from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


APPROVED_JOB_STATUSES = [
    "access_pending",
    "candidate_pending",
    "queued",
    "collecting_autohome",
    "collecting_dcd",
    "postprocessing",
    "summarizing",
    "rendering_wordcloud",
    "generating_ai_report",
    "building_qa_corpus",
    "completed",
    "completed_degraded",
    "failed",
    "cancelled",
    "expired",
]


class AccessVerifyRequest(BaseModel):
    passphrase: str = Field(min_length=1, max_length=256)


class AccessVerifyResponse(BaseModel):
    ok: bool
    passphrase_version: str


class PlatformCandidate(BaseModel):
    series_id: str | None = None
    url: str | None = None
    title: str | None = None
    source: str | None = None
    evidence_url: str | None = None
    kind: str | None = None
    note: str | None = None


class PlatformCandidateGroup(BaseModel):
    best: PlatformCandidate | None = None
    candidates: list[PlatformCandidate] = Field(default_factory=list)


class VehicleResolveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=255)


class VehicleResolveResponse(BaseModel):
    query: str
    autohome: PlatformCandidateGroup
    dongchedi: PlatformCandidateGroup


class SelectedCandidates(BaseModel):
    autohome: PlatformCandidate
    dongchedi: PlatformCandidate


class CreateJobRequest(BaseModel):
    query: str = Field(min_length=1, max_length=255)
    model_name: str | None = Field(default=None, max_length=255)
    selected_candidates: SelectedCandidates


class CreateJobResponse(BaseModel):
    job_id: str
    status: str
    current_stage: str
    result_url: str


class JobOverviewResponse(BaseModel):
    job_id: str
    query: str
    model_name: str
    status: str
    current_stage: str
    degraded: bool
    passphrase_version: str
    queue_job_id: str | None
    created_at: datetime
    enqueued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class StageStatusItem(BaseModel):
    name: str
    status: str
    attempt_no: int = 1
    error_code: str | None = None
    error_message: str | None = None
    progress_percent: int | None = None
    progress_message: str | None = None


class JobProgressResponse(BaseModel):
    job_id: str
    status: str
    current_stage: str
    degraded: bool
    overall_percent: int
    stages: list[StageStatusItem]
    message: str


class ArtifactItem(BaseModel):
    id: int
    type: str
    path: str
    url: str
    source_stage: str | None = None


class TemplateReportResponse(BaseModel):
    title: str
    highlights: list[str] = Field(default_factory=list)


class StructuredSectionsResponse(BaseModel):
    overview: list[dict[str, str]] = Field(default_factory=list)
    compare: list[dict[str, str]] = Field(default_factory=list)
    business: list[dict[str, str]] = Field(default_factory=list)
    opportunities: list[dict[str, str]] = Field(default_factory=list)


class WordcloudResponse(BaseModel):
    positive_image_url: str | None = None
    negative_image_url: str | None = None
    terms_excel_url: str | None = None


class SampleSummaryResponse(BaseModel):
    autohome_count: int
    dcd_count: int


class JobResultResponse(BaseModel):
    job_id: str
    status: str
    degraded: bool
    model_name: str
    sample_summary: SampleSummaryResponse
    template_report: TemplateReportResponse
    structured_sections: StructuredSectionsResponse
    wordcloud: WordcloudResponse
    artifacts: list[ArtifactItem] = Field(default_factory=list)
    ai_report: dict | None = None
    ai_available: bool
    qa_available: bool


class JobQARequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class JobQACitationResponse(BaseModel):
    chunk_id: str
    source_type: str
    text: str
    metadata: dict = Field(default_factory=dict)


class JobQAResponse(BaseModel):
    answer: str
    citations: list[JobQACitationResponse] = Field(default_factory=list)
    confidence: str
    insufficient_evidence: bool
    follow_up_suggestions: list[str] = Field(default_factory=list)
