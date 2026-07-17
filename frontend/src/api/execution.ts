export interface ExecutionRun {
  id: string;
  campaign_id: string;
  sequence_id: string;
  status: string;
  execution_mode: string;
  max_messages: number;
  batch_size: number;
  planned_count: number;
  processed_count: number;
  sent_count: number;
  failed_count: number;
  blocked_count: number;
  skipped_count: number;
  unknown_count: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  is_test_data: boolean;
  matched_existing?: boolean;
}

export interface ExecutionItem {
  id: string;
  outreach_message_id: string;
  position: number;
  status: string;
  error_message: string | null;
  finished_at: string | null;
  message_status?: string | null;
  company_name?: string | null;
}

export interface CampaignAnalytics {
  campaign_id: string;
  is_test_data: boolean;
  approved_leads: number;
  draft_messages: number;
  approved_messages: number;
  sent_messages: number;
  failed_messages: number;
  blocked_messages: number;
  unknown_messages: number;
  rejected_messages: number;
  execution_runs_total: number;
  execution_runs_completed: number;
  execution_runs_failed: number;
  execution_runs_blocked: number;
  latest_run_status: string | null;
  test_delivery_rate: number;
  failure_rate: number;
}
