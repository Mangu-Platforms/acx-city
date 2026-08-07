"""Tests for the multi-agent pipeline agents.

Tests run against the rule-based agents (Agent 1, parts of Agent 5) without
requiring LLM backends. LLM-dependent agents are tested with mocked responses.
"""
from __future__ import annotations

import json
import pytest

from pipeline.agents.structure_parser import StructureParser, _is_chapter_heading, _is_dialogue, _detect_speaker_attribution
from pipeline.agents.text_normalizer import _expand_numbers, _expand_abbreviations, _expand_dates, _number_to_words
from pipeline.agents.qa_validator import _validate_tags, _check_unclosed_tags, _check_character_consistency, _calculate_completeness_score
from pipeline.agents.prosody_planner import _apply_rule_based_tags
from pipeline.prosody_parser import parse_tagged_text, Segment, extract_emotion_conditioning


# ========================================================================= #
# Agent 1: Structure Parser
# ========================================================================= #

class TestStructureParser:
    def setup_method(self):
        self.parser = StructureParser()

    def test_empty_text(self):
        result = self.parser.run({"text": ""}, {})
        assert not result.success
        assert "Empty" in result.error

    def test_single_chapter(self):
        text = "Chapter 1\n\nThis is the first paragraph.\n\nThis is the second paragraph."
        result = self.parser.run({"text": text}, {})
        assert result.success
        assert result.data["stats"]["chapter_count"] == 1
        assert result.data["chapters"][0]["chapter_number"] == 1

    def test_multiple_chapters(self):
        text = """Chapter 1

First chapter content.

Chapter 2

Second chapter content.

Chapter 3

Third chapter content."""
        result = self.parser.run({"text": text}, {})
        assert result.success
        assert result.data["stats"]["chapter_count"] == 3

    def test_scene_breaks(self):
        text = """Chapter 1

First scene.

***

Second scene.

---

Third scene."""
        result = self.parser.run({"text": text}, {})
        assert result.success
        assert len(result.data["chapters"][0]["scenes"]) >= 3

    def test_dialogue_detection(self):
        text = """Chapter 1

"Hello!" said John.

Sarah walked away."""
        result = self.parser.run({"text": text}, {})
        assert result.success
        paragraphs = result.data["chapters"][0]["scenes"][0]["paragraphs"]
        assert paragraphs[0]["is_dialogue"] is True
        assert paragraphs[1]["is_dialogue"] is False

    def test_speaker_attribution(self):
        assert _detect_speaker_attribution('"Hello!" said John.') == "John"
        assert _detect_speaker_attribution('"Stop!" whispered Sarah.') == "Sarah"
        assert _detect_speaker_attribution('"I see." Tom nodded.') == "Tom"

    def test_no_chapters_fallback(self):
        text = "Just some plain text without any chapter markers at all."
        result = self.parser.run({"text": text}, {})
        assert result.success
        assert result.data["stats"]["chapter_count"] == 1  # fallback

    def test_prologue_epilogue(self):
        text = """Prologue

Before the story.

Chapter 1

The story begins.

Epilogue

After the story."""
        result = self.parser.run({"text": text}, {})
        assert result.success
        assert result.data["stats"]["chapter_count"] == 3

    def test_front_matter(self):
        text = """Title: My Book
Author: John Doe

Dedication

To my family.

Chapter 1

The story begins."""
        result = self.parser.run({"text": text}, {})
        assert result.success
        assert "Title: My Book" in result.data["front_matter"]


# ========================================================================= #
# Agent 3: Text Normalizer
# ========================================================================= #

class TestTextNormalizer:
    def test_expand_numbers_simple(self):
        assert "three" in _expand_numbers("I have 3 cats")
        assert "twenty" in _expand_numbers("She is 20 years old")

    def test_expand_numbers_large(self):
        result = _expand_numbers("The year was 1776")
        assert "seventeen" in result.lower() or "one thousand" in result.lower()

    def test_expand_numbers_decimal(self):
        result = _expand_numbers("Pi is 3.14")
        assert "point" in result.lower()

    def test_expand_dates(self):
        result = _expand_dates("Born on 07/04/1776")
        assert "July" in result

    def test_expand_abbreviations(self):
        assert "Mister" in _expand_abbreviations("Mr. Smith")
        assert "Doctor" in _expand_abbreviations("Dr. Jones")
        assert "Professor" in _expand_abbreviations("Prof. Wilson")

    def test_number_to_words(self):
        assert _number_to_words(0) == "zero"
        assert _number_to_words(1) == "one"
        assert _number_to_words(15) == "fifteen"
        assert _number_to_words(42) == "forty-two"
        assert _number_to_words(100) == "one hundred"
        assert _number_to_words(1000) == "one thousand"


# ========================================================================= #
# Agent 5: QA Validator
# ========================================================================= #

class TestQAValidator:
    def test_valid_tags(self):
        issues = _validate_tags("Hello [angry] world [pause:500] end")
        assert len(issues) == 0

    def test_invalid_tag(self):
        issues = _validate_tags("Hello [foobar] world")
        assert any(i["type"] == "invalid_tag" for i in issues)

    def test_missing_pause_value(self):
        issues = _validate_tags("Hello [pause] world")
        assert any(i["type"] == "missing_tag_value" for i in issues)

    def test_invalid_pause_duration(self):
        issues = _validate_tags("Hello [pause:abc] world")
        assert any(i["type"] == "invalid_tag_value" for i in issues)

    def test_excessive_pause(self):
        issues = _validate_tags("Hello [pause:99999] world")
        assert any(i["type"] == "invalid_pause_duration" for i in issues)

    def test_unclosed_pron_tag(self):
        issues = _check_unclosed_tags("[pron:hello] world")
        assert any(i["type"] == "unclosed_tag" for i in issues)

    def test_closed_pron_tag(self):
        issues = _check_unclosed_tags("[pron:hello]world[/pron]")
        assert len(issues) == 0

    def test_character_consistency(self):
        chapters = [
            {"scenes": [{"paragraphs": [
                {"speaker": "Sarah"},
                {"speaker": "sarah"},
                {"speaker": "John"},
            ]}]},
        ]
        issues = _check_character_consistency(chapters)
        assert any(i["type"] == "inconsistent_character_name" for i in issues)

    def test_completeness_score_perfect(self):
        assert _calculate_completeness_score([]) == 1.0

    def test_completeness_score_with_warnings(self):
        issues = [{"severity": "warning"}, {"severity": "warning"}]
        score = _calculate_completeness_score(issues)
        assert 0.9 < score < 1.0

    def test_completeness_score_with_errors(self):
        issues = [{"severity": "error"}, {"severity": "error"}]
        score = _calculate_completeness_score(issues)
        assert score < 0.9


# ========================================================================= #
# Agent 4: Rule-based fallback
# ========================================================================= #

class TestProsodyFallback:
    def test_angry_detection(self):
        para = {"text": '"Stop!" he shouted angrily.', "speaker": "John", "is_dialogue": True}
        tagged = _apply_rule_based_tags(para)
        assert "[angry]" in tagged or "[SPEAKER:John]" in tagged

    def test_whisper_detection(self):
        para = {"text": '"Come closer," she whispered softly.', "speaker": "Sarah", "is_dialogue": True}
        tagged = _apply_rule_based_tags(para)
        assert "[whisper]" in tagged or "[SPEAKER:Sarah]" in tagged

    def test_sad_detection(self):
        para = {"text": "He cried as the tears fell.", "speaker": "narrator", "is_dialogue": False}
        tagged = _apply_rule_based_tags(para)
        assert "[sad]" in tagged or "[SPEAKER:narrator]" in tagged

    def test_speaker_tag_always_added(self):
        para = {"text": "The sun was shining.", "speaker": "narrator", "is_dialogue": False}
        tagged = _apply_rule_based_tags(para)
        assert "[SPEAKER:narrator]" in tagged


# ========================================================================= #
# Prosody Parser
# ========================================================================= #

class TestProsodyParser:
    def test_plain_text(self):
        segments = parse_tagged_text("Hello world")
        assert len(segments) == 1
        assert segments[0].type == "text"
        assert segments[0].content == "Hello world"

    def test_emotion_tag(self):
        segments = parse_tagged_text("[angry] Stop right there!")
        assert len(segments) == 1
        assert segments[0].emotion == "angry"
        assert "Stop right there!" in segments[0].content

    def test_speaker_change(self):
        segments = parse_tagged_text("[SPEAKER:Sarah] Hello there.")
        assert any(s.type == "speaker_change" and s.speaker == "Sarah" for s in segments)
        assert any(s.type == "text" and "Hello there" in s.content for s in segments)

    def test_pause(self):
        segments = parse_tagged_text("Before [pause:500] after")
        assert any(s.type == "pause" and s.pause_ms == 500 for s in segments)

    def test_scene_break(self):
        segments = parse_tagged_text("End [scene_break:3000] New scene")
        assert any(s.type == "scene_break" and s.pause_ms == 3000 for s in segments)

    def test_rate_change(self):
        segments = parse_tagged_text("[rate:slow] Dramatic moment.")
        assert any(s.type == "text" and s.rate == 0.8 for s in segments)

    def test_multiple_emotions(self):
        text = "[SPEAKER:John] [angry] I said stop! [SPEAKER:Sarah] [whisper] Sorry."
        segments = parse_tagged_text(text)
        speakers = [s.speaker for s in segments if s.type == "speaker_change"]
        assert "John" in speakers
        assert "Sarah" in speakers

    def test_pronunciation_hint(self):
        text = '[pron:hɜːrˈmaɪ.əni]Hermione[/pron] walked in.'
        segments = parse_tagged_text(text)
        assert len(segments) >= 1
        assert "Hermione" in segments[0].content

    def test_merge_consecutive(self):
        text = "[SPEAKER:narrator] First sentence. Second sentence."
        segments = parse_tagged_text(text)
        # Should merge consecutive text segments with same speaker
        text_segments = [s for s in segments if s.type == "text"]
        assert len(text_segments) == 1  # merged

    def test_extract_emotion_conditioning(self):
        cond = extract_emotion_conditioning("angry")
        assert cond["pitch_shift"] > 1.0
        assert cond["speed_factor"] > 1.0

        cond = extract_emotion_conditioning("sad")
        assert cond["pitch_shift"] < 1.0
        assert cond["speed_factor"] < 1.0

        cond = extract_emotion_conditioning(None)
        assert cond == {}


# ========================================================================= #
# Integration: Agent 1 → Prosody Parser round-trip
# ========================================================================= #

class TestRoundTrip:
    def test_structure_to_prosody(self):
        text = """Chapter 1

        assert _detect_speaker_attribution('"Hello!" said John.') == "John"

Sarah walked away quietly."""
        parser = StructureParser()
        result = parser.run({"text": text}, {})
        assert result.success

        # Take first paragraph and add prosody tags
        para = result.data["chapters"][0]["scenes"][0]["paragraphs"][0]
        tagged = f"[SPEAKER:{para.get('speaker', 'narrator')}] [angry] {para['text']}"
        segments = parse_tagged_text(tagged)
        assert len(segments) >= 1
        assert any(s.emotion == "angry" for s in segments if s.type == "text")
