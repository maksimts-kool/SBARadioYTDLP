import type { JobCreateRequest, JobStatusResponse, PreviewResponse } from "./types";

const API_BASE = normalizeApiBase(import.meta.env.VITE_API_BASE ?? "/api");
const ENABLE_JOB_EVENTS = import.meta.env.VITE_ENABLE_JOB_EVENTS !== "false";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
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
  return apiUrl(`/jobs/${jobId}/download`);
}

export function jobEventsUrl(jobId: string): string | null {
  if (!ENABLE_JOB_EVENTS) {
    return null;
  }

  const url = new URL(apiUrl(`/jobs/${jobId}/events`), window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function normalizeApiBase(value: string): string {
  return value.replace(/\/+$/, "") || "/api";
}

function apiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalizedPath}`;
}
