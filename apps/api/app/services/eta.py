from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from statistics import median
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models import Job, JobStageRun

TERMINAL_STATUSES = {"completed", "completed_degraded", "failed", "cancelled", "expired"}
COLLECTOR_STAGES = ("collecting_autohome", "collecting_dcd")
SERIAL_STAGES = ("postprocessing", "generating_hermes_outputs")
STAGE_DEFAULT_SECONDS = {
    "collecting_autohome": 1800,
    "collecting_dcd": 1800,
    "postprocessing": 300,
    "generating_hermes_outputs": 900,
}


@dataclass(frozen=True)
class EtaEstimate:
    estimated_remaining_seconds: int | None
    estimated_remaining_minutes: int | None
    eta_label: str
    eta_confidence: str

    def as_dict(self) -> dict[str, int | str | None]:
        return {
            "estimated_remaining_seconds": self.estimated_remaining_seconds,
            "estimated_remaining_minutes": self.estimated_remaining_minutes,
            "eta_label": self.eta_label,
            "eta_confidence": self.eta_confidence,
        }


def _label(minutes: int | None) -> str:
    if minutes is None:
        return "预计剩余时间计算中"
    return f"预计剩余 {minutes} 分钟"


def _done() -> EtaEstimate:
    return EtaEstimate(0, 0, _label(0), "done")


def _stage_duration_seconds(db: Session, stage_name: str) -> tuple[int, str]:
    durations = [
        int(row.duration_ms / 1000)
        for row in (
            db.query(JobStageRun)
            .filter(
                JobStageRun.stage_name == stage_name,
                JobStageRun.status.in_(("success", "degraded")),
                JobStageRun.duration_ms.isnot(None),
                JobStageRun.duration_ms > 0,
            )
            .order_by(JobStageRun.id.desc())
            .limit(25)
            .all()
        )
        if row.duration_ms
    ]
    if durations:
        return max(1, int(median(durations))), "history"
    return STAGE_DEFAULT_SECONDS[stage_name], "fallback"


def _stage_map(stages: Iterable[Any]) -> dict[str, Any]:
    return {str(getattr(stage, "name", "")): stage for stage in stages}


def _stage_is_complete(stage: Any | None) -> bool:
    return bool(stage and getattr(stage, "status", None) in {"success", "degraded", "completed"})


def _stage_progress(stage: Any | None) -> float:
    if stage is None:
        return 0.0
    if _stage_is_complete(stage):
        return 1.0
    percent = getattr(stage, "progress_percent", None)
    if percent is None:
        return 0.0
    try:
        numeric = float(percent)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric / 100))


def estimate_full_job_seconds(db: Session) -> EtaEstimate:
    total = 0
    confidence = "fallback"
    collector_seconds = []
    for stage_name in COLLECTOR_STAGES:
        seconds, source = _stage_duration_seconds(db, stage_name)
        collector_seconds.append(seconds)
        if source == "history":
            confidence = "history"
    total += max(collector_seconds) if collector_seconds else 0
    for stage_name in SERIAL_STAGES:
        seconds, source = _stage_duration_seconds(db, stage_name)
        total += seconds
        if source == "history":
            confidence = "history"
    minutes = ceil(total / 60)
    return EtaEstimate(total, minutes, _label(minutes), confidence)


def estimate_job_progress_eta(db: Session, job: Job, stages: Iterable[Any]) -> EtaEstimate:
    if job.status in TERMINAL_STATUSES or job.current_stage in TERMINAL_STATUSES:
        return _done()

    stages_by_name = _stage_map(stages)
    total_remaining = 0.0
    confidence = "fallback"

    collector_remaining = []
    for stage_name in COLLECTOR_STAGES:
        stage = stages_by_name.get(stage_name)
        if _stage_is_complete(stage):
            collector_remaining.append(0.0)
            continue
        seconds, source = _stage_duration_seconds(db, stage_name)
        collector_remaining.append(seconds * (1.0 - _stage_progress(stage)))
        if source == "history":
            confidence = "history"
    if collector_remaining:
        total_remaining += max(collector_remaining)

    for stage_name in SERIAL_STAGES:
        stage = stages_by_name.get(stage_name)
        if _stage_is_complete(stage):
            continue
        seconds, source = _stage_duration_seconds(db, stage_name)
        total_remaining += seconds * (1.0 - _stage_progress(stage))
        if source == "history":
            confidence = "history"

    remaining_seconds = max(0, int(round(total_remaining)))
    remaining_minutes = ceil(remaining_seconds / 60)
    return EtaEstimate(remaining_seconds, remaining_minutes, _label(remaining_minutes), confidence)
