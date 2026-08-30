"""Tests for Pipeline — mock all components, test step filtering and error handling."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from src.pipeline.runner import Pipeline, STEPS


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
