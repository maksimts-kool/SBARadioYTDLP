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
}

export interface JobCreateRequest {
  url: string;
  kind: MediaKind;
  quality: string;
  entryIds: string[];
  termsAccepted: boolean;
}

