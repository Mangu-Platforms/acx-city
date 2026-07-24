import re
from typing import List, Dict

# Marker inserted by structured ingesters (e.g. DOCX headings). Detected with
# top priority so real document structure beats regex guessing.
CHAPTER_MARKER = "@@CHAPTER@@"


class TextProcessor:
    """Chapter detection, cleanup, and provider-sized chunking.

    Order matters: chapters are detected on the RAW text (which still has line
    breaks), and cleanup happens per chapter afterwards.
    """

    # A heading must be a short standalone line to count as a chapter break.
    _HEADING_PATTERNS = [
        r"^(chapter|part|book|prologue|epilogue|interlude|appendix)\b[\s\.:—-]*.{0,60}$",
        r"^\d{1,3}[\.\):]?\s*.{0,60}$",          # "12." / "12) The Storm"
        r"^[IVXLCDM]{1,7}[\.\):]?\s*.{0,60}$",    # roman numerals
        r"^\*{3,}\s*$",                            # *** separators
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
                # Require some body so consecutive heading-ish lines don't
                # create empty chapters.
                if len(body) > 100:
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
        if len(body) > 100 or not chapters:
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

        # Only expand abbreviations that are safe out of context.
        for abbr, full in {"Mr.": "Mister", "Mrs.": "Missus", "Ms.": "Miz", "Dr.": "Doctor"}.items():
            text = re.sub(rf"(?<!\w){re.escape(abbr)}(?=\s[A-Z])", full, text)
        return text.strip()

    def chunk_for_provider(self, text: str, max_chars: int) -> List[str]:
        """Split chapter text into provider-sized chunks on paragraph, then
        sentence boundaries."""
        if len(text) <= max_chars:
            return [text]

        chunks: List[str] = []
        current = ""

        def flush():
            nonlocal current
            if current.strip():
                chunks.append(current.strip())
            current = ""

        for para in text.split("\n\n"):
            if len(current) + len(para) + 2 <= max_chars:
                current += para + "\n\n"
                continue
            flush()
            if len(para) <= max_chars:
                current = para + "\n\n"
                continue
            # Paragraph itself too long: split by sentences.
            for sent in re.split(r"(?<=[.!?])\s+", para):
                if len(current) + len(sent) + 1 <= max_chars:
                    current += sent + " "
                else:
                    flush()
                    while len(sent) > max_chars:  # pathological run-on
                        chunks.append(sent[:max_chars])
                        sent = sent[max_chars:]
                    current = sent + " "
        flush()
        return chunks or [text[:max_chars]]

    # Backwards compatibility for existing callers/tests
    def split_large_chapter(self, text: str, max_chars: int = 100000) -> List[str]:
        return self.chunk_for_provider(text, max_chars)
