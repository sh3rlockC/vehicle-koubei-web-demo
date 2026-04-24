from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from worker_app.artifacts import JobPaths, ensure_job_dirs
from worker_app.progress import ProgressSink
from worker_app.stages import StageCommand, StageExecutionError, resolve_stage_command


@dataclass
class JobContext:
    job_id: str
    model_name: str
    artifact_root: str | Path
    allow_single_platform_fallback: bool = True


@dataclass
class StageResult:
    status: str
    artifact_paths: list[str] = field(default_factory=list)
    output_metadata: dict = field(default_factory=dict)


class StageRunner(Protocol):
    def __call__(self, command: StageCommand, job_paths: JobPaths, progress_sink: ProgressSink) -> StageResult: ...


PipelineObserver = Callable[[dict[str, Any]], None]


@dataclass
class PipelineResult:
    status: str
    degraded: bool
    completed_stages: list[str]
    failed_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def _write_job_meta(job_paths: JobPaths, payload: dict) -> None:
    (job_paths.meta / "job.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _emit(observer: PipelineObserver | None, payload: dict[str, Any]) -> None:
    if observer is not None:
        observer(payload)


def run_pipeline(
    context: JobContext,
    stage_commands: list[StageCommand],
    runner: StageRunner,
    observer: PipelineObserver | None = None,
) -> PipelineResult:
    job_paths = ensure_job_dirs(context.artifact_root, context.job_id)
    progress_sink = ProgressSink(
        job_id=context.job_id,
        progress_path=job_paths.progress / "progress.json",
        stages=[stage.name for stage in stage_commands],
    )
    _write_job_meta(
        job_paths,
        {
            "job_id": context.job_id,
            "model_name": context.model_name,
            "stages": [stage.name for stage in stage_commands],
        },
    )

    completed_stages: list[str] = []
    degraded = False
    collector_failures: set[str] = set()
    single_platform_mode = False

    total = max(len(stage_commands), 1)
    for index, stage in enumerate(stage_commands, start=1):
        resolved_stage = resolve_stage_command(stage, single_platform_mode=single_platform_mode)
        if resolved_stage is None:
            degraded = True
            snapshot = progress_sink.update(
                stage=stage.name,
                status="degraded",
                message="skipped in single-platform fallback",
                overall_percent=int(index * 100 / total),
                degraded=True,
            )
            _emit(
                observer,
                {
                    "type": "stage_degraded",
                    "job_id": context.job_id,
                    "stage": stage.name,
                    "snapshot": snapshot,
                    "message": "skipped in single-platform fallback",
                    "error_code": None,
                    "error_message": None,
                    "result": None,
                },
            )
            continue

        snapshot = progress_sink.update(
            stage=stage.name,
            status="running",
            message=f"running {stage.name}",
            overall_percent=int((index - 1) * 100 / total),
            degraded=degraded,
        )
        _emit(
            observer,
            {
                "type": "stage_running",
                "job_id": context.job_id,
                "stage": stage.name,
                "snapshot": snapshot,
                "command": resolved_stage.command,
            },
        )
        try:
            stage_result = runner(resolved_stage, job_paths, progress_sink)
            completed_stages.append(stage.name)
            snapshot = progress_sink.update(
                stage=stage.name,
                status="success",
                message=f"completed {stage.name}",
                overall_percent=int(index * 100 / total),
                degraded=degraded,
            )
            _emit(
                observer,
                {
                    "type": "stage_success",
                    "job_id": context.job_id,
                    "stage": stage.name,
                    "snapshot": snapshot,
                    "result": stage_result,
                },
            )
        except StageExecutionError as exc:
            is_collector = stage.name in {"collecting_autohome", "collecting_dcd"}
            can_fallback = (
                stage.name == "collecting_dcd"
                and context.allow_single_platform_fallback
                and "collecting_autohome" in completed_stages
                and not collector_failures
            )
            if is_collector and can_fallback:
                collector_failures.add(stage.name)
                degraded = True
                single_platform_mode = True
                snapshot = progress_sink.update(
                    stage=stage.name,
                    status="degraded",
                    message=f"single-platform fallback after {exc.stage}",
                    overall_percent=int(index * 100 / total),
                    degraded=True,
                )
                _emit(
                    observer,
                    {
                        "type": "stage_degraded",
                        "job_id": context.job_id,
                        "stage": stage.name,
                        "snapshot": snapshot,
                        "message": f"single-platform fallback after {exc.stage}",
                        "error_code": exc.error_code,
                        "error_message": exc.message,
                        "result": None,
                    },
                )
                continue

            if not stage.core:
                degraded = True
                snapshot = progress_sink.update(
                    stage=stage.name,
                    status="degraded",
                    message=exc.message,
                    overall_percent=int(index * 100 / total),
                    degraded=True,
                )
                _emit(
                    observer,
                    {
                        "type": "stage_degraded",
                        "job_id": context.job_id,
                        "stage": stage.name,
                        "snapshot": snapshot,
                        "message": exc.message,
                        "error_code": exc.error_code,
                        "error_message": exc.message,
                        "result": None,
                    },
                )
                continue

            snapshot = progress_sink.update(
                stage=stage.name,
                status="failed",
                message=exc.message,
                overall_percent=int(index * 100 / total),
                degraded=degraded,
            )
            _emit(
                observer,
                {
                    "type": "stage_failed",
                    "job_id": context.job_id,
                    "stage": stage.name,
                    "snapshot": snapshot,
                    "message": exc.message,
                    "error_code": exc.error_code,
                    "error_message": exc.message,
                    "result": None,
                },
            )
            pipeline_result = PipelineResult(
                status="failed",
                degraded=degraded,
                completed_stages=completed_stages,
                failed_stage=stage.name,
                error_code=exc.error_code,
                error_message=exc.message,
            )
            _emit(
                observer,
                {
                    "type": "pipeline_completed",
                    "job_id": context.job_id,
                    "result": pipeline_result,
                },
            )
            return pipeline_result

    final_status = "completed_degraded" if degraded else "completed"
    snapshot = progress_sink.update(
        stage=final_status,
        status=final_status,
        message="pipeline completed",
        overall_percent=100,
        degraded=degraded,
    )
    pipeline_result = PipelineResult(
        status=final_status,
        degraded=degraded,
        completed_stages=completed_stages,
    )
    _emit(
        observer,
        {
            "type": "pipeline_completed",
            "job_id": context.job_id,
            "snapshot": snapshot,
            "result": pipeline_result,
        },
    )
    return pipeline_result
