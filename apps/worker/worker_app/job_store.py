from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON as SAJSON
from sqlalchemy import bindparam, create_engine, text


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def _as_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _engine_kwargs(database_url: str) -> dict[str, Any]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


def _db_bool(value: Any) -> bool:
    return bool(value)


@dataclass(frozen=True)
class WorkerJobInputs:
    job_id: str
    model_name: str
    autohome_series_id: str
    dongchedi_series_id: str


@dataclass(frozen=True)
class TimeReportInputs:
    report_id: str
    job_id: str
    model_name: str
    start_date: str
    end_date: str


class DatabaseJobStore:
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, future=True, **_engine_kwargs(database_url))

    def fetch_job_inputs(self, job_id: str) -> WorkerJobInputs:
        query = text(
            """
            SELECT j.job_id, j.model_name, c.platform, c.series_id
            FROM jobs j
            JOIN job_candidates c ON c.job_id = j.job_id
            WHERE j.job_id = :job_id AND c.selected = :selected
            """
        )
        with self.engine.begin() as conn:
            rows = conn.execute(query, {"job_id": job_id, "selected": True}).mappings().all()
        if not rows:
            raise RuntimeError(f"job not found: {job_id}")

        series_by_platform = {row["platform"]: row["series_id"] for row in rows}
        if not series_by_platform.get("autohome") or not series_by_platform.get("dongchedi"):
            raise RuntimeError(f"job missing selected candidates: {job_id}")

        return WorkerJobInputs(
            job_id=job_id,
            model_name=rows[0]["model_name"],
            autohome_series_id=str(series_by_platform["autohome"]),
            dongchedi_series_id=str(series_by_platform["dongchedi"]),
        )

    def fetch_time_report_inputs(self, report_id: str) -> TimeReportInputs:
        query = text(
            """
            SELECT report_id, job_id, model_name, start_date, end_date
            FROM job_time_reports
            WHERE report_id = :report_id
            """
        )
        with self.engine.begin() as conn:
            row = conn.execute(query, {"report_id": report_id}).mappings().first()
        if row is None:
            raise RuntimeError(f"time report not found: {report_id}")
        return TimeReportInputs(
            report_id=str(row["report_id"]),
            job_id=str(row["job_id"]),
            model_name=str(row["model_name"]),
            start_date=str(row["start_date"]),
            end_date=str(row["end_date"]),
        )

    def mark_time_report_running(self, report_id: str) -> None:
        now = utc_now_iso()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE job_time_reports
                    SET status = 'running',
                        error_code = NULL,
                        error_message = NULL,
                        updated_at = :updated_at
                    WHERE report_id = :report_id
                    """
                ),
                {"report_id": report_id, "updated_at": now},
            )

    def mark_time_report_completed(self, report_id: str, result: dict[str, Any]) -> None:
        now = utc_now_iso()
        statement = text(
            """
            UPDATE job_time_reports
            SET status = 'completed',
                sample_count = :sample_count,
                platform_counts = :platform_counts,
                report_json = :report_json,
                artifact_paths = :artifact_paths,
                source = :source,
                error_code = NULL,
                error_message = NULL,
                updated_at = :updated_at,
                completed_at = :completed_at
            WHERE report_id = :report_id
            """
        ).bindparams(
            bindparam("platform_counts", type_=SAJSON),
            bindparam("report_json", type_=SAJSON),
            bindparam("artifact_paths", type_=SAJSON),
        )
        with self.engine.begin() as conn:
            conn.execute(
                statement,
                {
                    "report_id": report_id,
                    "sample_count": int(result.get("sample_count") or 0),
                    "platform_counts": result.get("platform_counts") or {},
                    "report_json": result.get("report_json") or {},
                    "artifact_paths": result.get("artifact_paths") or [],
                    "source": result.get("source") or "hermes",
                    "updated_at": now,
                    "completed_at": now,
                },
            )

    def mark_time_report_failed(self, report_id: str, *, error_code: str, error_message: str) -> None:
        now = utc_now_iso()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE job_time_reports
                    SET status = 'failed',
                        error_code = :error_code,
                        error_message = :error_message,
                        updated_at = :updated_at,
                        completed_at = :completed_at
                    WHERE report_id = :report_id
                    """
                ),
                {
                    "report_id": report_id,
                    "error_code": error_code,
                    "error_message": error_message,
                    "updated_at": now,
                    "completed_at": now,
                },
            )

    def mark_job_enqueued(self, *, job_id: str, queue_job_id: str | None) -> None:
        now = utc_now_iso()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE jobs
                    SET status = 'queued',
                        current_stage = 'queued',
                        started_at = NULL,
                        finished_at = NULL,
                        degraded = :degraded,
                        queue_job_id = :queue_job_id,
                        enqueued_at = :enqueued_at
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id, "degraded": _db_bool(False), "queue_job_id": queue_job_id, "enqueued_at": now},
            )

    def handle_pipeline_event(self, job_id: str, event: dict[str, Any]) -> None:
        event_type = event["type"]
        if event_type == "stage_running":
            self._stage_started(job_id=job_id, stage_name=event["stage"])
            return
        if event_type in {"stage_success", "stage_degraded", "stage_failed"}:
            self._stage_finished(job_id=job_id, event=event)
            return
        if event_type == "pipeline_completed":
            self._pipeline_completed(job_id=job_id, event=event)

    def mark_job_failed(self, job_id: str, *, error_code: str, error_message: str) -> None:
        now = utc_now()
        now_iso = now.isoformat()
        with self.engine.begin() as conn:
            job_row = conn.execute(
                text(
                    """
                    SELECT current_stage
                    FROM jobs
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id},
            ).mappings().first()
            current_stage = str(job_row["current_stage"]) if job_row and job_row["current_stage"] else None

            stage_row = conn.execute(
                text(
                    """
                    SELECT id, started_at
                    FROM job_stage_runs
                    WHERE job_id = :job_id AND status = 'running'
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"job_id": job_id},
            ).mappings().first()
            if stage_row is None and current_stage and current_stage not in {"completed", "failed", "completed_degraded"}:
                stage_row = conn.execute(
                    text(
                        """
                        SELECT id, started_at
                        FROM job_stage_runs
                        WHERE job_id = :job_id AND stage_name = :stage_name
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ),
                    {"job_id": job_id, "stage_name": current_stage},
                ).mappings().first()

            if stage_row is not None:
                started_at = _as_datetime(stage_row["started_at"]) or now
                duration_ms = int(max((now - started_at).total_seconds() * 1000, 0))
                conn.execute(
                    text(
                        """
                        UPDATE job_stage_runs
                        SET status = 'failed',
                            ended_at = :ended_at,
                            duration_ms = :duration_ms,
                            error_code = :error_code,
                            error_message = :error_message
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": stage_row["id"],
                        "ended_at": now_iso,
                        "duration_ms": duration_ms,
                        "error_code": error_code,
                        "error_message": error_message,
                    },
                )

            conn.execute(
                text(
                    """
                    UPDATE jobs
                    SET status = 'failed',
                        current_stage = 'failed',
                        finished_at = :finished_at
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id, "finished_at": now_iso},
            )

    def _next_attempt_no(self, conn, job_id: str, stage_name: str) -> int:
        current = conn.execute(
            text(
                """
                SELECT COALESCE(MAX(attempt_no), 0)
                FROM job_stage_runs
                WHERE job_id = :job_id AND stage_name = :stage_name
                """
            ),
            {"job_id": job_id, "stage_name": stage_name},
        ).scalar_one()
        return int(current) + 1

    def _stage_started(self, *, job_id: str, stage_name: str) -> None:
        now = utc_now_iso()
        with self.engine.begin() as conn:
            attempt_no = self._next_attempt_no(conn, job_id, stage_name)
            conn.execute(
                text(
                    """
                    INSERT INTO job_stage_runs (
                        job_id, stage_name, attempt_no, status, started_at, ended_at, duration_ms, error_code, error_message
                    ) VALUES (
                        :job_id, :stage_name, :attempt_no, 'running', :started_at, NULL, NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "job_id": job_id,
                    "stage_name": stage_name,
                    "attempt_no": attempt_no,
                    "started_at": now,
                },
            )
            conn.execute(
                text(
                    """
                    UPDATE jobs
                    SET status = :status,
                        current_stage = :current_stage,
                        started_at = COALESCE(started_at, :started_at)
                    WHERE job_id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "status": stage_name,
                    "current_stage": stage_name,
                    "started_at": now,
                },
            )

    def _stage_finished(self, *, job_id: str, event: dict[str, Any]) -> None:
        stage_name = event["stage"]
        snapshot = event.get("snapshot") or {}
        now = utc_now()
        now_iso = now.isoformat()
        status = snapshot.get("status", "success")
        error_code = event.get("error_code")
        error_message = event.get("error_message")
        result = event.get("result")

        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, started_at
                    FROM job_stage_runs
                    WHERE job_id = :job_id AND stage_name = :stage_name
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"job_id": job_id, "stage_name": stage_name},
            ).mappings().first()

            if row is None or row["started_at"] is None or status == "degraded" and event.get("message") == "skipped in single-platform fallback":
                attempt_no = self._next_attempt_no(conn, job_id, stage_name)
                conn.execute(
                    text(
                        """
                        INSERT INTO job_stage_runs (
                            job_id, stage_name, attempt_no, status, started_at, ended_at, duration_ms, error_code, error_message
                        ) VALUES (
                            :job_id, :stage_name, :attempt_no, :status, :started_at, :ended_at, 0, :error_code, :error_message
                        )
                        """
                    ),
                    {
                        "job_id": job_id,
                        "stage_name": stage_name,
                        "attempt_no": attempt_no,
                        "status": status,
                        "started_at": now_iso,
                        "ended_at": now_iso,
                        "error_code": error_code,
                        "error_message": error_message,
                    },
                )
            else:
                started_at = _as_datetime(row["started_at"]) or now
                duration_ms = int(max((now - started_at).total_seconds() * 1000, 0))
                conn.execute(
                    text(
                        """
                        UPDATE job_stage_runs
                        SET status = :status,
                            ended_at = :ended_at,
                            duration_ms = :duration_ms,
                            error_code = :error_code,
                            error_message = :error_message
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": row["id"],
                        "status": status,
                        "ended_at": now_iso,
                        "duration_ms": duration_ms,
                        "error_code": error_code,
                        "error_message": error_message,
                    },
                )

            conn.execute(
                text(
                    """
                    UPDATE jobs
                    SET current_stage = :current_stage,
                        degraded = :degraded
                    WHERE job_id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "current_stage": stage_name,
                    "degraded": _db_bool(snapshot.get("degraded")),
                },
            )

            if status in {"success", "degraded"} and result is not None:
                conn.execute(
                    text("DELETE FROM job_artifacts WHERE job_id = :job_id AND source_stage = :source_stage"),
                    {"job_id": job_id, "source_stage": stage_name},
                )
                for artifact_path in result.artifact_paths:
                    conn.execute(
                        text(
                            """
                            INSERT INTO job_artifacts (job_id, artifact_type, artifact_path, artifact_url, source_stage, created_at)
                            VALUES (:job_id, :artifact_type, :artifact_path, NULL, :source_stage, :created_at)
                            """
                        ),
                        {
                            "job_id": job_id,
                            "artifact_type": self._infer_artifact_type(artifact_path),
                            "artifact_path": artifact_path,
                            "source_stage": stage_name,
                            "created_at": now_iso,
                        },
                    )

    def _pipeline_completed(self, *, job_id: str, event: dict[str, Any]) -> None:
        result = event["result"]
        now = utc_now_iso()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE jobs
                    SET status = :status,
                        current_stage = :current_stage,
                        degraded = :degraded,
                        finished_at = :finished_at
                    WHERE job_id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "status": result.status,
                    "current_stage": result.status,
                    "degraded": _db_bool(result.degraded),
                    "finished_at": now,
                },
            )

    def _infer_artifact_type(self, artifact_path: str) -> str:
        path = artifact_path.lower()
        if path.endswith(".validation.json"):
            return "validation_json"
        if path.endswith(".progress.json"):
            return "progress_json"
        if path.endswith(".failed-pages.json"):
            return "failed_pages_json"
        if path.endswith(".png"):
            return "image_png"
        if path.endswith(".xlsx"):
            return "excel"
        if path.endswith(".json"):
            return "json"
        return "file"
