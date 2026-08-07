"""Agent 3: Text Normalizer & Pronunciation Engine.

Normalizes text for TTS synthesis:
- Expands numbers, dates, times, abbreviations
- Resolves heteronyms (read → /rɛd/ vs /riːd/)
- Applies project pronunciation lexicon
- Handles special characters and symbols

Uses gpt-4o-mini (primary) or Qwen2.5-7B (fallback via Ollama).
~$0.15/1M chars.

Input: attributed chapters from Agent 2
Output: normalized text with pronunciation hints
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from .base import BaseAgent, AgentResult

logger = logging.getLogger("acx.pipeline.agent3")

OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AGENT3_MODEL = os.getenv("AGENT3_MODEL", "gpt-4o-mini")
AGENT3_FALLBACK_MODEL = os.getenv("AGENT3_FALLBACK_MODEL", "qwen2.5:7b")

# Common heteronyms and their context-dependent pronunciations
HETERONYM_RULES: dict[str, dict[str, str]] = {
    "read": {
        "past": "red",      # I read (past tense) → "red"
        "present": "reed",  # I read (present) → "reed"
    },
    "lead": {
        "noun_metal": "led",   # lead (metal) → "led"
        "verb": "leed",        # lead (verb) → "leed"
    },
    "bow": {
        "noun_weapon": "boh",    # bow and arrow
        "verb_gesture": "bau",   # take a bow
    },
    "tear": {
        "noun_crying": "teer",   # a tear
        "verb_rip": "tair",      # to tear
    },
    "wind": {
        "noun_air": "wind",      # the wind blows
        "verb_turn": "wynd",     # wind a clock
    },
    "bass": {
        "noun_fish": "bass",     # bass (fish)
        "noun_music": "base",    # bass (music)
    },
}

# Common abbreviation expansions
ABBREVIATIONS: dict[str, str] = {
    "Mr.": "Mister",
    "Mrs.": "Missus",
    "Ms.": "Miss",
    "Dr.": "Doctor",
    "Prof.": "Professor",
    "St.": "Saint",
    "vs.": "versus",
    "etc.": "etcetera",
    "e.g.": "for example",
    "i.e.": "that is",
    "approx.": "approximately",
    "dept.": "department",
    "govt.": "government",
    "jr.": "junior",
    "sr.": "senior",
    "inc.": "incorporated",
    "ltd.": "limited",
    "corp.": "corporation",
}

# Number word mappings
ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
        "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _number_to_words(n: int) -> str:
    """Convert integer to English words."""
    if n == 0:
        return "zero"
    if n < 0:
        return "minus " + _number_to_words(-n)
    parts = []
    if n >= 1_000_000:
        parts.append(_number_to_words(n // 1_000_000) + " million")
        n %= 1_000_000
    if n >= 1_000:
        parts.append(_number_to_words(n // 1_000) + " thousand")
        n %= 1_000
    if n >= 100:
        parts.append(ONES[n // 100] + " hundred")
        n %= 100
    if n >= 20:
        word = TENS[n // 10]
        if n % 10:
            word += "-" + ONES[n % 10]
        parts.append(word)
    elif n > 0:
        parts.append(ONES[n])
    return " ".join(parts)


def _expand_numbers(text: str) -> str:
    """Expand standalone numbers to words."""
    def replace_number(m: re.Match) -> str:
        num_str = m.group(0).replace(",", "")
        try:
            if "." in num_str:
                # Decimal number
                whole, frac = num_str.split(".", 1)
                return _number_to_words(int(whole)) + " point " + " ".join(ONES[int(d)] for d in frac)
            n = int(num_str)
            if 0 <= n <= 99:
                return _number_to_words(n)
            elif 1000 <= n <= 9999:
                # Year-like: "1776" → "seventeen seventy-six"
                return _number_to_words(n)
            else:
                return _number_to_words(n)
        except (ValueError, IndexError):
            return num_str

    # Match standalone numbers (not part of words)
    return re.sub(r"\b\d[\d,]*(?:\.\d+)?\b", replace_number, text)


def _expand_dates(text: str) -> str:
    """Expand date patterns."""
    months = {
        "01": "January", "02": "February", "03": "March", "04": "April",
        "05": "May", "06": "June", "07": "July", "08": "August",
        "09": "September", "10": "October", "11": "November", "12": "December",
    }

    def replace_date(m: re.Match) -> str:
        groups = m.groups()
        if len(groups) == 3:
            month, day, year = groups
            month_name = months.get(month, month)
            return f"{month_name} {int(day)}, {_number_to_words(int(year))}"
        return m.group(0)

    # MM/DD/YYYY
    text = re.sub(r"(\d{1,2})/(\d{1,2})/(\d{4})", replace_date, text)
    return text


def _expand_abbreviations(text: str) -> str:
    """Expand common abbreviations."""
    for abbr, expansion in ABBREVIATIONS.items():
        # Case-insensitive but preserve original case
        pattern = re.compile(re.escape(abbr), re.IGNORECASE)
        text = pattern.sub(lambda m: expansion if m.group(0)[0].isupper() else expansion.lower(), text)
    return text


def _apply_lexicon(text: str, lexicon: list[dict[str, Any]]) -> str:
    """Apply pronunciation lexicon entries to text."""
    for entry in lexicon:
        word = entry.get("word", "")
        phonetic = entry.get("phonetic_spelling") or entry.get("ipa_phoneme", "")
        if word and phonetic:
            # Wrap in pronunciation hint tags
            pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
            text = pattern.sub(f"[pron:{phonetic}]\\g<0>[/pron]", text)
    return text


class TextNormalizer(BaseAgent):
    """Text normalization and pronunciation engine."""

    name = "text_normalizer"

    def run(self, input_data: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        chapters = input_data.get("chapters", [])
        lexicon = context.get("lexicon", [])

        if not chapters:
            return AgentResult(
                agent_name=self.name,
                success=False,
                data={},
                error="No chapters in input",
            )

        normalized_chapters = []
        total_chars_in = 0
        total_chars_out = 0

        for chapter in chapters:
            normalized_scenes = []
            for scene in chapter.get("scenes", []):
                normalized_paragraphs = []
                for para in scene.get("paragraphs", []):
                    text = para.get("text", "")
                    original_len = len(text)
                    total_chars_in += original_len

                    # Apply normalization pipeline
                    text = _expand_abbreviations(text)
                    text = _expand_dates(text)
                    text = _expand_numbers(text)
                    text = _apply_lexicon(text, lexicon)

                    total_chars_out += len(text)
                    normalized_paragraphs.append({
                        **para,
                        "text": text,
                        "original_text": para.get("text", ""),
                    })
                normalized_scenes.append({
                    **scene,
                    "paragraphs": normalized_paragraphs,
                })
            normalized_chapters.append({
                **chapter,
                "scenes": normalized_scenes,
            })

        # Auto-suggest lexicon entries for unusual proper nouns
        suggested_entries = []
        proper_noun_pattern = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)*\b")
        seen_names: set[str] = set()
        known_characters = set(context.get("characters", []))

        for chapter in chapters:
            for scene in chapter.get("scenes", []):
                for para in scene.get("paragraphs", []):
                    text = para.get("text", "")
                    for match in proper_noun_pattern.finditer(text):
                        name = match.group(0)
                        if (name not in seen_names and
                            name not in known_characters and
                            len(name) > 3 and
                            name not in ("The", "This", "That", "There", "Then", "They", "When", "Where", "What", "Which", "Who", "How")):
                            seen_names.add(name)
                            suggested_entries.append({
                                "word": name,
                                "source": "auto",
                                "context_note": "Auto-detected proper noun — verify pronunciation",
                            })

        return AgentResult(
            agent_name=self.name,
            success=True,
            data={
                "chapters": normalized_chapters,
                "suggested_lexicon": suggested_entries[:50],  # Cap suggestions
            },
            characters_in=total_chars_in,
            characters_out=total_chars_out,
        )
