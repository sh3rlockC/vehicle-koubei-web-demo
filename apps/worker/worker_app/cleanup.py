from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import multiprocessing
import os
from pathlib import Path
import shutil
import threading
from typing import Mapping

from sqlalchemy import bindparam, create_engine, inspect, text

from worker_app.job_store import _engine_kwargs

TERMINAL_CLEANUP_STATUSES = ("completed", "completed_degraded", "failed", "cancelled")


@dataclass(frozen=True)
class CleanupSettings:
    retention_days: int
    interval_seconds: int


@dataclass(frozen=True)
class CleanupResult:
    expired_job_ids: list[str]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _as_utc_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def cleanup_settings_from_env(env: Mapping[str, str] | None = None) -> CleanupSettings:
    if env is None:
        env = os.environ
    return CleanupSettings(
        retention_days=_positive_int(env.get("JOB_ARTIFACT_RETENTION_DAYS"), 3),
        interval_seconds=_positive_int(env.get("JOB_ARTIFACT_CLEANUP_INTERVAL_SECONDS"), 12 * 60 * 60),
    )


def _safe_job_dir(artifact_root: str | Path, job_id: str) -> Path | None:
    root = Path(artifact_root).expanduser().resolve()
    job_dir = (root / job_id).resolve()
    if job_dir == root or root not in job_dir.parents:
        return None
    return job_dir


def _remove_job_dir(artifact_root: str | Path, job_id: str) -> None:
    job_dir = _safe_job_dir(artifact_root, job_id)
    if job_dir is not None and job_dir.exists():
        try:
            shutil.rmtree(job_dir)
        except FileNotFoundError:
            pass


def cleanup_expired_job_data(
    *,
    database_url: str,
    artifact_root: str | Path,
    retention_days: int,
    now: datetime | None = None,
) -> CleanupResult:
    now = now or utc_now()
    cutoff = now - timedelta(days=retention_days)
    engine = create_engine(database_url, future=True, **_engine_kwargs(database_url))

    try:
        with engine.begin() as conn:
            existing_table_names = set(inspect(conn).get_table_names())
            if "jobs" not in existing_table_names:
                return CleanupResult(expired_job_ids=[])

            rows = conn.execute(
                text(
                    """
                    SELECT job_id, created_at, finished_at
                    FROM jobs
                    WHERE status IN :statuses
                    ORDER BY COALESCE(finished_at, created_at), job_id
                    """
                ).bindparams(bindparam("statuses", expanding=True)),
                {"statuses": TERMINAL_CLEANUP_STATUSES},
            ).mappings().all()

            expired_job_ids = []
            for row in rows:
                finished_or_created = _as_utc_datetime(row["finished_at"]) or _as_utc_datetime(row["created_at"])
                if finished_or_created is not None and finished_or_created <= cutoff:
                    expired_job_ids.append(str(row["job_id"]))

            for job_id in expired_job_ids:
                _remove_job_dir(artifact_root, job_id)
                for table_name in ("job_artifacts", "job_ai_reports", "job_qa_chunks", "job_time_reports"):
                    if table_name not in existing_table_names:
                        continue
                    conn.execute(text(f"DELETE FROM {table_name} WHERE job_id = :job_id"), {"job_id": job_id})
                conn.execute(
                    text(
                        """
                        UPDATE jobs
                        SET status = 'expired',
                            current_stage = 'expired'
                        WHERE job_id = :job_id
                        """
                    ),
                    {"job_id": job_id},
                )
    finally:
        engine.dispose()

    return CleanupResult(expired_job_ids=expired_job_ids)


def run_cleanup_loop(
    *,
    database_url: str,
    artifact_root: str | Path,
    settings: CleanupSettings,
    stop_event: threading.Event | None = None,
) -> None:
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        try:
            result = cleanup_expired_job_data(
                database_url=database_url,
                artifact_root=artifact_root,
                retention_days=settings.retention_days,
            )
            if result.expired_job_ids:
                print(f"cleanup expired jobs: {', '.join(result.expired_job_ids)}", flush=True)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            print(f"cleanup failed: {exc}", flush=True)
        stop_event.wait(settings.interval_seconds)


def start_cleanup_process(*, database_url: str, artifact_root: str | Path, settings: CleanupSettings) -> multiprocessing.Process:
    process = multiprocessing.Process(
        target=run_cleanup_loop,
        kwargs={
            "database_url": database_url,
            "artifact_root": artifact_root,
            "settings": settings,
        },
        name="job-artifact-cleanup",
        daemon=True,
    )
    process.start()
    return process
