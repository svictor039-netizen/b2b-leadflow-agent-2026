export type CampaignStatus =
  | "DRAFT"
  | "SEARCHING"
  | "ENRICHING"
  | "READY_FOR_REVIEW"
  | "APPROVED"
  | "SCHEDULED"
  | "RUNNING"
  | "PAUSED"
  | "COMPLETED"
  | "CANCELLED";

export type SendingMode = "TEST" | "MANUAL_APPROVAL";

export type CompanyStatus = "ACTIVE" | "CLOSED" | "UNKNOWN";

export type ConsentStatus = "UNKNOWN" | "GRANTED" | "DENIED";

export type ContactType = "EMAIL" | "PHONE" | "TELEGRAM" | "WHATSAPP" | "OTHER";

export interface Campaign {
  id: string;
  name: string;
  business_type: string;
  region: string;
  offer: string;
  offer_description: string | null;
  ideal_customer: string | null;
  desired_cta: string | null;
  max_companies: number;
  max_emails_per_lead: number;
  sending_mode: SendingMode;
  status: CampaignStatus;
  created_at: string;
  updated_at: string;
  lead_count: number;
  free_slots: number;
  lead_status_counts?: Record<string, number>;
}

export interface CampaignListResponse {
  items: Campaign[];
  total: number;
  page: number;
  page_size: number;
}

export interface CampaignLead {
  id: string;
  campaign_id: string;
  company_id: string;
  status: string;
  approved_for_research: boolean;
  approved_for_email: boolean;
  created_at: string;
  updated_at: string;
  company_name?: string | null;
  company_domain?: string | null;
  company_status?: string | null;
}

export interface Location {
  id: string;
  company_id: string;
  country: string | null;
  region: string | null;
  city: string | null;
  address: string | null;
  postal_code: string | null;
  latitude: number | null;
  longitude: number | null;
  is_primary: boolean;
  created_at: string;
  updated_at: string;
}

export interface Contact {
  id: string;
  company_id: string;
  contact_type: ContactType;
  value: string;
  label: string | null;
  source_url: string | null;
  collected_at: string | null;
  verified_at: string | null;
  verification_status: string;
  consent_status: ConsentStatus;
  consent_source: string | null;
  do_not_contact: boolean;
  created_at: string;
  updated_at: string;
}

export interface Company {
  id: string;
  name: string;
  legal_name: string | null;
  website: string | null;
  domain: string | null;
  description: string | null;
  status: CompanyStatus;
  source_confidence: number | null;
  created_at: string;
  updated_at: string;
  locations: Location[];
  contacts: Contact[];
}

export interface CompanyListItem {
  id: string;
  name: string;
  domain: string | null;
  website: string | null;
  status: CompanyStatus;
  created_at: string;
  updated_at: string;
}

export interface CompanyListResponse {
  items: CompanyListItem[];
  total: number;
  page: number;
  page_size: number;
}

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      data?.error?.message || data?.detail?.[0]?.msg || data?.detail || `Ошибка ${response.status}`;
    throw new ApiError(String(message), response.status, data?.error?.code);
  }
  return data as T;
}

export const api = {
  listCampaigns: (params: URLSearchParams) =>
    request<CampaignListResponse>(`/api/campaigns?${params}`),
  getCampaign: (id: string) => request<Campaign>(`/api/campaigns/${id}`),
  createCampaign: (body: unknown) =>
    request<Campaign>("/api/campaigns", { method: "POST", body: JSON.stringify(body) }),
  updateCampaign: (id: string, body: unknown) =>
    request<Campaign>(`/api/campaigns/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  listCampaignCompanies: (id: string) =>
    request<CampaignLead[]>(`/api/campaigns/${id}/companies`),
  attachCompany: (campaignId: string, companyId: string) =>
    request<CampaignLead>(`/api/campaigns/${campaignId}/companies/${companyId}`, {
      method: "POST",
    }),
  detachCompany: (campaignId: string, companyId: string) =>
    request<void>(`/api/campaigns/${campaignId}/companies/${companyId}`, { method: "DELETE" }),

  listCompanies: (params: URLSearchParams) =>
    request<CompanyListResponse>(`/api/companies?${params}`),
  getCompany: (id: string) => request<Company>(`/api/companies/${id}`),
  createCompany: (body: unknown) =>
    request<Company>("/api/companies", { method: "POST", body: JSON.stringify(body) }),
  updateCompany: (id: string, body: unknown) =>
    request<Company>(`/api/companies/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  createLocation: (companyId: string, body: unknown) =>
    request<Location>(`/api/companies/${companyId}/locations`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  createContact: (companyId: string, body: unknown) =>
    request<Contact>(`/api/companies/${companyId}/contacts`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateContact: (contactId: string, body: unknown) =>
    request<Contact>(`/api/contacts/${contactId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteContact: (contactId: string) =>
    request<void>(`/api/contacts/${contactId}`, { method: "DELETE" }),

  listResearchRuns: (params: URLSearchParams) =>
    request<import("./qualification").ResearchRunSummary[]>(`/api/research/runs?${params}`),
  createResearchRun: (body: unknown) =>
    request<import("./qualification").ResearchRunSummary>("/api/research/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  startQualification: (body: unknown) =>
    request<import("./qualification").QualificationRun>("/api/qualification/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getQualificationRun: (id: string) =>
    request<import("./qualification").QualificationRun>(`/api/qualification/runs/${id}`),
  listCampaignLeads: (campaignId: string, params: URLSearchParams) =>
    request<import("./qualification").QualificationLeadListResponse>(
      `/api/campaigns/${campaignId}/leads?${params}`,
    ),
  reviewLead: (campaignId: string, leadId: string, body: unknown) =>
    request<import("./qualification").QualificationLead>(
      `/api/campaigns/${campaignId}/leads/${leadId}/review`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  listOutreachTemplates: (campaignId: string) =>
    request<import("./outreach").OutreachTemplate[]>(
      `/api/campaigns/${campaignId}/outreach/templates`,
    ),
  createOutreachTemplate: (campaignId: string, body: unknown) =>
    request<import("./outreach").OutreachTemplate>(
      `/api/campaigns/${campaignId}/outreach/templates`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  updateOutreachTemplate: (campaignId: string, templateId: string, body: unknown) =>
    request<import("./outreach").OutreachTemplate>(
      `/api/campaigns/${campaignId}/outreach/templates/${templateId}`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),
  listOutreachSequences: (campaignId: string) =>
    request<import("./outreach").OutreachSequence[]>(
      `/api/campaigns/${campaignId}/outreach/sequences`,
    ),
  createOutreachSequence: (campaignId: string, body: unknown) =>
    request<import("./outreach").OutreachSequence>(
      `/api/campaigns/${campaignId}/outreach/sequences`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  createOutreachDrafts: (campaignId: string, body: unknown) =>
    request<import("./outreach").DraftCreateResponse>(
      `/api/campaigns/${campaignId}/outreach/drafts`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  listOutreachMessages: (campaignId: string, params: URLSearchParams) =>
    request<import("./outreach").OutreachMessageListResponse>(
      `/api/campaigns/${campaignId}/outreach/messages?${params}`,
    ),
  approveOutreachMessage: (campaignId: string, messageId: string) =>
    request<import("./outreach").OutreachMessage>(
      `/api/campaigns/${campaignId}/outreach/messages/${messageId}/approve`,
      { method: "POST" },
    ),
  rejectOutreachMessage: (campaignId: string, messageId: string, body?: unknown) =>
    request<import("./outreach").OutreachMessage>(
      `/api/campaigns/${campaignId}/outreach/messages/${messageId}/reject`,
      { method: "POST", body: JSON.stringify(body ?? {}) },
    ),
  sendOutreachMessage: (campaignId: string, messageId: string) =>
    request<import("./outreach").OutreachMessage>(
      `/api/campaigns/${campaignId}/outreach/messages/${messageId}/send`,
      { method: "POST" },
    ),

  createExecutionRun: (campaignId: string, body: unknown) =>
    request<import("./execution").ExecutionRun>(
      `/api/campaigns/${campaignId}/execution-runs`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  listExecutionRuns: (campaignId: string, params: URLSearchParams) =>
    request<{ items: import("./execution").ExecutionRun[]; total: number }>(
      `/api/campaigns/${campaignId}/execution-runs?${params}`,
    ),
  getExecutionRun: (campaignId: string, runId: string) =>
    request<import("./execution").ExecutionRun>(
      `/api/campaigns/${campaignId}/execution-runs/${runId}`,
    ),
  startExecutionRun: (campaignId: string, runId: string) =>
    request<import("./execution").ExecutionRun>(
      `/api/campaigns/${campaignId}/execution-runs/${runId}/start?async_mode=false`,
      { method: "POST" },
    ),
  pauseExecutionRun: (campaignId: string, runId: string) =>
    request<import("./execution").ExecutionRun>(
      `/api/campaigns/${campaignId}/execution-runs/${runId}/pause`,
      { method: "POST" },
    ),
  resumeExecutionRun: (campaignId: string, runId: string) =>
    request<import("./execution").ExecutionRun>(
      `/api/campaigns/${campaignId}/execution-runs/${runId}/resume?async_mode=false`,
      { method: "POST" },
    ),
  cancelExecutionRun: (campaignId: string, runId: string) =>
    request<import("./execution").ExecutionRun>(
      `/api/campaigns/${campaignId}/execution-runs/${runId}/cancel`,
      { method: "POST" },
    ),
  listExecutionItems: (campaignId: string, runId: string, params: URLSearchParams) =>
    request<{ items: import("./execution").ExecutionItem[]; total: number }>(
      `/api/campaigns/${campaignId}/execution-runs/${runId}/items?${params}`,
    ),
  getCampaignAnalytics: (campaignId: string) =>
    request<import("./execution").CampaignAnalytics>(
      `/api/campaigns/${campaignId}/analytics`,
    ),
};

export const campaignStatusLabel: Record<CampaignStatus, string> = {
  DRAFT: "Черновик",
  SEARCHING: "Поиск",
  ENRICHING: "Обогащение",
  READY_FOR_REVIEW: "Готово к проверке",
  APPROVED: "Утверждена",
  SCHEDULED: "Запланирована",
  RUNNING: "Запущена",
  PAUSED: "Пауза",
  COMPLETED: "Завершена",
  CANCELLED: "Отменена",
};

export const companyStatusLabel: Record<CompanyStatus, string> = {
  ACTIVE: "Активна",
  CLOSED: "Закрыта",
  UNKNOWN: "Неизвестно",
};

export const consentLabel: Record<ConsentStatus, string> = {
  UNKNOWN: "Не подтверждено",
  GRANTED: "Получено",
  DENIED: "Отклонено",
};

export const contactTypeLabel: Record<ContactType, string> = {
  EMAIL: "Email",
  PHONE: "Телефон",
  TELEGRAM: "Telegram",
  WHATSAPP: "WhatsApp",
  OTHER: "Другое",
};

export const sendingModeLabel: Record<SendingMode, string> = {
  TEST: "Тестовый",
  MANUAL_APPROVAL: "Ручное подтверждение",
};
