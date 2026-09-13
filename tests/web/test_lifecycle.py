from __future__ import annotations

import pytest

from web.lifecycle import (
    PIPELINE_STEPS,
    StepStatus,
    derive_post_status,
    step_can_run,
)


def _make_statuses(default: StepStatus, **overrides: StepStatus) -> dict[str, StepStatus]:
    return {s: overrides.get(s, default) for s in PIPELINE_STEPS}


class TestDerivePostStatus:
    def test_all_pending(self):
        assert derive_post_status(_make_statuses(StepStatus.PENDING)) == "discovered"

    def test_any_running(self):
        statuses = _make_statuses(StepStatus.PENDING, record=StepStatus.RUNNING)
        assert derive_post_status(statuses) == "in_progress"

    def test_running_takes_priority_over_failed(self):
        statuses = _make_statuses(StepStatus.PENDING, record=StepStatus.FAILED, transcribe=StepStatus.RUNNING)
        assert derive_post_status(statuses) == "in_progress"

    def test_all_completed(self):
        assert derive_post_status(_make_statuses(StepStatus.COMPLETED)) == "completed"

    def test_all_skipped(self):
        assert derive_post_status(_make_statuses(StepStatus.SKIPPED)) == "completed"

    def test_mix_completed_and_skipped(self):
        statuses = _make_statuses(StepStatus.COMPLETED, analyze=StepStatus.SKIPPED)
        assert derive_post_status(statuses) == "completed"

    def test_any_failed_none_running(self):
        statuses = _make_statuses(StepStatus.PENDING, record=StepStatus.FAILED)
        assert derive_post_status(statuses) == "failed"

    def test_any_queued_none_running(self):
        statuses = _make_statuses(StepStatus.PENDING, record=StepStatus.QUEUED)
        assert derive_post_status(statuses) == "queued"

    def test_some_completed_some_pending(self):
        statuses = _make_statuses(StepStatus.PENDING, record=StepStatus.COMPLETED)
        assert derive_post_status(statuses) == "partial"

    def test_queued_and_completed(self):
        statuses = _make_statuses(StepStatus.PENDING, record=StepStatus.COMPLETED, transcribe=StepStatus.QUEUED)
        assert derive_post_status(statuses) == "queued"

    def test_empty_dict(self):
        assert derive_post_status({}) == "discovered"

    def test_subset_of_steps(self):
        statuses = {"record": StepStatus.COMPLETED, "transcribe": StepStatus.PENDING}
        assert derive_post_status(statuses) == "partial"


class TestStepCanRun:
    def test_record_always_can_run(self):
        statuses = _make_statuses(StepStatus.PENDING)
        assert step_can_run("record", statuses) is True

    def test_transcribe_blocked_when_record_pending(self):
        statuses = _make_statuses(StepStatus.PENDING)
        assert step_can_run("transcribe", statuses) is False

    def test_transcribe_can_run_when_record_completed(self):
        statuses = _make_statuses(StepStatus.PENDING, record=StepStatus.COMPLETED)
        assert step_can_run("transcribe", statuses) is True

    def test_extract_frames_needs_both_deps(self):
        statuses = _make_statuses(StepStatus.PENDING, find_gaps=StepStatus.COMPLETED)
        assert step_can_run("extract_frames", statuses) is False

        statuses["record"] = StepStatus.COMPLETED
        assert step_can_run("extract_frames", statuses) is True

    def test_ocr_needs_extract_frames(self):
        statuses = _make_statuses(StepStatus.PENDING)
        assert step_can_run("ocr", statuses) is False

        statuses["extract_frames"] = StepStatus.COMPLETED
        assert step_can_run("ocr", statuses) is True

    def test_unknown_step_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown step"):
            step_can_run("nonexistent", _make_statuses(StepStatus.PENDING))


class TestPipelineStepsSync:
    def test_matches_runner_steps(self):
        from src.pipeline.runner import STEPS

        assert PIPELINE_STEPS == STEPS
