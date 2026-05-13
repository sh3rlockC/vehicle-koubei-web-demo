from __future__ import annotations

from io import BytesIO
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from redis.exceptions import RedisError
from rq import Queue
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import ComparisonJob, ComparisonVehicle
from app.schemas import (
    ComparisonCreateRequest,
    ComparisonCreateResponse,
    ComparisonOptionsRequest,
    ComparisonOptionsResponse,
    ComparisonProgressResponse,
    ComparisonResultResponse,
    ComparisonVehicleOptionResponse,
)
from app.services.comparisons import (
    comparison_progress_payload,
    comparison_result_payload,
    empty_vehicle_resolve,
    find_reusable_jobs,
    is_reusable_job,
)
from app.services.confirmed_vehicle_series import query_key, upsert_confirmed_vehicle_series
from app.services.job_queue import get_job_queue
from app.services.passphrase import require_passphrase_session
from app.services.vehicle_resolver import VehicleResolver

router = APIRouter(prefix="/api/comparisons", tags=["comparisons"])
QUEUE_UNAVAILABLE_MESSAGE = "任务队列暂不可用，请确认 Redis 和 worker 已启动。"


def _ensure_session(request: Request, settings: Settings) -> None:
    require_passphrase_session(request, settings)


def _resolve_vehicle(db: Session, settings: Settings, query: str) -> dict:
    try:
        return VehicleResolver(settings=settings, db=db).resolve(query)
    except Exception:
        return empty_vehicle_resolve(query)


def _safe_zip_name(path: Path, seen: set[str]) -> str:
    base_name = path.name or "artifact"
    if base_name not in seen:
        seen.add(base_name)
        return base_name
    stem = path.stem or "artifact"
    suffix = path.suffix
    index = 2
    while True:
        candidate = f"{stem}_{index}{suffix}"
        if candidate not in seen:
            seen.add(candidate)
            return candidate
        index += 1


@router.post("/options", response_model=ComparisonOptionsResponse)
def comparison_options(
    payload: ComparisonOptionsRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ComparisonOptionsResponse:
    _ensure_session(request, settings)
    vehicles = []
    for vehicle in payload.vehicles:
        resolve = _resolve_vehicle(db, settings, vehicle.query)
        vehicles.append(
            ComparisonVehicleOptionResponse(
                query=vehicle.query,
                resolve=resolve,
                reuse_options=find_reusable_jobs(db, settings, vehicle.query),
            )
        )
    return ComparisonOptionsResponse(vehicles=vehicles)


@router.post("", response_model=ComparisonCreateResponse)
def create_comparison(
    payload: ComparisonCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    queue: Queue = Depends(get_job_queue),
) -> ComparisonCreateResponse:
    _ensure_session(request, settings)

    normalized_keys = [query_key(vehicle.query) for vehicle in payload.vehicles]
    if len(set(normalized_keys)) != len(normalized_keys):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="comparison vehicles must be distinct")

    comparison = ComparisonJob(
        status="queued",
        current_stage="queued",
        passphrase_version=settings.pass_phrase_version,
        vehicle_count=len(payload.vehicles),
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    db.add(comparison)
    db.flush()

    for position, vehicle in enumerate(payload.vehicles, start=1):
        selected_autohome = vehicle.selected_candidates.autohome
        selected_dongchedi = vehicle.selected_candidates.dongchedi
        if not selected_autohome.series_id or not selected_dongchedi.series_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirmed candidates required for both platforms")
        if vehicle.reuse_job_id and not is_reusable_job(db, settings, vehicle.reuse_job_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"reuse job is not available: {vehicle.reuse_job_id}")

        model_name = vehicle.model_name or vehicle.query
        upsert_confirmed_vehicle_series(
            db,
            query=vehicle.query,
            selected_candidates={
                "autohome": selected_autohome,
                "dongchedi": selected_dongchedi,
            },
        )
        db.add(
            ComparisonVehicle(
                comparison_id=comparison.comparison_id,
                position=position,
                query=vehicle.query,
                model_name=model_name,
                status="reused" if vehicle.reuse_job_id else "queued",
                source_job_id=vehicle.reuse_job_id,
                selected_candidates=vehicle.selected_candidates.model_dump(),
            )
        )

    db.commit()
    db.refresh(comparison)

    try:
        queue_job = queue.enqueue(
            "worker_jobs.run_comparison_job",
            kwargs={
                "comparison_id": comparison.comparison_id,
                "database_url": settings.database_url,
                "artifact_root": settings.artifact_root,
            },
            job_timeout=settings.worker_job_timeout_seconds,
        )
    except RedisError as exc:
        comparison.status = "failed"
        comparison.current_stage = "failed"
        comparison.error_code = "queue_unavailable"
        comparison.error_message = QUEUE_UNAVAILABLE_MESSAGE
        db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=QUEUE_UNAVAILABLE_MESSAGE) from exc

    comparison.queue_job_id = queue_job.id
    comparison.enqueued_at = comparison.created_at
    db.commit()
    db.refresh(comparison)

    return ComparisonCreateResponse(
        comparison_id=comparison.comparison_id,
        status=comparison.status,
        current_stage=comparison.current_stage,
        progress_url=f"/api/comparisons/{comparison.comparison_id}/progress",
        result_url=f"/api/comparisons/{comparison.comparison_id}",
    )


@router.get("/{comparison_id}/progress", response_model=ComparisonProgressResponse)
def get_comparison_progress(
    comparison_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ComparisonProgressResponse:
    _ensure_session(request, settings)
    comparison = db.get(ComparisonJob, comparison_id)
    if comparison is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="comparison not found")
    return comparison_progress_payload(db, settings, comparison)


@router.get("/{comparison_id}", response_model=ComparisonResultResponse)
def get_comparison(
    comparison_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ComparisonResultResponse:
    _ensure_session(request, settings)
    comparison = db.get(ComparisonJob, comparison_id)
    if comparison is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="comparison not found")
    return comparison_result_payload(settings, comparison)


@router.get("/{comparison_id}/artifacts/{artifact_id}")
def download_comparison_artifact(
    comparison_id: str,
    artifact_id: int,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _ensure_session(request, settings)
    comparison = db.get(ComparisonJob, comparison_id)
    if comparison is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="comparison not found")
    artifact = next((item for item in comparison.artifacts if item.id == artifact_id), None)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    path = Path(artifact.artifact_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact file missing")
    return FileResponse(path=path, filename=path.name)


@router.get("/{comparison_id}/artifacts.zip")
def download_comparison_bundle(
    comparison_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _ensure_session(request, settings)
    comparison = db.get(ComparisonJob, comparison_id)
    if comparison is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="comparison not found")

    paths = [Path(artifact.artifact_path) for artifact in sorted(comparison.artifacts, key=lambda item: item.id)]
    paths = [path for path in paths if path.exists()]
    if not paths:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no downloadable comparison artifacts")

    buffer = BytesIO()
    seen_names: set[str] = set()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, arcname=_safe_zip_name(path, seen_names))

    filename = f"{comparison.comparison_id}_竞品对比结果.zip"
    encoded_filename = quote(filename)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=comparison_bundle.zip; filename*=UTF-8''{encoded_filename}"},
    )
