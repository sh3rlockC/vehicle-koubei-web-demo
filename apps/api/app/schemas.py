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
    "generating_hermes_outputs",
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


class KeywordRankItemResponse(BaseModel):
    term: str
    count: int


class KeywordRankingsResponse(BaseModel):
    positive: list[KeywordRankItemResponse] = Field(default_factory=list)
    negative: list[KeywordRankItemResponse] = Field(default_factory=list)
    combined: list[KeywordRankItemResponse] = Field(default_factory=list)


class WordcloudResponse(BaseModel):
    positive_image_url: str | None = None
    negative_image_url: str | None = None
    terms_excel_url: str | None = None
    keyword_rankings: KeywordRankingsResponse = Field(default_factory=KeywordRankingsResponse)


class SampleSummaryResponse(BaseModel):
    autohome_count: int
    dcd_count: int


class JobResultResponse(BaseModel):
    job_id: str
    status: str
    degraded: bool
    model_name: str
    retention_days: int
    sample_summary: SampleSummaryResponse
    template_report: TemplateReportResponse
    structured_sections: StructuredSectionsResponse
    wordcloud: WordcloudResponse
    artifacts: list[ArtifactItem] = Field(default_factory=list)
    ai_report: dict | None = None
    ai_available: bool
    qa_available: bool


class CommentDailyCountResponse(BaseModel):
    date: str
    count: int


class JobCommentSummaryResponse(BaseModel):
    job_id: str
    total_count: int
    dated_count: int
    undated_count: int
    date_min: str | None = None
    date_max: str | None = None
    daily_counts: list[CommentDailyCountResponse] = Field(default_factory=list)
    platform_counts: dict[str, int] = Field(default_factory=dict)


class JobCommentItemResponse(BaseModel):
    comment_id: str
    platform: str
    date: str
    model_name: str
    positive_text: str
    negative_text: str
    full_text: str


class JobCommentPageResponse(BaseModel):
    job_id: str
    start_date: str
    end_date: str
    total: int
    page: int
    page_size: int
    items: list[JobCommentItemResponse] = Field(default_factory=list)


class CreateTimeReportRequest(BaseModel):
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class TimeReportDateRangeResponse(BaseModel):
    start_date: str
    end_date: str


class TimeReportArtifactResponse(BaseModel):
    name: str
    path: str
    type: str


class TimeReportResponse(BaseModel):
    report_id: str
    job_id: str
    model_name: str
    date_range: TimeReportDateRangeResponse
    status: str
    sample_count: int
    platform_counts: dict[str, int] = Field(default_factory=dict)
    source: str | None = None
    report_json: dict | None = None
    artifacts: list[TimeReportArtifactResponse] = Field(default_factory=list)
    zip_url: str
    error_code: str | None = None
    error_message: str | None = None
    queue_job_id: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class TimeReportListResponse(BaseModel):
    items: list[TimeReportResponse] = Field(default_factory=list)


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
    answer_source: str = "fallback"
    model_used: str | None = None
    llm_error: str | None = None
    follow_up_suggestions: list[str] = Field(default_factory=list)
