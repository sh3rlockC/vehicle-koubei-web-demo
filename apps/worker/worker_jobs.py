from __future__ import annotations

from worker_app.artifacts import ensure_job_dirs
from worker_app.job_store import DatabaseJobStore
from worker_app.jobs import JobContext, run_pipeline
from worker_app.openclaw_runner import build_stage_runner
from worker_app.stages import build_stage_commands


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
    pipeline_result = run_pipeline(
        context,
        stage_commands,
        build_stage_runner(),
        observer=lambda event: store.handle_pipeline_event(job_id, event),
    )
    return {
        "job_id": job_id,
        "status": pipeline_result.status,
        "degraded": pipeline_result.degraded,
        "completed_stages": pipeline_result.completed_stages,
        "failed_stage": pipeline_result.failed_stage,
        "error_code": pipeline_result.error_code,
        "error_message": pipeline_result.error_message,
    }
