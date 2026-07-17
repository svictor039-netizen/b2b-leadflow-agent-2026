export type SuppressionEntry = {
  id: string;
  scope: string;
  campaign_id: string | null;
  suppression_type: string;
  display_value: string;
  reason: string;
  source: string;
  is_active: boolean;
  expires_at: string | null;
  created_by: string;
  notes: string | null;
  is_test_data: boolean;
  created_at: string;
  updated_at: string;
};

export type ComplianceCheckResult = {
  allowed: boolean;
  decision: string;
  reason_code: string;
  suppression_type: string | null;
  scope: string | null;
  safe_message: string;
  checked_at: string;
  is_test_data: boolean;
};

export type ProviderReadinessReport = {
  overall_status: string;
  test_mode_ready: boolean;
  live_mode_ready: boolean;
  production_readiness_status: string;
  checks: { name: string; status: string; detail: string }[];
  blockers: string[];
  warnings: string[];
  generated_at: string;
  is_test_data: boolean;
};
