"""Chapter detection and splitting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Chapter:
    """A detected chapter."""

    number: int
    title: str
    text: str
    start_offset: int = 0  # character offset in original
    word_count: int = 0

    def __post_init__(self):
        self.word_count = len(self.text.split())


# Common chapter heading patterns
CHAPTER_PATTERNS = [
    # "Chapter 1", "Chapter One", "CHAPTER 1"
    re.compile(
        r"^(?:Chapter|CHAPTER)\s+"
        r"(?:(\d+)|([IVXLCDM]+)|(\w+))"  # arabic, roman, or word numeral
        r"(?:\s*[:\.\-—]\s*(.+))?$",
        re.MULTILINE,
    ),
    # "Part 1", "PART ONE"
    re.compile(
        r"^(?:Part|PART)\s+"
        r"(?:(\d+)|([IVXLCDM]+)|(\w+))"
        r"(?:\s*[:\.\-—]\s*(.+))?$",
        re.MULTILINE,
    ),
    # Standalone numbered headings: "1.", "1:", "1 — Title"
    re.compile(
        r"^(\d{1,3})\s*[\.:\-—]\s*(.+)$",
        re.MULTILINE,
    ),
]


def _parse_numeral(s: str) -> int:
    """Convert a numeral string to an integer. Handles arabic, roman, word."""
    if not s:
        return 0

    # Try arabic
    if s.isdigit():
        return int(s)

    # Try roman numerals (simple implementation)
    roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    upper = s.upper()
    if all(c in roman_map for c in upper):
        result = 0
        prev = 0
        for c in reversed(upper):
            val = roman_map[c]
            if val < prev:
                result -= val
            else:
                result += val
            prev = val
        if 1 <= result <= 999:
            return result

    # Try word numerals
    word_nums = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    }
    val = word_nums.get(s.lower())
    if val is not None:
        return val

    return 0


def detect_chapters(text: str) -> list[re.Match]:
    """Find all chapter heading matches in text, using the best pattern."""
    for pattern in CHAPTER_PATTERNS:
        matches = list(pattern.finditer(text))
        if len(matches) >= 1:  # Single-chapter books are valid
            return matches
    return []


def chapterize(text: str) -> tuple[list[Chapter], str | None]:
    """Split text into chapters.

    Returns:
        Tuple of (chapters, detection_method).
        If no chapters detected, returns ([], None) and the full text
        should be treated as a single chapter.
    """
    matches = detect_chapters(text)

    if not matches:
        return [], None

    # Determine which pattern matched
    # (for now, just use the matches we found)
    chapters = []

    # Prologue: text before first chapter heading
    prologue_text = text[: matches[0].start()].strip()
    if prologue_text:
        chapters.append(
            Chapter(number=0, title="Prologue", text=prologue_text, start_offset=0)
        )

    for i, match in enumerate(matches):
        # Extract chapter number and title from groups
        groups = match.groups()
        num = 0
        title = match.group(0).strip()

        for g in groups[:3]:  # First three groups are numeral variants
            if g:
                num = _parse_numeral(g)
                break

        if num == 0:
            num = i + 1

        # Title is the last non-None group after the numeral
        for g in reversed(groups[3:]):
            if g:
                title = g.strip()
                break

        # Extract text between this heading and the next (or end)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chapter_text = text[start:end].strip()

        if chapter_text:  # Skip empty chapters
            chapters.append(
                Chapter(
                    number=num,
                    title=title,
                    text=chapter_text,
                    start_offset=match.start(),
                )
            )

    return chapters, "pattern_matching"
