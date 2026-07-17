export interface HealthResponse {
  status: string;
  service: string;
}

export interface ReadinessResponse {
  status: string;
  checks: {
    postgres: string;
    redis: string;
  };
}

export interface VersionResponse {
  version: string;
  environment: string;
  stage: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const fetchHealth = () => fetchJson<HealthResponse>("/api/health");
export const fetchReadiness = () => fetchJson<ReadinessResponse>("/api/readiness");
export const fetchVersion = () => fetchJson<VersionResponse>("/api/version");
