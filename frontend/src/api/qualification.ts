export type QualificationStatus = "QUALIFIED" | "REVIEW" | "DISQUALIFIED";
export type ReviewDecision = "PENDING" | "APPROVED" | "REJECTED";

export interface ScoreReason {
  code: string;
  points: number;
  detail?: string;
}

export interface QualificationRun {
  id: string;
  campaign_id: string;
  research_run_id: string;
  status: string;
  scoring_version: string;
  found_count: number;
  created_leads_count: number;
  matched_leads_count: number;
  scored_count: number;
  qualified_count: number;
  review_count: number;
  disqualified_count: number;
  conflict_count: number;
  skipped_count: number;
  error_message: string | null;
  is_test_data: boolean;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface QualificationLead {
  id: string;
  campaign_id: string;
  company_id: string;
  company_name?: string | null;
  company_domain?: string | null;
  qualification_score: number | null;
  qualification_status: string | null;
  review_decision: string;
  score_version: string | null;
  scored_at: string | null;
  score_reasons: ScoreReason[];
  source_research_run_id: string | null;
  is_test_data: boolean;
  reviewed_at: string | null;
  review_note: string | null;
  status: string;
  approved_for_email: boolean;
  created_at: string;
  updated_at: string;
}

export interface QualificationLeadListResponse {
  items: QualificationLead[];
  total: number;
  limit: number;
  offset: number;
}

export interface ResearchRunSummary {
  id: string;
  status: string;
  query: string;
  industry: string | null;
  location: string | null;
  found_count: number;
  created_count: number;
  is_test_data: boolean;
  finished_at: string | null;
}
