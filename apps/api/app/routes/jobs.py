from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from rq import Queue
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Job, JobCandidate, JobStageRun
from app.models import JobArtifact
from app.schemas import (
    CreateJobRequest,
    CreateJobResponse,
    JobQARequest,
    JobQAResponse,
    JobOverviewResponse,
    JobProgressResponse,
    JobResultResponse,
    StageStatusItem,
)
from app.services.job_queue import get_job_queue
from app.services.passphrase import require_passphrase_session
from app.services.qa_service import answer_job_question, find_summary_artifact
from app.services.result_assembler import assemble_job_result

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _ensure_session(request: Request, settings: Settings) -> None:
    require_passphrase_session(request, settings)


def _clamp_percent(value: object) -> int | None:
    try:
        percent = int(float(value))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, percent))


def _read_stage_progress(settings: Settings, job_id: str, stage_name: str, stage_status: str) -> tuple[int | None, str | None]:
    if stage_name not in {"collecting_autohome", "collecting_dcd"}:
        return None, None

    progress_path = settings.artifact_root_path / job_id / "progress" / f"{stage_name}.progress.json"
    payload: dict = {}
    if progress_path.exists():
        try:
            payload = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}

    percent = _clamp_percent(payload.get("percent"))
    if percent is None and isinstance(payload.get("overall"), dict):
        percent = _clamp_percent(payload["overall"].get("percent"))
    if percent is None:
        percent = 100 if stage_status in {"success", "completed"} else 0

    message = payload.get("message")
    return percent, message if isinstance(message, str) and message else None


@router.post("", response_model=CreateJobResponse)
def create_job(
    payload: CreateJobRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    queue: Queue = Depends(get_job_queue),
) -> CreateJobResponse:
    _ensure_session(request, settings)

    model_name = payload.model_name or payload.query
    selected_autohome = payload.selected_candidates.autohome
    selected_dongchedi = payload.selected_candidates.dongchedi
    if not selected_autohome.series_id or not selected_dongchedi.series_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirmed candidates required for both platforms")

    job = Job(
        query=payload.query,
        model_name=model_name,
        status="queued",
        current_stage="queued",
        passphrase_version=settings.pass_phrase_version,
    )
    db.add(job)
    db.flush()

    db.add_all(
        [
            JobCandidate(
                job_id=job.job_id,
                platform="autohome",
                series_id=selected_autohome.series_id,
                url=selected_autohome.url,
                title=selected_autohome.title,
                source=selected_autohome.source,
                selected=True,
            ),
            JobCandidate(
                job_id=job.job_id,
                platform="dongchedi",
                series_id=selected_dongchedi.series_id,
                url=selected_dongchedi.url,
                title=selected_dongchedi.title,
                source=selected_dongchedi.source,
                selected=True,
            ),
        ]
    )

    db.add(
        JobStageRun(
            job_id=job.job_id,
            stage_name="queued",
            attempt_no=1,
            status="queued",
        )
    )
    db.commit()
    db.refresh(job)

    queue_job = queue.enqueue(
        "worker_jobs.run_job",
        kwargs={
            "job_id": job.job_id,
            "database_url": settings.database_url,
            "artifact_root": settings.artifact_root,
        },
        job_timeout=settings.worker_job_timeout_seconds,
    )
    job.queue_job_id = queue_job.id
    job.enqueued_at = job.created_at
    db.commit()
    db.refresh(job)

    return CreateJobResponse(
        job_id=job.job_id,
        status=job.status,
        current_stage=job.current_stage,
        result_url=f"/jobs/{job.job_id}",
    )


@router.get("/{job_id}", response_model=JobOverviewResponse)
def get_job(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobOverviewResponse:
    _ensure_session(request, settings)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return JobOverviewResponse.model_validate(job, from_attributes=True)


@router.get("/{job_id}/progress", response_model=JobProgressResponse)
def get_job_progress(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobProgressResponse:
    _ensure_session(request, settings)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    stage_runs = (
        db.query(JobStageRun)
        .filter(JobStageRun.job_id == job_id)
        .order_by(JobStageRun.id.asc())
        .all()
    )
    stages = []
    for stage in stage_runs:
        progress_percent, progress_message = _read_stage_progress(settings, job_id, stage.stage_name, stage.status)
        stages.append(
            StageStatusItem(
                name=stage.stage_name,
                status=stage.status,
                attempt_no=stage.attempt_no,
                error_code=stage.error_code,
                error_message=stage.error_message,
                progress_percent=progress_percent,
                progress_message=progress_message,
            )
        )

    status_to_percent = {
        "queued": 5,
        "candidate_pending": 10,
        "collecting_autohome": 25,
        "collecting_dcd": 40,
        "postprocessing": 55,
        "summarizing": 70,
        "rendering_wordcloud": 82,
        "generating_ai_report": 92,
        "building_qa_corpus": 96,
        "completed": 100,
        "completed_degraded": 100,
        "failed": 100,
        "cancelled": 100,
        "expired": 100,
    }
    overall_percent = status_to_percent.get(job.current_stage, status_to_percent.get(job.status, 0))
    message = {
        "queued": "任务已创建，等待执行",
        "completed": "任务已完成",
        "completed_degraded": "任务已完成，部分结果降级",
        "failed": "任务执行失败",
    }.get(job.current_stage, f"当前阶段：{job.current_stage}")

    return JobProgressResponse(
        job_id=job.job_id,
        status=job.status,
        current_stage=job.current_stage,
        degraded=job.degraded,
        overall_percent=overall_percent,
        stages=stages,
        message=message,
    )


@router.get("/{job_id}/result", response_model=JobResultResponse)
def get_job_result(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobResultResponse:
    _ensure_session(request, settings)
    payload = assemble_job_result(db, settings, job_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return JobResultResponse.model_validate(payload)


@router.post("/{job_id}/qa", response_model=JobQAResponse)
def answer_job_qa(
    job_id: str,
    payload: JobQARequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobQAResponse:
    _ensure_session(request, settings)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    if find_summary_artifact(db, job_id) is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="qa is not available for this job")

    try:
        result = answer_job_question(db, job_id=job_id, question=payload.question, model_name=job.model_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return JobQAResponse.model_validate(result)


@router.get("/{job_id}/artifacts/{artifact_id}")
def download_artifact(
    job_id: str,
    artifact_id: int,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _ensure_session(request, settings)
    artifact = db.get(JobArtifact, artifact_id)
    if artifact is None or artifact.job_id != job_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    path = Path(artifact.artifact_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact file missing")
    return FileResponse(path=path, filename=path.name)
