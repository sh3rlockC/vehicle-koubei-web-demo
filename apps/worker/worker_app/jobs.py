from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
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


COLLECTOR_STAGE_NAMES = {"collecting_autohome", "collecting_dcd"}


@dataclass
class CollectorGroupResult:
    completed_stages: list[str] = field(default_factory=list)
    degraded: bool = False
    single_platform_mode: bool = False
    failed_result: PipelineResult | None = None


def _write_job_meta(job_paths: JobPaths, payload: dict) -> None:
    (job_paths.meta / "job.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _emit(observer: PipelineObserver | None, payload: dict[str, Any]) -> None:
    if observer is not None:
        observer(payload)


def _looks_like_parallel_collector_group(
    stage_commands: list[StageCommand],
    index: int,
    *,
    single_platform_mode: bool,
) -> bool:
    if single_platform_mode or index + 1 >= len(stage_commands):
        return False
    current_stage = stage_commands[index]
    next_stage = stage_commands[index + 1]
    return {current_stage.name, next_stage.name} == COLLECTOR_STAGE_NAMES


def _stage_running(
    *,
    context: JobContext,
    stage: StageCommand,
    resolved_stage: StageCommand,
    stage_index: int,
    total: int,
    degraded: bool,
    progress_sink: ProgressSink,
    observer: PipelineObserver | None,
) -> None:
    snapshot = progress_sink.update(
        stage=stage.name,
        status="running",
        message=f"running {stage.name}",
        overall_percent=int((stage_index - 1) * 100 / total),
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


def _stage_success(
    *,
    context: JobContext,
    stage: StageCommand,
    stage_index: int,
    total: int,
    degraded: bool,
    result: StageResult,
    completed_stages: list[str],
    progress_sink: ProgressSink,
    observer: PipelineObserver | None,
) -> None:
    completed_stages.append(stage.name)
    stage_status = "degraded" if result.status == "degraded" else "success"
    snapshot = progress_sink.update(
        stage=stage.name,
        status=stage_status,
        message=f"completed {stage.name}" if stage_status == "success" else f"completed {stage.name} with degraded output",
        overall_percent=int(stage_index * 100 / total),
        degraded=degraded or stage_status == "degraded",
    )
    _emit(
        observer,
        {
            "type": "stage_success",
            "job_id": context.job_id,
            "stage": stage.name,
            "snapshot": snapshot,
            "result": result,
        },
    )


def _stage_degraded(
    *,
    context: JobContext,
    stage: StageCommand,
    stage_index: int,
    total: int,
    message: str,
    error_code: str | None,
    error_message: str | None,
    progress_sink: ProgressSink,
    observer: PipelineObserver | None,
) -> None:
    snapshot = progress_sink.update(
        stage=stage.name,
        status="degraded",
        message=message,
        overall_percent=int(stage_index * 100 / total),
        degraded=True,
    )
    _emit(
        observer,
        {
            "type": "stage_degraded",
            "job_id": context.job_id,
            "stage": stage.name,
            "snapshot": snapshot,
            "message": message,
            "error_code": error_code,
            "error_message": error_message,
            "result": None,
        },
    )


def _stage_failed(
    *,
    context: JobContext,
    stage: StageCommand,
    stage_index: int,
    total: int,
    exc: StageExecutionError,
    degraded: bool,
    progress_sink: ProgressSink,
    observer: PipelineObserver | None,
) -> PipelineResult:
    snapshot = progress_sink.update(
        stage=stage.name,
        status="failed",
        message=exc.message,
        overall_percent=int(stage_index * 100 / total),
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
    return PipelineResult(
        status="failed",
        degraded=degraded,
        completed_stages=[],
        failed_stage=stage.name,
        error_code=exc.error_code,
        error_message=exc.message,
    )


def _run_parallel_collectors(
    *,
    context: JobContext,
    stage_commands: list[StageCommand],
    start_index: int,
    total: int,
    runner: StageRunner,
    job_paths: JobPaths,
    progress_sink: ProgressSink,
    observer: PipelineObserver | None,
    degraded: bool,
) -> CollectorGroupResult:
    stages = [(stage_commands[start_index], start_index + 1), (stage_commands[start_index + 1], start_index + 2)]
    resolved_stages: list[tuple[StageCommand, StageCommand, int]] = []
    for stage, stage_index in stages:
        resolved_stage = resolve_stage_command(stage, single_platform_mode=False)
        if resolved_stage is None:
            continue
        resolved_stages.append((stage, resolved_stage, stage_index))
        _stage_running(
            context=context,
            stage=stage,
            resolved_stage=resolved_stage,
            stage_index=stage_index,
            total=total,
            degraded=degraded,
            progress_sink=progress_sink,
            observer=observer,
        )

    results: dict[str, StageResult] = {}
    errors: dict[str, StageExecutionError] = {}
    stage_by_name = {stage.name: (stage, stage_index) for stage, _resolved, stage_index in resolved_stages}

    with ThreadPoolExecutor(max_workers=len(resolved_stages)) as executor:
        future_to_stage = {
            executor.submit(runner, resolved_stage, job_paths, progress_sink): stage
            for stage, resolved_stage, _stage_index in resolved_stages
        }
        for future in as_completed(future_to_stage):
            stage = future_to_stage[future]
            try:
                results[stage.name] = future.result()
            except StageExecutionError as exc:
                errors[stage.name] = exc

    completed_stages: list[str] = []
    dcd_failed = "collecting_dcd" in errors
    autohome_succeeded = "collecting_autohome" in results
    can_single_platform_fallback = context.allow_single_platform_fallback and autohome_succeeded and dcd_failed and len(errors) == 1

    if not errors or can_single_platform_fallback:
        for stage, _resolved_stage, stage_index in resolved_stages:
            if stage.name in results:
                _stage_success(
                    context=context,
                    stage=stage,
                    stage_index=stage_index,
                    total=total,
                    degraded=degraded,
                    result=results[stage.name],
                    completed_stages=completed_stages,
                    progress_sink=progress_sink,
                    observer=observer,
                )

        if can_single_platform_fallback:
            dcd_stage, dcd_index = stage_by_name["collecting_dcd"]
            exc = errors["collecting_dcd"]
            _stage_degraded(
                context=context,
                stage=dcd_stage,
                stage_index=dcd_index,
                total=total,
                message=f"single-platform fallback after {exc.stage}",
                error_code=exc.error_code,
                error_message=exc.message,
                progress_sink=progress_sink,
                observer=observer,
            )
            return CollectorGroupResult(
                completed_stages=completed_stages,
                degraded=True,
                single_platform_mode=True,
            )

        return CollectorGroupResult(
            completed_stages=completed_stages,
            degraded=degraded,
            single_platform_mode=False,
        )

    for stage, _resolved_stage, stage_index in resolved_stages:
        if stage.name in results:
            _stage_success(
                context=context,
                stage=stage,
                stage_index=stage_index,
                total=total,
                degraded=degraded,
                result=results[stage.name],
                completed_stages=completed_stages,
                progress_sink=progress_sink,
                observer=observer,
            )

    failed_name = next(stage.name for stage, _resolved, _stage_index in resolved_stages if stage.name in errors)
    failed_stage, failed_index = stage_by_name[failed_name]
    failed_result = _stage_failed(
        context=context,
        stage=failed_stage,
        stage_index=failed_index,
        total=total,
        exc=errors[failed_name],
        degraded=degraded,
        progress_sink=progress_sink,
        observer=observer,
    )
    failed_result.completed_stages = completed_stages
    return CollectorGroupResult(completed_stages=completed_stages, degraded=degraded, failed_result=failed_result)


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
    index = 0
    while index < len(stage_commands):
        if _looks_like_parallel_collector_group(stage_commands, index, single_platform_mode=single_platform_mode):
            group_result = _run_parallel_collectors(
                context=context,
                stage_commands=stage_commands,
                start_index=index,
                total=total,
                runner=runner,
                job_paths=job_paths,
                progress_sink=progress_sink,
                observer=observer,
                degraded=degraded,
            )
            completed_stages.extend(group_result.completed_stages)
            degraded = group_result.degraded
            single_platform_mode = group_result.single_platform_mode
            if group_result.failed_result is not None:
                _emit(
                    observer,
                    {
                        "type": "pipeline_completed",
                        "job_id": context.job_id,
                        "result": group_result.failed_result,
                    },
                )
                return group_result.failed_result
            index += 2
            continue

        stage = stage_commands[index]
        stage_index = index + 1
        resolved_stage = resolve_stage_command(stage, single_platform_mode=single_platform_mode)
        if resolved_stage is None:
            degraded = True
            _stage_degraded(
                context=context,
                stage=stage,
                stage_index=stage_index,
                total=total,
                message="skipped in single-platform fallback",
                error_code=None,
                error_message=None,
                progress_sink=progress_sink,
                observer=observer,
            )
            index += 1
            continue

        _stage_running(
            context=context,
            stage=stage,
            resolved_stage=resolved_stage,
            stage_index=stage_index,
            total=total,
            degraded=degraded,
            progress_sink=progress_sink,
            observer=observer,
        )
        try:
            stage_result = runner(resolved_stage, job_paths, progress_sink)
            if stage_result.status == "degraded":
                degraded = True
            _stage_success(
                context=context,
                stage=stage,
                stage_index=stage_index,
                total=total,
                degraded=degraded,
                result=stage_result,
                completed_stages=completed_stages,
                progress_sink=progress_sink,
                observer=observer,
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
                _stage_degraded(
                    context=context,
                    stage=stage,
                    stage_index=stage_index,
                    total=total,
                    message=f"single-platform fallback after {exc.stage}",
                    error_code=exc.error_code,
                    error_message=exc.message,
                    progress_sink=progress_sink,
                    observer=observer,
                )
                index += 1
                continue

            if not stage.core:
                degraded = True
                _stage_degraded(
                    context=context,
                    stage=stage,
                    stage_index=stage_index,
                    total=total,
                    message=exc.message,
                    error_code=exc.error_code,
                    error_message=exc.message,
                    progress_sink=progress_sink,
                    observer=observer,
                )
                index += 1
                continue

            pipeline_result = _stage_failed(
                context=context,
                stage=stage,
                stage_index=stage_index,
                total=total,
                exc=exc,
                degraded=degraded,
                progress_sink=progress_sink,
                observer=observer,
            )
            pipeline_result.completed_stages = completed_stages
            _emit(
                observer,
                {
                    "type": "pipeline_completed",
                    "job_id": context.job_id,
                    "result": pipeline_result,
                },
            )
            return pipeline_result
        index += 1

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
