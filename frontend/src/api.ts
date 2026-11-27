export interface HealthResponse {
  status: string;
  database: string;
  detail?: string;
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);
  const data = (await response.json()) as HealthResponse;
  if (!response.ok) {
    throw new Error(data.detail ?? `Health check failed (${response.status})`);
  }
  return data;
}
