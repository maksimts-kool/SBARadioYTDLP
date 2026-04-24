import type { JobCreateRequest, JobStatusResponse, PreviewResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    let message = "Request failed.";
    try {
      const payload = await response.json();
      message = typeof payload.detail === "string" ? payload.detail : message;
    } catch {
      message = response.statusText || message;
    }
    throw new ApiError(message, response.status);
  }

  return response.json() as Promise<T>;
}

export function previewUrl(url: string): Promise<PreviewResponse> {
  return apiFetch<PreviewResponse>("/preview", {
    method: "POST",
    body: JSON.stringify({ url })
  });
}

export function startJob(payload: JobCreateRequest): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>("/jobs", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getJob(jobId: string): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>(`/jobs/${jobId}`);
}

export function getAvailableJobs(): Promise<JobStatusResponse[]> {
  return apiFetch<JobStatusResponse[]>("/jobs/available");
}

export async function cancelJob(jobId: string): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>(`/jobs/${jobId}`, {
    method: "DELETE"
  });
}

export function downloadUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/download`;
}

export function jobEventsUrl(jobId: string): string {
  const url = new URL(`${API_BASE}/jobs/${jobId}/events`, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
