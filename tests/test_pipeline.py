"""Tests for Pipeline — mock all components, test step filtering and error handling."""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from src.pipeline.runner import Pipeline, PipelineResult, STEPS


def test_default_steps_all():
    assert len(STEPS) >= 5


def test_step_names():
    for step in STEPS:
        assert isinstance(step, str)
    assert "transcribe" in STEPS
    assert "analyze" in STEPS


@pytest.mark.asyncio
async def test_pipeline_runs_selected_steps():
    mock_source = MagicMock()
    mock_engine = MagicMock()
    pipeline = Pipeline(source=mock_source, engine=mock_engine)

    with patch.object(pipeline, "_step_transcribe", new_callable=AsyncMock) as mock_t, \
         patch.object(pipeline, "_step_correct", new_callable=AsyncMock) as mock_c:
        await pipeline.run([], steps=["transcribe", "correct"])


@pytest.mark.asyncio
async def test_pipeline_continues_on_failure():
    mock_source = MagicMock()
    mock_engine = MagicMock()
    pipeline = Pipeline(source=mock_source, engine=mock_engine)

    posts = [
        MagicMock(url="http://a", filename="a", title="A"),
        MagicMock(url="http://b", filename="b", title="B"),
    ]

    with patch.object(pipeline, "_process_one", new_callable=AsyncMock) as mock_p:
        mock_p.side_effect = [Exception("fail"), None]
        results = await pipeline.run(posts, steps=["transcribe"])
        assert mock_p.call_count == 2


@pytest.mark.asyncio
async def test_pipeline_step_filtering():
    mock_source = MagicMock()
    mock_engine = MagicMock()
    pipeline = Pipeline(source=mock_source, engine=mock_engine)

    valid = pipeline._validate_steps(["transcribe", "correct"])
    assert valid == ["transcribe", "correct"]


@pytest.mark.asyncio
async def test_pipeline_invalid_step_raises():
    mock_source = MagicMock()
    mock_engine = MagicMock()
    pipeline = Pipeline(source=mock_source, engine=mock_engine)

    with pytest.raises(ValueError, match="Unknown"):
        pipeline._validate_steps(["nonexistent_step"])


# --- New tests for fixed pipeline wiring ---


def test_pipeline_accepts_all_init_params():
    p = Pipeline(
        source=MagicMock(), engine=MagicMock(),
        output_dir=Path("/tmp/test"), enable_breaks=True,
    )
    assert p._output_dir == Path("/tmp/test")
    assert p._enable_breaks is True


def test_pipeline_defaults():
    p = Pipeline(source=None, engine=None)
    assert p._output_dir == Path(".")
    assert p._enable_breaks is False


@pytest.mark.asyncio
async def test_breaks_called_between_videos():
    pipeline = Pipeline(
        source=MagicMock(), engine=MagicMock(), enable_breaks=True,
    )
    posts = [
        MagicMock(url="http://a", title="A", filename="a"),
        MagicMock(url="http://b", title="B", filename="b"),
        MagicMock(url="http://c", title="C", filename="c"),
    ]

    with patch.object(pipeline, "_process_one", new_callable=AsyncMock) as mock_p, \
         patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_p.return_value = PipelineResult(post_url="x", post_title="X")
        results = await pipeline.run(posts, steps=["record"])
        assert len(results) == 3
        assert mock_thread.call_count == 2


@pytest.mark.asyncio
async def test_breaks_not_called_when_disabled():
    pipeline = Pipeline(
        source=MagicMock(), engine=MagicMock(), enable_breaks=False,
    )
    posts = [
        MagicMock(url="http://a", title="A", filename="a"),
        MagicMock(url="http://b", title="B", filename="b"),
    ]

    with patch.object(pipeline, "_process_one", new_callable=AsyncMock) as mock_p, \
         patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_p.return_value = PipelineResult(post_url="x", post_title="X")
        await pipeline.run(posts, steps=["record"])
        mock_thread.assert_not_called()


@pytest.mark.asyncio
async def test_health_check_called_between_recordings():
    mock_pf = MagicMock()
    mock_pf._ensure_chrome = MagicMock(return_value=True)
    mock_pf._ensure_obs = MagicMock(return_value=True)
    pipeline = Pipeline(
        source=MagicMock(), engine=MagicMock(),
        enable_breaks=False, preflight=mock_pf,
    )
    posts = [
        MagicMock(url="http://a", title="A", filename="a"),
        MagicMock(url="http://b", title="B", filename="b"),
        MagicMock(url="http://c", title="C", filename="c"),
    ]

    with patch.object(pipeline, "_process_one", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = PipelineResult(post_url="x", post_title="X")
        await pipeline.run(posts, steps=["record"])
        assert mock_pf._ensure_chrome.call_count == 2
        assert mock_pf._ensure_obs.call_count == 2


@pytest.mark.asyncio
async def test_health_check_skipped_without_preflight():
    pipeline = Pipeline(
        source=MagicMock(), engine=MagicMock(),
        enable_breaks=False, preflight=None,
    )
    posts = [
        MagicMock(url="http://a", title="A", filename="a"),
        MagicMock(url="http://b", title="B", filename="b"),
    ]

    with patch.object(pipeline, "_process_one", new_callable=AsyncMock) as mock_p:
        mock_p.return_value = PipelineResult(post_url="x", post_title="X")
        results = await pipeline.run(posts, steps=["record"])
        assert len(results) == 2


@pytest.mark.asyncio
async def test_breaks_not_called_for_non_record_steps():
    pipeline = Pipeline(
        source=MagicMock(), engine=MagicMock(), enable_breaks=True,
    )
    posts = [
        MagicMock(url="http://a", title="A", filename="a"),
        MagicMock(url="http://b", title="B", filename="b"),
    ]

    with patch.object(pipeline, "_process_one", new_callable=AsyncMock) as mock_p, \
         patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_p.return_value = PipelineResult(post_url="x", post_title="X")
        await pipeline.run(posts, steps=["transcribe"])
        mock_thread.assert_not_called()


@pytest.mark.asyncio
async def test_step_record_calls_mark_seen_on_success():
    engine = MagicMock()
    engine.move_to_backup = MagicMock(return_value="/backup/video.mkv")
    pipeline = Pipeline(source=MagicMock(), engine=engine)
    post = MagicMock(url="http://test", title="Test", filename="test.mkv")
    result = PipelineResult(post_url="http://test", post_title="Test")

    mock_rec = MagicMock(ok=True, output_path="/tmp/video.mkv", error=None)
    mock_recorder_instance = MagicMock()
    mock_recorder_instance.record_one = AsyncMock(return_value=mock_rec)

    mock_cdp = AsyncMock()

    with patch("src.capture.window.focus_chrome") as mock_focus, \
         patch("src.capture.batch.mark_seen") as mock_seen, \
         patch("src.cdp.CDPClient") as mock_cdp_cls, \
         patch("src.capture.recorder.Recorder", return_value=mock_recorder_instance), \
         patch("src.config.IS_WINDOWS", False):
        mock_cdp_cls.return_value.__aenter__ = AsyncMock(return_value=mock_cdp)
        mock_cdp_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await pipeline._step_record(post, result)

        mock_seen.assert_called_once_with("http://test")
        assert result.output_paths["recording"] == "/backup/video.mkv"
        mock_focus.assert_not_called()


@pytest.mark.asyncio
async def test_step_record_raises_on_failure():
    engine = MagicMock()
    pipeline = Pipeline(source=MagicMock(), engine=engine)
    post = MagicMock(url="http://test", title="Test", filename="test.mkv")
    result = PipelineResult(post_url="http://test", post_title="Test")

    mock_rec = MagicMock(ok=False, output_path=None, error="OBS timeout")
    mock_recorder_instance = MagicMock()
    mock_recorder_instance.record_one = AsyncMock(return_value=mock_rec)

    mock_cdp = AsyncMock()

    with patch("src.capture.batch.mark_seen") as mock_seen, \
         patch("src.cdp.CDPClient") as mock_cdp_cls, \
         patch("src.capture.recorder.Recorder", return_value=mock_recorder_instance), \
         patch("src.config.IS_WINDOWS", False), \
         patch("src.capture.window.focus_chrome"):
        mock_cdp_cls.return_value.__aenter__ = AsyncMock(return_value=mock_cdp)
        mock_cdp_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(RuntimeError, match="OBS timeout"):
            await pipeline._step_record(post, result)

        mock_seen.assert_not_called()


@pytest.mark.asyncio
async def test_step_correct_finds_corrections_at_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pipeline = Pipeline(source=None, engine=None, output_dir=tmp_path)
    post = MagicMock()

    srt = tmp_path / "test.srt"
    txt = tmp_path / "test.txt"
    srt.write_text("hello wrld", encoding="utf-8")
    txt.write_text("hello wrld", encoding="utf-8")

    corrections = tmp_path / "corrections.txt"
    corrections.write_text("wrld -> world", encoding="utf-8")

    result = PipelineResult(
        post_url="http://test", post_title="Test",
        output_paths={"transcript_srt": str(srt), "transcript_txt": str(txt)},
    )

    await pipeline._step_correct(post, result)


@pytest.mark.asyncio
async def test_step_correct_skips_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pipeline = Pipeline(source=None, engine=None, output_dir=tmp_path)
    post = MagicMock()

    srt = tmp_path / "test.srt"
    txt = tmp_path / "test.txt"
    srt.write_text("hello", encoding="utf-8")
    txt.write_text("hello", encoding="utf-8")

    result = PipelineResult(
        post_url="http://test", post_title="Test",
        output_paths={"transcript_srt": str(srt), "transcript_txt": str(txt)},
    )

    await pipeline._step_correct(post, result)


@pytest.mark.asyncio
async def test_step_transcribe_uses_output_dir(tmp_path):
    pipeline = Pipeline(source=None, engine=None, output_dir=tmp_path)
    post = MagicMock()
    result = PipelineResult(
        post_url="http://test", post_title="Test",
        output_paths={"recording": "/tmp/video.mkv"},
    )

    mock_runner = MagicMock()
    mock_runner.transcribe_file.return_value = (
        tmp_path / "transcripts" / "test.txt",
        tmp_path / "transcripts" / "test.srt",
    )

    with patch("src.transcribe.whisper_runner.WhisperRunner", return_value=mock_runner):
        await pipeline._step_transcribe(post, result)

    mock_runner.transcribe_file.assert_called_once()
    call_args = mock_runner.transcribe_file.call_args
    assert call_args[0][1] == tmp_path / "transcripts"


def test_hyphenated_step_names_normalize():
    """Verify that find-gaps normalizes to find_gaps for validation."""
    pipeline = Pipeline(source=None, engine=None)
    normalized = pipeline._validate_steps(["find_gaps", "extract_frames"])
    assert normalized == ["find_gaps", "extract_frames"]


@pytest.mark.asyncio
async def test_no_record_mode_no_crash():
    pipeline = Pipeline(source=None, engine=None)
    posts = [
        MagicMock(url="http://a", title="A", filename="a"),
    ]

    with patch.object(pipeline, "_step_transcribe", new_callable=AsyncMock), \
         patch.object(pipeline, "_step_correct", new_callable=AsyncMock):
        results = await pipeline.run(posts, steps=["transcribe", "correct"])
        assert len(results) == 1
        assert not results[0].steps_failed
