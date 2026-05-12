from __future__ import annotations

import os
from pathlib import Path

from worker_app.artifacts import ensure_job_dirs
from worker_app.hermes_outputs import generate_time_report_outputs
from worker_app.job_store import DatabaseJobStore
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
