"""Text scrubbing — remove/normalize artifacts that break TTS or billing."""

from __future__ import annotations

import re
from typing import Callable

# The scrubbing regex catalog. Each entry is (name, pattern, replacement_or_handler).
# Order matters — earlier rules can create patterns that later rules consume.

SCRUB_RULES: list[tuple[str, re.Pattern, str | Callable[[re.Match], str]]] = [
    # Normalize unicode dashes to em-dash.
    # Single hyphens inside words (e.g. "water-stained") must survive,
    # so only em-dash, en-dash, and runs of 2+ hyphens are rewritten.
    (
        "normalize_dashes",
        re.compile(r"(—|–|--+)"),
        "—",
    ),
    # Remove page numbers (standalone numbers on a line)
    (
        "remove_page_numbers",
        re.compile(r"^\s*\d{1,5}\s*$", re.MULTILINE),
        "",
    ),
    # Remove common header/footer patterns
    (
        "remove_headers_footers",
        re.compile(
            r"^(Chapter\s+\d+|CHAPTER\s+\d+|Part\s+\d+|PART\s+\d+)\s*$",
            re.MULTILINE,
        ),
        "",  # These get reconstructed from chapterization
    ),
    # Normalize multiple spaces
    (
        "normalize_spaces",
        re.compile(r"[^\S\n]+"),
        " ",
    ),
    # Normalize multiple blank lines to double newline
    (
        "normalize_blank_lines",
        re.compile(r"\n{3,}"),
        "\n\n",
    ),
    # Remove zero-width characters
    (
        "remove_zero_width",
        re.compile(r"[\u200b\u200c\u200d\ufeff]"),
        "",
    ),
    # Normalize quotation marks (optional, depends on TTS engine)
    (
        "normalize_quotes",
        re.compile(r"[\u201c\u201d\u00ab\u00bb]"),
        '"',
    ),
    # Normalize ellipsis
    (
        "normalize_ellipsis",
        re.compile(r"\.{4,}|\.{3}"),
        "…",
    ),
    # Remove bracket stage directions [laughs], (whispers), etc.
    (
        "remove_stage_directions",
        re.compile(r"\[(?:laughs|whispers|sighs|clears throat|etc\.?)\]", re.IGNORECASE),
        "",
    ),
    # Strip trailing whitespace per line
    (
        "strip_trailing",
        re.compile(r"[ \t]+$", re.MULTILINE),
        "",
    ),
]


def scrub_text(text: str, rules: list[str] | None = None) -> tuple[str, list[str]]:
    """Apply scrubbing rules to text.

    Args:
        text: Raw extracted text.
        rules: Optional list of rule names to apply. None = all rules.

    Returns:
        Tuple of (scrubbed_text, list_of_rules_applied).
    """
    applied = []
    for name, pattern, replacement in SCRUB_RULES:
        if rules is not None and name not in rules:
            continue
        text = pattern.sub(replacement, text)
        applied.append(name)

    return text, applied
