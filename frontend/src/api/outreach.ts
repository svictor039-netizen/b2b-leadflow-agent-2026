export type OutreachMessageStatus =
  | "DRAFT"
  | "APPROVED"
  | "REJECTED"
  | "SENDING"
  | "SENT"
  | "FAILED"
  | "BLOCKED";

export interface OutreachTemplate {
  id: string;
  campaign_id: string | null;
  name: string;
  subject_template: string;
  body_template: string;
  is_active: boolean;
  is_test_data: boolean;
  created_at: string;
  updated_at: string;
}

export interface SequenceStep {
  id: string;
  sequence_id: string;
  template_id: string;
  step_number: number;
  created_at: string;
}

export interface OutreachSequence {
  id: string;
  campaign_id: string;
  name: string;
  is_active: boolean;
  is_test_data: boolean;
  created_at: string;
  updated_at: string;
  steps: SequenceStep[];
}

export interface OutreachMessage {
  id: string;
  campaign_id: string;
  campaign_lead_id: string;
  sequence_id: string;
  sequence_step_id: string;
  template_id: string;
  recipient_email: string;
  subject_rendered: string;
  body_rendered: string;
  status: OutreachMessageStatus | string;
  approval_decision: string;
  approved_at: string | null;
  rejected_at: string | null;
  reject_note: string | null;
  sent_at: string | null;
  failed_at: string | null;
  blocked_at: string | null;
  error_message: string | null;
  is_test_data: boolean;
  created_at: string;
  updated_at: string;
  company_name?: string | null;
}

export interface OutreachMessageListResponse {
  items: OutreachMessage[];
  total: number;
  limit: number;
  offset: number;
}

export interface DraftCreateResponse {
  campaign_id: string;
  sequence_id: string;
  created_count: number;
  matched_existing_count: number;
  skipped_count: number;
  conflict_count: number;
  failed_count: number;
}
