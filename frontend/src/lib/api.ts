/** Minimal REST client shell. Auth cookies and error decoding expand in S1. */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    let code = "HTTP_ERROR";
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { code?: string; detail?: string };
      code = body.code ?? code;
      detail = body.detail ?? detail;
    } catch {
      // ignore non-JSON error bodies
    }
    throw new ApiError(detail, response.status, code);
  }
  return (await response.json()) as T;
}

export type HealthResponse = {
  status: string;
  service: string;
  version: string;
  env: string;
};

export function fetchHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/health");
}
