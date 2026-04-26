export type MediaKind = "mp4" | "mp3";
export type PreviewKind = "video" | "playlist";

export interface PreviewEntry {
  id: string;
  index: number;
  title: string;
  webpageUrl?: string | null;
  thumbnail?: string | null;
  duration?: number | null;
}

export interface PreviewResponse {
  kind: PreviewKind;
  url: string;
  title: string;
  uploader?: string | null;
  thumbnail?: string | null;
  duration?: number | null;
  entries: PreviewEntry[];
}

export type JobState =
  | "queued"
  | "metadata"
  | "downloading"
  | "converting"
  | "archiving"
  | "ready"
  | "failed"
  | "cancelled";

export interface JobStatusResponse {
  jobId: string;
  status: JobState;
  mediaKind: MediaKind;
  quality: string;
  mediaTitle?: string | null;
  progress: number;
  currentItem?: string | null;
  totalItems: number;
  completedItems: number;
  message?: string | null;
  error?: string | null;
  downloadUrl?: string | null;
  isArchive: boolean;
  createdAt: string;
  updatedAt: string;
  expiresAt?: string | null;
}

export interface JobCreateRequest {
  url: string;
  kind: MediaKind;
  quality: string;
  entryIds: string[];
  mediaTitle?: string | null;
  termsAccepted: boolean;
}

export interface ServerStatusResponse {
  status: "ok" | "degraded";
  uptimeSeconds: number;
  activeJobs: number;
  maxActiveJobs: number;
  checks: Record<
    string,
    {
      ok: boolean;
      message: string;
    }
  >;
}

export interface AdminSessionResponse {
  token: string;
  expiresAt: string;
}

export interface AdminDiskResponse {
  tempRoot: string;
  totalBytes: number;
  usedBytes: number;
  freeBytes: number;
  tempBytes: number;
  usagePercent: number;
  cleanupAfterSeconds: number;
}

export interface AdminFileResponse {
  relativePath: string;
  name: string;
  jobId?: string | null;
  status?: JobState | string | null;
  sizeBytes: number;
  modifiedAt: string;
  downloadUrl?: string | null;
  isOutput: boolean;
  deletable: boolean;
}

export interface AdminVisitorResponse {
  ip: string;
  firstSeen: string;
  lastSeen: string;
  requestCount: number;
  lastPath: string;
  userAgent: string;
  blocked: boolean;
}

export interface AdminTransferResponse {
  transferId: string;
  direction: "upload";
  jobId: string;
  ip: string;
  fileName: string;
  sizeBytes: number;
  status: "active" | "completed" | "failed";
  startedAt: string;
  completedAt?: string | null;
}

export interface AdminEventResponse {
  eventId: string;
  category: string;
  message: string;
  ip?: string | null;
  jobId?: string | null;
  createdAt: string;
}

export interface AdminDashboardResponse {
  serverTime: string;
  uptimeSeconds: number;
  activeJobs: number;
  maxActiveJobs: number;
  disk: AdminDiskResponse;
  currentJobs: JobStatusResponse[];
  jobHistory: JobStatusResponse[];
  availableFiles: AdminFileResponse[];
  tempFiles: AdminFileResponse[];
  visitors: AdminVisitorResponse[];
  blockedIps: string[];
  activeUploads: AdminTransferResponse[];
  uploadHistory: AdminTransferResponse[];
  events: AdminEventResponse[];
}

export interface AdminCleanupResponse {
  removedFiles: number;
  removedDirectories: number;
  removedBytes: number;
}

export interface AdminBlockedIpsResponse {
  blockedIps: string[];
}
