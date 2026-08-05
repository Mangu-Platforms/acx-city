"""Tests for the pipeline configuration system."""

import pytest
from pipeline.config import PipelineConfig, ConfigValidationError


def test_config_defaults():
    """Default config should be valid."""
    cfg = PipelineConfig()
    errors = cfg.validate()
    assert errors == [], f"Default config has errors: {errors}"


def test_config_rejects_empty_manuscript():
    """Manuscript path must not be empty."""
    cfg = PipelineConfig(manuscript_path="")
    errors = cfg.validate()
    assert any("manuscript" in e.lower() for e in errors)


def test_config_rejects_negative_max_chapters():
    """max_chapters must be positive."""
    cfg = PipelineConfig(max_chapters=-1)
    errors = cfg.validate()
    assert any("max_chapters" in e.lower() for e in errors)


def test_config_auto_mode_boolean():
    """auto_mode must be a bool."""
    cfg = PipelineConfig(auto_mode=True)
    assert cfg.auto_mode is True


def test_config_to_dict():
    """Config serializes cleanly."""
    cfg = PipelineConfig()
    d = cfg.to_dict()
    assert isinstance(d, dict)
    assert "manuscript_path" in d
