from __future__ import annotations

from enum import Enum


class StepStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


PIPELINE_STEPS = ["record", "analyze", "transcribe", "correct", "find_gaps", "extract_frames", "ocr"]

STEP_DEPENDENCIES: dict[str, list[str]] = {
    "record": [],
    "analyze": ["record"],
    "transcribe": ["record"],
    "correct": ["transcribe"],
    "find_gaps": ["transcribe"],
    "extract_frames": ["find_gaps", "record"],
    "ocr": ["extract_frames"],
}


def derive_post_status(step_statuses: dict[str, StepStatus]) -> str:
    values = list(step_statuses.values())
    if not values:
        return "discovered"
    if any(v == StepStatus.RUNNING for v in values):
        return "in_progress"
    if all(v in (StepStatus.COMPLETED, StepStatus.SKIPPED) for v in values):
        return "completed"
    if any(v == StepStatus.FAILED for v in values):
        return "failed"
    if any(v == StepStatus.QUEUED for v in values):
        return "queued"
    if any(v == StepStatus.COMPLETED for v in values):
        return "partial"
    return "discovered"


def step_can_run(step: str, step_statuses: dict[str, StepStatus]) -> bool:
    if step not in STEP_DEPENDENCIES:
        raise ValueError(f"Unknown step: {step}")
    deps = STEP_DEPENDENCIES[step]
    return all(step_statuses.get(d) == StepStatus.COMPLETED for d in deps)
