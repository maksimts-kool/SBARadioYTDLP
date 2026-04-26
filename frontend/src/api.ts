import type {
  AdminBlockedIpsResponse,
  AdminCleanupResponse,
  AdminDashboardResponse,
  AdminSessionResponse,
  JobCreateRequest,
  JobStatusResponse,
  PreviewResponse,
  ServerStatusResponse
} from "./types";

const API_BASE = normalizeApiBase(import.meta.env.VITE_API_BASE ?? "/api");
const ENABLE_JOB_EVENTS = import.meta.env.VITE_ENABLE_JOB_EVENTS !== "false";
const DEVICE_ID_STORAGE_KEY = "sbaradio-ytdlp-device-id";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit, token?: string): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(apiUrl(path), {
    ...init,
    headers
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

export function getServerStatus(): Promise<ServerStatusResponse> {
  return apiFetch<ServerStatusResponse>("/health");
}

export function startJob(payload: JobCreateRequest): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>("/jobs", {
    method: "POST",
    headers: deviceHeaders(),
    body: JSON.stringify(payload)
  });
}

export function getJob(jobId: string): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>(`/jobs/${jobId}`);
}

export function getAvailableJobs(): Promise<JobStatusResponse[]> {
  return apiFetch<JobStatusResponse[]>("/jobs/available", {
    headers: deviceHeaders()
  });
}

export async function cancelJob(jobId: string): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>(`/jobs/${jobId}`, {
    method: "DELETE"
  });
}

export function downloadUrl(jobId: string): string {
  return apiUrl(`/jobs/${jobId}/download`);
}

export function adminFileDownloadUrl(path: string): string {
  return apiUrl(path);
}

export function adminLogin(password: string): Promise<AdminSessionResponse> {
  return apiFetch<AdminSessionResponse>("/admin/login", {
    method: "POST",
    body: JSON.stringify({ password })
  });
}

export function getAdminDashboard(token: string): Promise<AdminDashboardResponse> {
  return apiFetch<AdminDashboardResponse>("/admin/summary", undefined, token);
}

export function cleanupAdminTempFiles(token: string): Promise<AdminCleanupResponse> {
  return apiFetch<AdminCleanupResponse>(
    "/admin/temp/cleanup",
    {
      method: "POST"
    },
    token
  );
}

export function deleteAdminJobTemp(token: string, jobId: string): Promise<AdminCleanupResponse> {
  return apiFetch<AdminCleanupResponse>(
    `/admin/temp/${encodeURIComponent(jobId)}`,
    {
      method: "DELETE"
    },
    token
  );
}

export function blockAdminIp(token: string, ip: string): Promise<AdminBlockedIpsResponse> {
  return apiFetch<AdminBlockedIpsResponse>(
    "/admin/blocked-ips",
    {
      method: "POST",
      body: JSON.stringify({ ip })
    },
    token
  );
}

export function unblockAdminIp(token: string, ip: string): Promise<AdminBlockedIpsResponse> {
  return apiFetch<AdminBlockedIpsResponse>(
    `/admin/blocked-ips/${encodeURIComponent(ip)}`,
    {
      method: "DELETE"
    },
    token
  );
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

function deviceHeaders(): HeadersInit {
  return { "X-Device-Id": getDeviceId() };
}

function getDeviceId(): string {
  try {
    const stored = window.localStorage.getItem(DEVICE_ID_STORAGE_KEY);
    if (stored) {
      return stored;
    }
    const next = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    window.localStorage.setItem(DEVICE_ID_STORAGE_KEY, next);
    return next;
  } catch {
    return "device-storage-unavailable";
  }
}
