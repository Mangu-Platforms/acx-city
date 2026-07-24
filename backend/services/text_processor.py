import re
from typing import List, Dict

# Marker inserted by structured ingesters (e.g. DOCX headings). Detected with
# top priority so real document structure beats regex guessing.
CHAPTER_MARKER = "@@CHAPTER@@"

# Minimum body length (characters) required before a heading-like line is
# accepted as a real chapter break. Raised from 100 → 500 (Fix #7) to prevent
# numbered list items and footnotes from creating micro-chapters.
_MIN_CHAPTER_BODY = 500

# Abbreviations that are safe to expand regardless of context.
# Extended list (Fix #8) covers the most common TTS mispronunciations.
_ABBREVIATIONS = {
    "Mr.": "Mister",
    "Mrs.": "Missus",
    "Ms.": "Miz",
    "Dr.": "Doctor",
    "Prof.": "Professor",
    "St.": "Saint",       # street context is rare in narrative prose
    "vs.": "versus",
    "etc.": "etcetera",
    "e.g.": "for example",
    "i.e.": "that is",
    "No.": "Number",
    "Vol.": "Volume",
    "Jr.": "Junior",
    "Sr.": "Senior",
    "Dept.": "Department",
    "approx.": "approximately",
}


class TextProcessor:
    """Chapter detection, cleanup, and provider-sized chunking.

    Order matters: chapters are detected on the RAW text (which still has line
    breaks), and cleanup happens per chapter afterwards.
    """

    # A heading must be a short standalone line to count as a chapter break.
    # Fix #7: numeric pattern now requires ≤ 8 words after the number so plain
    # list items like "1. Mix dry ingredients in a bowl" are not treated as
    # chapter headings.
    _HEADING_PATTERNS = [
        r"^(chapter|part|book|prologue|epilogue|interlude|appendix)\b[\s\.:—-]*.{0,60}$",
        r"^\d{1,3}[\.\):]?\s*(?:\S+\s*){0,7}$",   # up to 8 words after the number
        r"^[IVXLCDM]{1,7}[\.\):]?\s*.{0,60}$",    # roman numerals
        r"^\*{3,}\s*$",                             # *** separators
    ]

    def split_by_chapters(self, text: str) -> List[Dict]:
        if CHAPTER_MARKER in text:
            return self._split_by_marker(text)
        return self._split_by_heuristics(text)

    def _split_by_marker(self, text: str) -> List[Dict]:
        chapters = []
        title = "Front Matter"
        buf: List[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith(CHAPTER_MARKER):
                body = "\n".join(buf).strip()
                if body:
                    chapters.append({"title": title, "text": body})
                title = stripped[len(CHAPTER_MARKER):].strip() or f"Chapter {len(chapters) + 1}"
                buf = []
            else:
                buf.append(line)
        body = "\n".join(buf).strip()
        if body:
            chapters.append({"title": title, "text": body})
        return chapters or [{"title": "Full Book", "text": text.strip()}]

    def _split_by_heuristics(self, text: str) -> List[Dict]:
        pattern = re.compile("|".join(self._HEADING_PATTERNS), re.IGNORECASE)
        chapters = []
        title = "Introduction"
        buf: List[str] = []

        for line in text.split("\n"):
            stripped = line.strip()
            if stripped and len(stripped) <= 80 and pattern.match(stripped):
                body = "\n".join(buf).strip()
                # Fix #7: raised minimum body from 100 → _MIN_CHAPTER_BODY so
                # numbered list items followed by short paragraphs don't create
                # spurious chapter breaks.
                if len(body) > _MIN_CHAPTER_BODY:
                    chapters.append({"title": title, "text": body})
                    buf = []
                    title = stripped
                elif not chapters and not body:
                    title = stripped
                else:
                    buf.append(line)
            else:
                buf.append(line)

        body = "\n".join(buf).strip()
        if len(body) > _MIN_CHAPTER_BODY or not chapters:
            chapters.append({"title": title, "text": body or text.strip()})
        return chapters

    def preprocess_text(self, text: str) -> str:
        """Cleanup applied per chapter, preserving paragraph breaks."""
        paragraphs = re.split(r"\n\s*\n", text)
        cleaned = []
        for para in paragraphs:
            p = re.sub(r"\s+", " ", para).strip()
            if p:
                cleaned.append(p)
        text = "\n\n".join(cleaned)

        # Fix #8: expanded abbreviation table; removed the (?=\s[A-Z]) lookahead
        # so end-of-sentence uses ("Dr. Smith said") are caught too.
        for abbr, full in _ABBREVIATIONS.items():
            text = re.sub(
                rf"(?<!\w){re.escape(abbr)}",
                full,
                text,
            )
        return text.strip()

    def chunk_for_provider(self, text: str, max_chars: int) -> List[str]:
        """Split chapter text into provider-sized chunks on paragraph, then
        sentence boundaries.

        Fix #6: size is measured in UTF-8 bytes, not code-point count, so
        multi-byte characters (em-dashes, curly quotes, accented names) don't
        silently push a chunk over the provider's byte limit (Polly: 3 000 B).

        Fix #4: chunks that are blank after stripping are discarded so
        whitespace-only text is never sent to a TTS provider.
        """
        encoded_len = lambda s: len(s.encode("utf-8"))  # noqa: E731

        if encoded_len(text) <= max_chars:
            stripped = text.strip()
            return [stripped] if stripped else []

        chunks: List[str] = []
        current = ""

        def flush() -> None:
            nonlocal current
            stripped = current.strip()
            # Fix #4: discard empty / whitespace-only chunks.
            if stripped:
                chunks.append(stripped)
            current = ""

        for para in text.split("\n\n"):
            if encoded_len(current) + encoded_len(para) + 2 <= max_chars:
                current += para + "\n\n"
                continue
            flush()
            if encoded_len(para) <= max_chars:
                current = para + "\n\n"
                continue
            # Paragraph itself too long: split by sentences.
            for sent in re.split(r"(?<=[.!?])\s+", para):
                if encoded_len(current) + encoded_len(sent) + 1 <= max_chars:
                    current += sent + " "
                else:
                    flush()
                    # Pathological run-on: hard-split on byte boundary.
                    encoded = sent.encode("utf-8")
                    while len(encoded) > max_chars:
                        # Decode up to max_chars bytes, respecting char boundary.
                        chunk_bytes = encoded[:max_chars]
                        chunk_str = chunk_bytes.decode("utf-8", errors="ignore")
                        if chunk_str.strip():
                            chunks.append(chunk_str.strip())
                        encoded = encoded[len(chunk_bytes):]
                    current = encoded.decode("utf-8") + " "
        flush()
        # Fix #4: final safety — if everything was whitespace, return a single
        # hard-truncated chunk rather than an empty list.
        if not chunks:
            fallback = text.strip()
            if fallback:
                chunks.append(fallback[:max_chars])
        return chunks

    # Backwards compatibility for existing callers/tests
    def split_large_chapter(self, text: str, max_chars: int = 100000) -> List[str]:
        return self.chunk_for_provider(text, max_chars)
