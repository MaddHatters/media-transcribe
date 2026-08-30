"""Tests for BatchOrchestrator — queue, seen tracking, shuffle, breaks, summary."""
import json
import random
import time
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.capture.batch import (
    load_queue, load_seen, mark_seen, filter_unseen,
    mild_shuffle, human_break, print_summary,
    BatchOrchestrator, BatchConfig,
)


def test_load_queue_valid(tmp_path):
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps([
        {"url": "https://example.com/1", "filename": "video_1"},
        {"url": "https://example.com/2", "filename": "video_2"},
    ]))
    entries = load_queue(queue_file)
    assert len(entries) == 2
    assert entries[0]["url"] == "https://example.com/1"


def test_load_queue_invalid_json(tmp_path):
    queue_file = tmp_path / "queue.json"
    queue_file.write_text("not json {{{")
    with pytest.raises(json.JSONDecodeError):
        load_queue(queue_file)


def test_load_queue_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_queue(tmp_path / "nonexistent.json")


def test_load_queue_not_array(tmp_path):
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps({"url": "not an array"}))
    with pytest.raises(ValueError, match="JSON array"):
        load_queue(queue_file)


def test_load_queue_skips_missing_keys(tmp_path):
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps([
        {"url": "https://example.com/1", "filename": "video_1"},
        {"url": "https://example.com/2"},
        {"filename": "video_3"},
        {"url": "https://example.com/4", "filename": "video_4"},
    ]))
    entries = load_queue(queue_file)
    assert len(entries) == 2


def test_load_queue_skips_non_dict(tmp_path):
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps([
        {"url": "https://example.com/1", "filename": "video_1"},
        "just a string",
        42,
    ]))
    entries = load_queue(queue_file)
    assert len(entries) == 1


def test_load_seen_from_file(tmp_path):
    seen_file = tmp_path / "seen.txt"
    seen_file.write_text("https://example.com/1\nhttps://example.com/2\n")
    seen = load_seen(seen_file)
    assert seen == {"https://example.com/1", "https://example.com/2"}


def test_load_seen_missing_file(tmp_path):
    seen = load_seen(tmp_path / "nonexistent.txt")
    assert seen == set()


def test_mark_seen_appends(tmp_path):
    seen_file = tmp_path / "seen.txt"
    mark_seen("https://example.com/1", seen_file)
    mark_seen("https://example.com/2", seen_file)
    lines = seen_file.read_text().strip().splitlines()
    assert len(lines) == 2
    assert "https://example.com/1" in lines
    assert "https://example.com/2" in lines


def test_filter_unseen(tmp_path):
    seen_file = tmp_path / "seen.txt"
    seen_file.write_text("https://example.com/1\n")
    entries = [
        {"url": "https://example.com/1", "filename": "v1"},
        {"url": "https://example.com/2", "filename": "v2"},
        {"url": "https://example.com/3", "filename": "v3"},
    ]
    unseen, skipped = filter_unseen(entries, seen_file)
    assert len(unseen) == 2
    assert skipped == 1
    assert all(e["url"] != "https://example.com/1" for e in unseen)


def test_mild_shuffle_preserves_elements():
    random.seed(42)
    entries = [{"url": f"url_{i}"} for i in range(20)]
    shuffled = mild_shuffle(entries)
    assert len(shuffled) == len(entries)
    assert set(e["url"] for e in shuffled) == set(e["url"] for e in entries)


def test_mild_shuffle_length_preserved():
    entries = [{"url": f"url_{i}"} for i in range(50)]
    shuffled = mild_shuffle(entries)
    assert len(shuffled) == len(entries)


def test_mild_shuffle_some_swaps():
    random.seed(42)
    entries = [{"url": f"url_{i}"} for i in range(100)]
    shuffled = mild_shuffle(entries)
    swaps = sum(1 for a, b in zip(entries, shuffled) if a["url"] != b["url"])
    assert swaps > 0


def test_mild_shuffle_empty():
    assert mild_shuffle([]) == []


def test_mild_shuffle_single():
    entries = [{"url": "only"}]
    assert mild_shuffle(entries) == [{"url": "only"}]


def test_mild_shuffle_two():
    entries = [{"url": "a"}, {"url": "b"}]
    result = mild_shuffle(entries)
    assert len(result) == 2
    assert set(e["url"] for e in result) == {"a", "b"}


def test_human_break_timing():
    with patch("time.sleep") as mock_sleep:
        delay = human_break(1, 10)
    assert 300 <= delay <= 1500
    mock_sleep.assert_called()


def test_summary_reporting():
    results = [
        {"ok": True, "filename": "v1"},
        {"ok": True, "filename": "v2"},
        {"ok": False, "filename": "v3"},
    ]
    total_start = time.monotonic() - 3600
    summary = print_summary(results, total_start, skipped_seen=2)
    assert summary["total"] == 3
    assert summary["ok"] == 2
    assert summary["failed"] == 1
    assert summary["skipped_seen"] == 2
    assert summary["elapsed_seconds"] >= 3600


def test_filter_all_seen(tmp_path):
    seen_file = tmp_path / "seen.txt"
    seen_file.write_text("url1\nurl2\n")
    entries = [{"url": "url1"}, {"url": "url2"}]
    unseen, skipped = filter_unseen(entries, seen_file)
    assert len(unseen) == 0
    assert skipped == 2


def test_filter_none_seen(tmp_path):
    seen_file = tmp_path / "seen.txt"
    entries = [{"url": "url1"}, {"url": "url2"}]
    unseen, skipped = filter_unseen(entries, seen_file)
    assert len(unseen) == 2
    assert skipped == 0


# --- BatchOrchestrator tests ---


async def test_orchestrator_runs_full_loop(tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from src.capture.recorder import RecordResult

    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps([
        {"url": "https://example.com/1", "filename": "v1"},
        {"url": "https://example.com/2", "filename": "v2"},
    ]))
    seen_file = tmp_path / "seen.txt"

    recorder = MagicMock()
    recorder.record_one = AsyncMock(return_value=RecordResult(ok=True))

    cdp = AsyncMock()
    config = BatchConfig(
        queue_path=queue_file,
        seen_file=seen_file,
        shuffle=False,
        breaks=False,
        skip_preflight=True,
    )

    orch = BatchOrchestrator(recorder=recorder)
    summary = await orch.run(cdp, config)

    assert summary["total"] == 2
    assert summary["ok"] == 2
    assert recorder.record_one.call_count == 2
    # Both URLs marked as seen
    seen = load_seen(seen_file)
    assert "https://example.com/1" in seen
    assert "https://example.com/2" in seen


async def test_orchestrator_skips_seen(tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from src.capture.recorder import RecordResult

    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps([
        {"url": "https://example.com/1", "filename": "v1"},
        {"url": "https://example.com/2", "filename": "v2"},
    ]))
    seen_file = tmp_path / "seen.txt"
    seen_file.write_text("https://example.com/1\n")

    recorder = MagicMock()
    recorder.record_one = AsyncMock(return_value=RecordResult(ok=True))

    cdp = AsyncMock()
    config = BatchConfig(
        queue_path=queue_file,
        seen_file=seen_file,
        shuffle=False,
        breaks=False,
        skip_preflight=True,
    )

    orch = BatchOrchestrator(recorder=recorder)
    summary = await orch.run(cdp, config)

    assert summary["total"] == 1
    assert summary["skipped_seen"] == 1
    assert recorder.record_one.call_count == 1


async def test_orchestrator_aborts_on_preflight_failure(tmp_path):
    from unittest.mock import MagicMock, AsyncMock
    from src.capture.preflight import GateResult

    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps([{"url": "u", "filename": "f"}]))

    preflight = MagicMock()
    preflight.run_all.return_value = (
        False,
        [GateResult("Chrome CDP", False)],
    )

    recorder = MagicMock()
    recorder.record_one = AsyncMock()
    cdp = AsyncMock()
    config = BatchConfig(queue_path=queue_file, skip_preflight=False)

    orch = BatchOrchestrator(recorder=recorder, preflight=preflight)
    result = await orch.run(cdp, config)

    assert result["aborted"] is True
    recorder.record_one.assert_not_called()


async def test_orchestrator_health_check_called(tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from src.capture.recorder import RecordResult

    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps([
        {"url": "u1", "filename": "f1"},
        {"url": "u2", "filename": "f2"},
    ]))
    seen_file = tmp_path / "seen.txt"

    preflight = MagicMock()
    preflight.run_all.return_value = (True, [])
    preflight._ensure_chrome.return_value = True
    preflight._ensure_obs.return_value = True

    recorder = MagicMock()
    recorder.record_one = AsyncMock(return_value=RecordResult(ok=True))
    cdp = AsyncMock()

    config = BatchConfig(
        queue_path=queue_file,
        seen_file=seen_file,
        shuffle=False,
        breaks=False,
        skip_preflight=True,
    )

    orch = BatchOrchestrator(recorder=recorder, preflight=preflight)
    await orch.run(cdp, config)

    preflight._ensure_chrome.assert_called()
    preflight._ensure_obs.assert_called()


async def test_orchestrator_empty_queue(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps([
        {"url": "u1", "filename": "f1"},
    ]))
    seen_file = tmp_path / "seen.txt"
    seen_file.write_text("u1\n")

    recorder = MagicMock()
    cdp = AsyncMock()
    config = BatchConfig(
        queue_path=queue_file,
        seen_file=seen_file,
        skip_preflight=True,
    )

    orch = BatchOrchestrator(recorder=recorder)
    result = await orch.run(cdp, config)

    assert result["total"] == 0
    assert result["skipped_seen"] == 1
