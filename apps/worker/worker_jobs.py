from __future__ import annotations

import os
from pathlib import Path
import shutil

from worker_app.artifacts import ensure_job_dirs
from worker_app.comparison_outputs import VehicleSnapshot, generate_comparison_outputs
from worker_app.hermes_outputs import generate_time_report_outputs
from worker_app.job_store import ComparisonVehicleInputs, DatabaseJobStore
from worker_app.jobs import JobContext, run_pipeline
from worker_app.openclaw_runner import build_stage_runner
from worker_app.stages import build_stage_commands


def _optional_existing_path(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return str(path) if path.exists() else None


def _error_code_from_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return message.split(":", 1)[0]


def _safe_filename_part(value: str) -> str:
    cleaned = "".join(char if char not in {'/', '\\', ':', '*', '?', '"', '<', '>', '|'} else "_" for char in value.strip())
    return cleaned or "vehicle"


def _copy_snapshot_artifacts(
    *,
    vehicle: ComparisonVehicleInputs,
    source_job_id: str,
    source_artifacts: dict[str, str],
    output_dir: Path,
) -> tuple[VehicleSnapshot, list[str]]:
    final_report = Path(source_artifacts["final_report.json"])
    analysis_facts = Path(source_artifacts["analysis_facts.jsonl"])
    llm_metrics_value = source_artifacts.get("llm_metrics.json")
    if not final_report.exists() or not analysis_facts.exists():
        raise RuntimeError(f"source job missing comparison JSON artifacts: {source_job_id}")

    prefix = _safe_filename_part(vehicle.model_name)
    final_target = output_dir / f"{prefix}.final_report.json"
    facts_target = output_dir / f"{prefix}.analysis_facts.jsonl"
    shutil.copy2(final_report, final_target)
    shutil.copy2(analysis_facts, facts_target)

    copied = [str(final_target), str(facts_target)]
    metrics_target = None
    if llm_metrics_value:
        metrics_source = Path(llm_metrics_value)
        if metrics_source.exists():
            metrics_target = output_dir / f"{prefix}.llm_metrics.json"
            shutil.copy2(metrics_source, metrics_target)
            copied.append(str(metrics_target))

    return (
        VehicleSnapshot(
            model_name=vehicle.model_name,
            source_job_id=source_job_id,
            final_report_path=final_target,
            analysis_facts_path=facts_target,
            llm_metrics_path=metrics_target,
        ),
        copied,
    )


def _unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _copy_vehicle_downloadable_artifacts(
    *,
    vehicle: ComparisonVehicleInputs,
    source_paths: list[str],
    output_dir: Path,
) -> list[str]:
    vehicle_dir = output_dir / _safe_filename_part(vehicle.model_name)
    vehicle_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for source_value in source_paths:
        source = Path(source_value)
        if not source.exists() or not source.name.lower().endswith((".xlsx", ".png")):
            continue
        target = _unique_target(vehicle_dir / source.name)
        shutil.copy2(source, target)
        copied.append(str(target))
    return copied


def run_job(
    *,
    job_id: str,
    database_url: str,
    artifact_root: str,
) -> dict:
    store = DatabaseJobStore(database_url)
    job_inputs = store.fetch_job_inputs(job_id)
    context = JobContext(
        job_id=job_id,
        model_name=job_inputs.model_name,
        artifact_root=artifact_root,
    )
    job_paths = ensure_job_dirs(artifact_root, job_id)
    stage_commands = build_stage_commands(
        job_paths=job_paths,
        model_name=job_inputs.model_name,
        autohome_series_id=job_inputs.autohome_series_id,
        dongchedi_series_id=job_inputs.dongchedi_series_id,
    )
    try:
        pipeline_result = run_pipeline(
            context,
            stage_commands,
            build_stage_runner(),
            observer=lambda event: store.handle_pipeline_event(job_id, event),
        )
    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        error_code = _error_code_from_exception(exc)
        store.mark_job_failed(job_id, error_code=error_code, error_message=error_message)
        return {
            "job_id": job_id,
            "status": "failed",
            "degraded": False,
            "completed_stages": [],
            "failed_stage": None,
            "error_code": error_code,
            "error_message": error_message,
        }
    return {
        "job_id": job_id,
        "status": pipeline_result.status,
        "degraded": pipeline_result.degraded,
        "completed_stages": pipeline_result.completed_stages,
        "failed_stage": pipeline_result.failed_stage,
        "error_code": pipeline_result.error_code,
        "error_message": pipeline_result.error_message,
    }


def run_time_report(
    *,
    report_id: str,
    database_url: str,
    artifact_root: str,
) -> dict:
    store = DatabaseJobStore(database_url)
    report_inputs = store.fetch_time_report_inputs(report_id)
    store.mark_time_report_running(report_id)

    job_paths = ensure_job_dirs(artifact_root, report_inputs.job_id)
    autohome_input = job_paths.outputs.raw / f"ZJ{report_inputs.model_name}原始口碑.xlsx"
    dcd_input = job_paths.outputs.raw / f"DCD口碑_{report_inputs.model_name}.xlsx"
    output_dir = job_paths.root / "outputs" / "time_reports" / report_inputs.report_id
    progress_file = job_paths.progress / f"{report_inputs.report_id}.progress.json"

    try:
        result = generate_time_report_outputs(
            autohome_input=autohome_input,
            dcd_input=dcd_input,
            output_dir=output_dir,
            model_name=report_inputs.model_name,
            start_date=report_inputs.start_date,
            end_date=report_inputs.end_date,
            hermes_command=os.getenv("HERMES_COMMAND", "hermes"),
            font_path=_optional_existing_path(os.getenv("WORDCLOUD_FONT_PATH")),
            env=dict(os.environ),
            progress_file=progress_file,
        )
    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        error_code = _error_code_from_exception(exc)
        store.mark_time_report_failed(report_id, error_code=error_code, error_message=error_message)
        return {
            "report_id": report_id,
            "status": "failed",
            "error_code": error_code,
            "error_message": error_message,
        }

    store.mark_time_report_completed(report_id, result)
    return {
        "report_id": report_id,
        "status": result.get("status", "completed"),
        "sample_count": result.get("sample_count", 0),
        "source": result.get("source", "hermes"),
    }


def run_comparison_job(
    *,
    comparison_id: str,
    database_url: str,
    artifact_root: str,
) -> dict:
    store = DatabaseJobStore(database_url)
    comparison_inputs = store.fetch_comparison_inputs(comparison_id)
    comparison_dir = Path(artifact_root).expanduser().resolve() / comparison_id / "comparisons"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    store.mark_comparison_running(comparison_id)

    snapshots: list[VehicleSnapshot] = []
    artifact_paths: list[str] = []
    excluded: list[dict[str, str]] = []

    for vehicle in comparison_inputs.vehicles:
        try:
            source_job_id = vehicle.source_job_id
            if source_job_id:
                store.mark_comparison_vehicle_status(vehicle.id, status="reused", source_job_id=source_job_id)
            else:
                child_job_id = store.ensure_comparison_child_job(vehicle, passphrase_version=comparison_inputs.passphrase_version)
                store.mark_comparison_vehicle_status(vehicle.id, status="running", child_job_id=child_job_id)
                child_result = run_job(job_id=child_job_id, database_url=database_url, artifact_root=artifact_root)
                if child_result.get("status") not in {"completed", "completed_degraded"}:
                    message = str(child_result.get("error_message") or "vehicle collection failed")
                    store.mark_comparison_vehicle_status(
                        vehicle.id,
                        status="excluded",
                        child_job_id=child_job_id,
                        error_code=str(child_result.get("error_code") or "collection_failed"),
                        error_message=message,
                    )
                    excluded.append({"model_name": vehicle.model_name, "reason": message})
                    continue
                source_job_id = child_job_id
                store.mark_comparison_vehicle_status(vehicle.id, status="completed", child_job_id=child_job_id)

            source_artifacts = store.comparison_source_artifacts(source_job_id)
            if "final_report.json" not in source_artifacts or "analysis_facts.jsonl" not in source_artifacts:
                raise RuntimeError(f"source job missing comparison JSON artifacts: {source_job_id}")
            snapshot, copied_paths = _copy_snapshot_artifacts(
                vehicle=vehicle,
                source_job_id=source_job_id,
                source_artifacts=source_artifacts,
                output_dir=comparison_dir,
            )
            snapshots.append(snapshot)
            artifact_paths.extend(copied_paths)
            artifact_paths.extend(
                _copy_vehicle_downloadable_artifacts(
                    vehicle=vehicle,
                    source_paths=store.comparison_downloadable_artifacts(source_job_id),
                    output_dir=comparison_dir,
                )
            )
        except Exception as exc:
            error_message = str(exc) or exc.__class__.__name__
            store.mark_comparison_vehicle_status(
                vehicle.id,
                status="excluded",
                error_code=_error_code_from_exception(exc),
                error_message=error_message,
            )
            excluded.append({"model_name": vehicle.model_name, "reason": error_message})

    if len(snapshots) < 2:
        message = "竞品对比至少需要 2 个可用车型结果"
        store.mark_comparison_failed(comparison_id, error_code="insufficient_available_vehicles", error_message=message)
        return {
            "comparison_id": comparison_id,
            "status": "failed",
            "error_code": "insufficient_available_vehicles",
            "error_message": message,
            "available_vehicle_count": len(snapshots),
            "excluded": excluded,
        }

    store.mark_comparison_comparing(comparison_id)
    result = generate_comparison_outputs(
        snapshots=snapshots,
        output_dir=comparison_dir,
        start_date=comparison_inputs.start_date,
        end_date=comparison_inputs.end_date,
        env=dict(os.environ),
    )
    artifact_paths.extend(result["artifact_paths"])
    degraded = bool(excluded) or bool(result.get("degraded"))
    report_json = dict(result["report_json"])
    if excluded:
        report_json["excluded_vehicles"] = excluded
    store.mark_comparison_completed(
        comparison_id,
        report_json=report_json,
        artifact_paths=artifact_paths,
        degraded=degraded,
    )
    return {
        "comparison_id": comparison_id,
        "status": "completed_degraded" if degraded else "completed",
        "vehicle_count": len(snapshots),
        "excluded": excluded,
    }
