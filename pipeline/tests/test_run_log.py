"""Tests for the JSONL run log."""

import pytest
from pathlib import Path
from pipeline.run_log import RunLog


def test_append_and_read(tmp_path):
    log = RunLog(tmp_path)
    log.append("test_event", key="value")
    entries = log.read_all()
    assert len(entries) == 1
    assert entries[0]["event"] == "test_event"
    assert entries[0]["key"] == "value"
    assert "ts" in entries[0]


def test_append_multiple(tmp_path):
    log = RunLog(tmp_path)
    log.append("event_1")
    log.append("event_2")
    log.append("event_3")
    entries = log.read_all()
    assert len(entries) == 3


def test_last_event(tmp_path):
    log = RunLog(tmp_path)
    log.append("first")
    log.append("last")
    assert log.last_event()["event"] == "last"


def test_empty_log(tmp_path):
    log = RunLog(tmp_path)
    assert log.read_all() == []
    assert log.last_event() is None


def test_filter_by_run_id(tmp_path):
    log = RunLog(tmp_path)
    log.append("event_a", run_id="run-1")
    log.append("event_b", run_id="run-2")
    log.append("event_c", run_id="run-1")
    filtered = log.events_for_run("run-1")
    assert len(filtered) == 2
    assert all(e["run_id"] == "run-1" for e in filtered)
