export interface LivePilot {
  id: string;
  campaign_id: string;
  status: string;
  provider_name: string | null;
  subject_snapshot: string;
  max_recipients: number;
  daily_limit: number;
  per_minute_limit: number;
  live_delivery_enabled: boolean;
  primary_message_id: string;
  dry_run_sent_count: number;
  live_sent_count: number;
  approved_at: string | null;
  created_at: string;
}

export interface LivePilotListResponse {
  items: LivePilot[];
  total: number;
  limit: number;
  offset: number;
}

export interface LivePilotValidation {
  ready: boolean;
  overall_status: string;
  blockers: string[];
  warnings: string[];
  checks: { name: string; passed: boolean; detail: string }[];
  test_ready: boolean;
  live_ready: boolean;
  live_mode_ready?: boolean;
  production_status?: string;
}

export interface LivePilotApproval {
  pilot_id: string;
  status: string;
  confirmation_phrase: string | null;
  confirmation_token: string | null;
  approved: boolean;
  message: string;
}

export interface LivePilotDryRunResult {
  pilot_id: string;
  status: string;
  dry_run: boolean;
  simulated: boolean;
  provider: string;
  recipients_processed: number;
  live_sent_count: number;
  message: string;
}

export interface LivePilotRecipient {
  id: string;
  outreach_message_id: string;
  recipient_masked: string;
  status: string;
  position: number;
}
