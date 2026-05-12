export type AccessVerifyResponse = {
  ok: boolean;
  passphrase_version: string;
};

export type PlatformCandidate = {
  series_id: string | null;
  url: string | null;
  title: string | null;
  source: string | null;
  evidence_url?: string | null;
  kind?: string | null;
  note?: string | null;
};

export type PlatformCandidateGroup = {
  best: PlatformCandidate | null;
  candidates: PlatformCandidate[];
};

export type VehicleResolveResponse = {
  query: string;
  autohome: PlatformCandidateGroup;
  dongchedi: PlatformCandidateGroup;
};

export type SelectedCandidates = {
  autohome: PlatformCandidate;
  dongchedi: PlatformCandidate;
};

export type CreateJobResponse = {
  job_id: string;
  status: string;
  current_stage: string;
  result_url: string;
};

export type StageStatusItem = {
  name: string;
  status: string;
  attempt_no: number;
  error_code: string | null;
  error_message: string | null;
  progress_percent: number | null;
  progress_message: string | null;
};

export type JobProgressResponse = {
  job_id: string;
  status: string;
  current_stage: string;
  degraded: boolean;
  overall_percent: number;
  stages: StageStatusItem[];
  message: string;
};

export type SampleSummary = {
  autohome_count: number;
  dcd_count: number;
};

export type TemplateReport = {
  title: string;
  highlights: string[];
};

export type StructuredSections = {
  overview: Array<Record<string, string>>;
  compare: Array<Record<string, string>>;
  business: Array<Record<string, string>>;
  opportunities: Array<Record<string, string>>;
};

export type KeywordRankItem = {
  term: string;
  count: number;
};

export type KeywordRankings = {
  positive: KeywordRankItem[];
  negative: KeywordRankItem[];
  combined: KeywordRankItem[];
};

export type Wordcloud = {
  positive_image_url: string | null;
  negative_image_url: string | null;
  terms_excel_url: string | null;
  keyword_rankings: KeywordRankings;
};

export type ArtifactItem = {
  id: number;
  type: string;
  path: string;
  url: string;
  source_stage: string | null;
};

export type JobResultResponse = {
  job_id: string;
  status: string;
  degraded: boolean;
  model_name: string;
  retention_days: number;
  sample_summary: SampleSummary;
  template_report: TemplateReport;
  structured_sections: StructuredSections;
  wordcloud: Wordcloud;
  artifacts: ArtifactItem[];
  ai_report: Record<string, unknown> | null;
  ai_available: boolean;
  qa_available: boolean;
};

export type CommentDailyCount = {
  date: string;
  count: number;
};

export type JobCommentSummaryResponse = {
  job_id: string;
  total_count: number;
  dated_count: number;
  undated_count: number;
  date_min: string | null;
  date_max: string | null;
  daily_counts: CommentDailyCount[];
  platform_counts: Record<string, number>;
};

export type JobCommentItem = {
  comment_id: string;
  platform: string;
  date: string;
  model_name: string;
  positive_text: string;
  negative_text: string;
  full_text: string;
};

export type JobCommentPageResponse = {
  job_id: string;
  start_date: string;
  end_date: string;
  total: number;
  page: number;
  page_size: number;
  items: JobCommentItem[];
};

export type CreateTimeReportRequest = {
  start_date: string;
  end_date: string;
};

export type TimeReportArtifact = {
  name: string;
  path: string;
  type: string;
};

export type TimeReportResponse = {
  report_id: string;
  job_id: string;
  model_name: string;
  date_range: {
    start_date: string;
    end_date: string;
  };
  status: string;
  sample_count: number;
  platform_counts: Record<string, number>;
  source: string | null;
  report_json: Record<string, unknown> | null;
  artifacts: TimeReportArtifact[];
  zip_url: string;
  error_code: string | null;
  error_message: string | null;
  queue_job_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type TimeReportListResponse = {
  items: TimeReportResponse[];
};

export type QaCitation = {
  chunk_id: string;
  source_type: string;
  text: string;
  metadata: Record<string, unknown>;
};

export type QaResponse = {
  answer: string;
  citations: QaCitation[];
  confidence: string;
  insufficient_evidence: boolean;
  answer_source: string;
  model_used: string | null;
  llm_error: string | null;
  follow_up_suggestions: string[];
};

export type QaRequest = {
  question: string;
};
