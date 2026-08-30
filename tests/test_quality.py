"""Tests for QualityAnalyzer — mock ffmpeg output, test verdict logic."""
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from src.analyze.quality import (
    QualityAnalyzer, QualityReport,
    compute_verdict, compute_trim_points,
)


@pytest.fixture
def analyzer():
    return QualityAnalyzer()


def test_quality_report_dataclass():
    r = QualityReport(
        filename="test.mkv", duration=1800.0,
        resolution=(1920, 1080), verdict="clean",
        black_frames=[], silence_gaps=[], bitrate_drops=[],
        freezes=[], notes="No issues",
    )
    assert r.filename == "test.mkv"
    assert r.resolution == (1920, 1080)


def test_verdict_clean():
    verdict, notes = compute_verdict(
        black_frames=[], freezes=[],
        silence_gaps=[], bitrate_drops=[],
        trim_start=None, trim_end=None,
    )
    assert verdict == "clean"


def test_verdict_trim_needed():
    verdict, _ = compute_verdict(
        black_frames=[{"location": "start", "duration": 2.0}],
        freezes=[], silence_gaps=[], bitrate_drops=[],
        trim_start=2.0, trim_end=None,
    )
    assert verdict == "trim_needed"


def test_verdict_has_issues_freezes():
    verdict, _ = compute_verdict(
        black_frames=[], silence_gaps=[], bitrate_drops=[],
        freezes=[{"duration": 5.0}],
        trim_start=None, trim_end=None,
    )
    assert verdict == "has_issues"


def test_verdict_re_record_long_freeze():
    verdict, _ = compute_verdict(
        black_frames=[], silence_gaps=[], bitrate_drops=[],
        freezes=[{"duration": 15.0}],
        trim_start=None, trim_end=None,
    )
    assert verdict == "re_record"


def test_verdict_re_record_many_freezes():
    verdict, _ = compute_verdict(
        black_frames=[], silence_gaps=[], bitrate_drops=[],
        freezes=[{"duration": 4.0}] * 5,
        trim_start=None, trim_end=None,
    )
    assert verdict == "re_record"


def test_verdict_re_record_long_silence():
    verdict, _ = compute_verdict(
        black_frames=[], freezes=[], bitrate_drops=[],
        silence_gaps=[{"duration": 35.0}],
        trim_start=None, trim_end=None,
    )
    assert verdict == "re_record"


def test_trim_points_start_black():
    trim_s, trim_e = compute_trim_points(
        duration=1800.0,
        black_frames=[{"location": "start", "start": 0.0, "end": 3.5, "duration": 3.5}],
    )
    assert trim_s == 3.5
    assert trim_e is None


def test_trim_points_end_black():
    trim_s, trim_e = compute_trim_points(
        duration=1800.0,
        black_frames=[{"location": "end", "start": 1795.0, "end": 1800.0, "duration": 5.0}],
    )
    assert trim_s is None
    assert trim_e == 1795.0


def test_trim_points_too_small_ignored():
    trim_s, trim_e = compute_trim_points(
        duration=1800.0,
        black_frames=[{"location": "start", "start": 0.0, "end": 0.3, "duration": 0.3}],
    )
    assert trim_s is None


@patch("src.analyze.quality._run_cmd")
def test_analyze_calls_ffprobe(mock_run, analyzer, tmp_path):
    video = tmp_path / "test.mkv"
    video.write_bytes(b"fake")

    probe_result = MagicMock()
    probe_result.returncode = 0
    probe_result.stdout = json.dumps({
        "format": {"duration": "1800.0", "bit_rate": "5000000"},
        "streams": [{"codec_type": "video", "width": 1920, "height": 1080, "codec_name": "h264"}],
    })

    empty_result = MagicMock()
    empty_result.returncode = 0
    empty_result.stderr = ""
    empty_result.stdout = ""

    mock_run.side_effect = [probe_result] + [empty_result] * 10

    report = analyzer.analyze(video)
    assert report.filename == "test.mkv"
    assert report.duration == 1800.0
    assert report.resolution == (1920, 1080)
    assert report.verdict == "clean"
