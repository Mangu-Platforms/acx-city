"""Tests for Stage 0 ingestion."""

import pytest
from pathlib import Path
from pipeline.ingest.extract import extract_text, ExtractionError
from pipeline.ingest.scrub import scrub_text
from pipeline.ingest.chapterize import chapterize, _parse_numeral


class TestExtraction:
    def test_txt_extraction(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_text("Hello world\n\nSecond paragraph.")
        result = extract_text(p)
        assert "Hello world" in result
        assert "Second paragraph" in result

    def test_missing_file(self):
        with pytest.raises(ExtractionError, match="not found"):
            extract_text("/nonexistent/path.txt")

    def test_unsupported_format(self, tmp_path):
        p = tmp_path / "test.xyz"
        p.write_text("data")
        with pytest.raises(ExtractionError, match="Unsupported"):
            extract_text(p)


class TestScrub:
    def test_removes_page_numbers(self):
        text = "Chapter One\n\nOnce upon a time.\n\n2\n\nThe end."
        result, rules = scrub_text(text)
        assert "Once upon a time" in result
        assert "\n2\n" not in result

    def test_normalizes_whitespace(self):
        text = "Hello   world\t\tthere"
        result, _ = scrub_text(text)
        assert "  " not in result
        assert "\t" not in result

    def test_removes_zero_width(self):
        text = "He\u200bllo\u200d wo\u200brld"
        result, _ = scrub_text(text)
        assert "\u200b" not in result
        assert "Hello world" in result

    def test_applies_all_rules_by_default(self):
        text = "test"
        result, rules = scrub_text(text)
        assert len(rules) > 0

    def test_selective_rules(self):
        text = "Hello   world"
        result, rules = scrub_text(text, rules=["normalize_spaces"])
        assert "normalize_spaces" in rules
        assert "Hello world" in result


class TestChapterize:
    def test_detects_chapter_headings(self):
        text = """Chapter 1: The Beginning

Once upon a time there was a story.

Chapter 2: The Middle

The story continued.

Chapter 3: The End

And it ended."""
        chapters, method = chapterize(text)
        assert len(chapters) == 3
        assert chapters[0].title == "The Beginning"
        assert chapters[1].title == "The Middle"
        assert chapters[2].title == "The End"

    def test_no_chapters(self):
        text = "Just a plain text without any chapter headings."
        chapters, method = chapterize(text)
        assert chapters == []
        assert method is None

    def test_prologue(self):
        text = """Prologue

Some introduction text.

Chapter 1: First

The actual story begins."""
        chapters, method = chapterize(text)
        assert len(chapters) == 2
        assert chapters[0].title == "Prologue"
        assert chapters[0].number == 0

    def test_word_count(self):
        text = """Chapter 1: Test

This is a test chapter with exactly ten words here for verification purposes."""
        chapters, _ = chapterize(text)
        assert len(chapters) == 1
        assert chapters[0].word_count > 0


class TestParseNumeral:
    def test_arabic(self):
        assert _parse_numeral("42") == 42

    def test_roman(self):
        assert _parse_numeral("IV") == 4
        assert _parse_numeral("XII") == 12
        assert _parse_numeral("III") == 3

    def test_word(self):
        assert _parse_numeral("one") == 1
        assert _parse_numeral("twenty") == 20

    def test_invalid(self):
        assert _parse_numeral("xyz") == 0
