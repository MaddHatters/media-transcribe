"""Tests for visual gap detection — pattern matching on SRT content."""
import pytest
from pathlib import Path
from src.transcribe.visual_gaps import (
    Gap, find_gaps, find_gaps_in_folder, parse_srt, DEFAULT_PATTERNS,
)

SAMPLE_SRT = """\
1
00:00:01,000 --> 00:00:05,000
Welcome to the course.

2
00:00:05,000 --> 00:00:10,000
Today we'll look at investing basics.

3
00:00:10,000 --> 00:00:15,000
Take a look at this chart on the screen.

4
00:00:15,000 --> 00:00:20,000
As you can see, the numbers are clear.

5
00:00:20,000 --> 00:00:25,000
Let's move on to the next topic.
"""


@pytest.fixture
def srt_file(tmp_path):
    f = tmp_path / "test.srt"
    f.write_text(SAMPLE_SRT, encoding="utf-8")
    return f


def test_parse_srt(srt_file):
    entries = parse_srt(srt_file)
    assert len(entries) == 5
    assert entries[0]["index"] == 1
    assert entries[0]["text"] == "Welcome to the course."
    assert "00:00:01" in entries[0]["timestamp"]


def test_find_gaps_detects_visual_patterns(srt_file):
    gaps = find_gaps(srt_file)
    assert len(gaps) >= 2
    patterns = [g.pattern for g in gaps]
    assert "take a look" in patterns
    assert "as you can see" in patterns


def test_find_gaps_includes_context(srt_file):
    gaps = find_gaps(srt_file)
    for gap in gaps:
        assert gap.context_before is not None
        assert gap.context_after is not None


def test_find_gaps_custom_patterns(srt_file):
    gaps = find_gaps(srt_file, patterns=["investing"])
    assert len(gaps) == 1
    assert gaps[0].pattern == "investing"


def test_find_gaps_no_matches(srt_file):
    gaps = find_gaps(srt_file, patterns=["xyznotfound"])
    assert gaps == []


def test_find_gaps_in_folder(tmp_path):
    (tmp_path / "lesson1.srt").write_text(SAMPLE_SRT, encoding="utf-8")
    (tmp_path / "lesson2.srt").write_text(SAMPLE_SRT, encoding="utf-8")
    result = find_gaps_in_folder(tmp_path)
    assert len(result) == 2
    assert "lesson1" in result
    assert "lesson2" in result


def test_find_gaps_in_folder_empty(tmp_path):
    result = find_gaps_in_folder(tmp_path)
    assert result == {}


def test_gap_dataclass():
    gap = Gap(
        file="test.srt", subtitle_index=3, timestamp="00:00:10,000 --> 00:00:15,000",
        pattern="take a look", text="Take a look at this chart.",
        context_before=[], context_after=[],
    )
    assert gap.file == "test.srt"
    assert gap.pattern == "take a look"


def test_default_patterns_not_empty():
    assert len(DEFAULT_PATTERNS) > 10
