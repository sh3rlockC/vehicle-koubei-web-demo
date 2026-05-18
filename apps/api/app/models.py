from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_job_id() -> str:
    return f"job_{utc_now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"


def new_time_report_id() -> str:
    return f"time_report_{utc_now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"


def new_comparison_id() -> str:
    return f"cmp_{utc_now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_job_id)
    query: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    current_stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    passphrase_version: Mapped[str] = mapped_column(String(64), nullable=False)
    queue_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collection_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="incremental")
    collection_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    candidates: Mapped[list["JobCandidate"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    stage_runs: Mapped[list["JobStageRun"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    artifacts: Mapped[list["JobArtifact"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    ai_reports: Mapped[list["JobAIReport"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    qa_chunks: Mapped[list["JobQAChunk"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    time_reports: Mapped[list["JobTimeReport"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class KoubeiRawComment(Base):
    __tablename__ = "koubei_raw_comments"
    __table_args__ = (
        UniqueConstraint("query_key", "platform", "series_id", "dedupe_key", name="uq_koubei_raw_comment_dedupe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_key: Mapped[str] = mapped_column(String(255), nullable=False)
    query: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    series_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    row_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    first_seen_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    published_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)


class JobCandidate(Base):
    __tablename__ = "job_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    series_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    job: Mapped[Job] = relationship(back_populates="candidates")


class ConfirmedVehicleSeries(Base):
    __tablename__ = "confirmed_vehicle_series"
    __table_args__ = (UniqueConstraint("query_key", "platform", name="uq_confirmed_vehicle_series_query_platform"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_key: Mapped[str] = mapped_column(String(255), nullable=False)
    query: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    series_id: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class JobStageRun(Base):
    __tablename__ = "job_stage_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    stage_name: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[Job] = relationship(back_populates="stage_runs")


class JobArtifact(Base):
    __tablename__ = "job_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    job: Mapped[Job] = relationship(back_populates="artifacts")


class JobAIReport(Base):
    __tablename__ = "job_ai_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    report_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    job: Mapped[Job] = relationship(back_populates="ai_reports")


class JobQAChunk(Base):
    __tablename__ = "job_qa_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    job: Mapped[Job] = relationship(back_populates="qa_chunks")


class JobTimeReport(Base):
    __tablename__ = "job_time_reports"

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_time_report_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    platform_counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact_paths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queue_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[Job] = relationship(back_populates="time_reports")


class VehicleResolveCache(Base):
    __tablename__ = "vehicle_resolve_cache"

    query_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    query: Mapped[str] = mapped_column(String(255), nullable=False)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ComparisonJob(Base):
    __tablename__ = "comparison_jobs"

    comparison_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_comparison_id)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    current_stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    vehicle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passphrase_version: Mapped[str] = mapped_column(String(64), nullable=False)
    queue_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vehicles: Mapped[list["ComparisonVehicle"]] = relationship(back_populates="comparison", cascade="all, delete-orphan")
    artifacts: Mapped[list["ComparisonArtifact"]] = relationship(back_populates="comparison", cascade="all, delete-orphan")


class ComparisonVehicle(Base):
    __tablename__ = "comparison_vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comparison_id: Mapped[str] = mapped_column(ForeignKey("comparison_jobs.comparison_id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    query: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    source_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    child_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_candidates: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    comparison: Mapped[ComparisonJob] = relationship(back_populates="vehicles")


class ComparisonArtifact(Base):
    __tablename__ = "comparison_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comparison_id: Mapped[str] = mapped_column(ForeignKey("comparison_jobs.comparison_id", ondelete="CASCADE"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    comparison: Mapped[ComparisonJob] = relationship(back_populates="artifacts")
