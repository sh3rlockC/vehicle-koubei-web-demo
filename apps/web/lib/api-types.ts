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

export type Wordcloud = {
  positive_image_url: string | null;
  negative_image_url: string | null;
  terms_excel_url: string | null;
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
  sample_summary: SampleSummary;
  template_report: TemplateReport;
  structured_sections: StructuredSections;
  wordcloud: Wordcloud;
  artifacts: ArtifactItem[];
  ai_report: Record<string, unknown> | null;
  ai_available: boolean;
  qa_available: boolean;
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
  follow_up_suggestions: string[];
};

export type QaRequest = {
  question: string;
};
