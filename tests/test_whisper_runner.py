"""Tests for WhisperRunner — mock faster-whisper, test discovery and resumability."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.transcribe.whisper_runner import WhisperRunner, VIDEO_EXTS


@pytest.fixture
def runner():
    return WhisperRunner(model="tiny", device="cpu", workers=1)


def test_video_exts_includes_common():
    for ext in (".mp4", ".mkv", ".webm", ".mp3"):
        assert ext in VIDEO_EXTS


def test_discover_videos(tmp_path):
    (tmp_path / "video1.mp4").touch()
    (tmp_path / "video2.mkv").touch()
    (tmp_path / "readme.txt").touch()
    (tmp_path / "image.png").touch()
    runner = WhisperRunner()
    vids = runner._discover_videos(tmp_path)
    assert len(vids) == 2
    names = {v.name for v in vids}
    assert "video1.mp4" in names
    assert "video2.mkv" in names


def test_discover_videos_with_filter(tmp_path):
    (tmp_path / "Masterclass 1.mp4").touch()
    (tmp_path / "Masterclass 2.mp4").touch()
    (tmp_path / "Bonus.mp4").touch()
    runner = WhisperRunner()
    vids = runner._discover_videos(tmp_path, only="Masterclass 1")
    assert len(vids) == 1
    assert vids[0].name == "Masterclass 1.mp4"


def test_is_done_both_exist(tmp_path):
    (tmp_path / "test.txt").write_text("hello")
    (tmp_path / "test.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
    runner = WhisperRunner()
    assert runner._is_done("test", tmp_path) is True


def test_is_done_missing_srt(tmp_path):
    (tmp_path / "test.txt").write_text("hello")
    runner = WhisperRunner()
    assert runner._is_done("test", tmp_path) is False


def test_is_done_both_missing(tmp_path):
    runner = WhisperRunner()
    assert runner._is_done("test", tmp_path) is False


def test_fmt_ts():
    from src.transcribe.whisper_runner import fmt_ts
    assert fmt_ts(0.0) == "00:00:00,000"
    assert fmt_ts(3661.5) == "01:01:01,500"
    assert fmt_ts(59.999) == "00:00:59,999"


def test_transcribe_file_skips_done(tmp_path):
    video = tmp_path / "done.mp4"
    video.touch()
    out = tmp_path / "out"
    out.mkdir()
    (out / "done.txt").write_text("existing")
    (out / "done.srt").write_text("existing")
    runner = WhisperRunner()
    txt, srt = runner.transcribe_file(video, out)
    assert txt == out / "done.txt"
    assert srt == out / "done.srt"


def test_transcribe_file_calls_whisper(tmp_path):
    video = tmp_path / "new.mp4"
    video.touch()
    out = tmp_path / "out"
    out.mkdir()

    mock_segment = MagicMock()
    mock_segment.text = " Hello world "
    mock_segment.start = 0.0
    mock_segment.end = 1.5

    mock_info = MagicMock()
    mock_info.duration = 1.5

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    runner = WhisperRunner(model="tiny", device="cpu")
    runner._model = mock_model

    txt, srt = runner.transcribe_file(video, out)
    assert txt.exists()
    assert srt.exists()
    assert "Hello world" in txt.read_text()
    mock_model.transcribe.assert_called_once()


def test_transcribe_file_applies_corrections(tmp_path):
    video = tmp_path / "new.mp4"
    video.touch()
    out = tmp_path / "out"
    out.mkdir()

    rules_file = tmp_path / "rules.txt"
    rules_file.write_text("hello => GOODBYE\n")

    mock_segment = MagicMock()
    mock_segment.text = " hello world "
    mock_segment.start = 0.0
    mock_segment.end = 1.5

    mock_info = MagicMock()
    mock_info.duration = 1.5

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    runner = WhisperRunner(model="tiny", device="cpu")
    runner._model = mock_model

    txt, srt = runner.transcribe_file(video, out, corrections=rules_file)
    content = txt.read_text()
    assert "GOODBYE" in content
    assert "hello" not in content.lower().replace("goodbye", "")


def test_device_auto_selects_cpu_or_cuda():
    """Auto device detection should not raise."""
    runner = WhisperRunner(device="auto")
    detected = runner._detect_device()
    assert detected in ("cpu", "cuda")
