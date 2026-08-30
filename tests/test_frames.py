"""Tests for frame extraction — mock ffmpeg, test timestamp formatting."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.analyze.frames import extract_frame, extract_frames_from_gaps, parse_srt_timestamp
from src.transcribe.visual_gaps import Gap


@patch("src.analyze.frames._run_cmd")
def test_extract_frame_calls_ffmpeg(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    video = tmp_path / "test.mp4"
    video.touch()
    output = tmp_path / "frame.jpg"

    result = extract_frame(video, 65.5, output)
    assert result == output
    cmd = mock_run.call_args[0][0]
    assert "-ss" in cmd
    assert "65.500" in cmd
    assert "-frames:v" in cmd
    assert "1" in cmd


@patch("src.analyze.frames._run_cmd")
def test_extract_frame_failure(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=1, stderr="error")
    video = tmp_path / "test.mp4"
    video.touch()
    output = tmp_path / "frame.jpg"

    result = extract_frame(video, 10.0, output)
    assert result is None


@patch("src.analyze.frames.extract_frame")
def test_extract_frames_from_gaps(mock_extract, tmp_path):
    mock_extract.side_effect = lambda v, t, o, **kw: o
    video = tmp_path / "test.mp4"
    video.touch()
    out_dir = tmp_path / "frames"
    out_dir.mkdir()

    gaps = [
        Gap(file="test.srt", subtitle_index=3,
            timestamp="00:01:05,000 --> 00:01:10,000",
            pattern="take a look", text="Take a look"),
        Gap(file="test.srt", subtitle_index=7,
            timestamp="00:02:30,500 --> 00:02:35,000",
            pattern="this chart", text="This chart"),
    ]

    paths = extract_frames_from_gaps(video, gaps, out_dir)
    assert len(paths) == 2
    assert mock_extract.call_count == 2


def test_parse_srt_timestamp():
    assert parse_srt_timestamp("01:02:03,500") == 3723.5
    assert parse_srt_timestamp("00:00:10,000") == 10.0
    assert parse_srt_timestamp("00:01:05,000") == 65.0
