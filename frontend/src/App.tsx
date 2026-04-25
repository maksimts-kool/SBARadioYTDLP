import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Container,
  Divider,
  FormControl,
  FormControlLabel,
  FormLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileAudio, Film, LinkIcon, PackageCheck, Search, Trash2, XCircle } from "lucide-react";
import { z } from "zod";
import { ApiError, cancelJob, downloadUrl, getAvailableJobs, getJob, jobEventsUrl, previewUrl, startJob } from "./api";
import type { JobStatusResponse, MediaKind, PreviewEntry, PreviewResponse } from "./types";

const urlSchema = z.string().url("Enter a valid YouTube URL.");
const MAX_SELECTED_ITEMS = 50;
const CURRENT_JOB_STORAGE_KEY = "sbaradio-ytdlp-current-job-id";
const TERMINAL_JOB_STATUSES = new Set<JobStatusResponse["status"]>(["ready", "failed", "cancelled"]);

const qualityOptions: Record<MediaKind, string[]> = {
  mp4: ["best", "1080p", "720p", "480p", "360p"],
  mp3: ["best", "320k", "192k", "128k"]
};

function App() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [kind, setKind] = useState<MediaKind>("mp4");
  const [quality, setQuality] = useState("best");
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [jobId, setJobId] = useState<string | null>(() => readStoredJobId());
  const [liveJob, setLiveJob] = useState<JobStatusResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const previewMutation = useMutation({
    mutationFn: previewUrl,
    onSuccess: (data) => {
      setPreview(data);
      clearActiveJob();
      setLiveJob(null);
      if (data.kind === "playlist") {
        setSelectedIds(data.entries.slice(0, MAX_SELECTED_ITEMS).map((entry) => entry.id));
      } else {
        setSelectedIds([]);
      }
    },
    onError: (error) => setNotice(errorMessage(error))
  });

  const startMutation = useMutation({
    mutationFn: startJob,
    onSuccess: (data) => {
      setActiveJob(data.jobId);
      setLiveJob(data);
    },
    onError: (error) => setNotice(errorMessage(error))
  });

  const cancelMutation = useMutation({
    mutationFn: cancelJob,
    onSuccess: (data) => {
      setLiveJob(data);
      void queryClient.invalidateQueries({ queryKey: ["available-jobs"] });
    },
    onError: (error) => setNotice(errorMessage(error))
  });

  const clearAvailableMutation = useMutation({
    mutationFn: cancelJob,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["available-jobs"] });
    },
    onError: (error) => setNotice(errorMessage(error))
  });

  const polledJob = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId!),
    enabled: Boolean(jobId) && !isTerminalJobStatus(liveJob?.status),
    refetchInterval: (query) => {
      const data = query.state.data as JobStatusResponse | undefined;
      return isTerminalJobStatus(data?.status ?? liveJob?.status) ? false : 1500;
    },
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) {
        return false;
      }
      return failureCount < 1;
    }
  });

  const availableJobsQuery = useQuery({
    queryKey: ["available-jobs"],
    queryFn: getAvailableJobs
  });

  const job = liveJob ?? polledJob.data ?? null;
  const availableJobs = (availableJobsQuery.data ?? []).filter((availableJob) => availableJob.jobId !== job?.jobId);
  const isWorking = job ? !isTerminalJobStatus(job.status) : false;
  const selectedCount = preview?.kind === "playlist" ? selectedIds.length : preview ? 1 : 0;
  const canStart = Boolean(preview) && selectedCount > 0 && selectedCount <= MAX_SELECTED_ITEMS && termsAccepted && !isWorking;

  useEffect(() => {
    if (!jobId) {
      return;
    }

    const eventsUrl = jobEventsUrl(jobId);
    if (!eventsUrl) {
      return;
    }

    const socket = new WebSocket(eventsUrl);
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as Partial<JobStatusResponse> & { error?: string };
      if (!payload.jobId) {
        clearActiveJob();
        setNotice(payload.error ?? "Previous download is no longer available.");
        return;
      }
      setLiveJob(payload as JobStatusResponse);
    };
    socket.onerror = () => {
      setNotice("Live progress disconnected. Polling is still active.");
    };

    return () => socket.close();
  }, [jobId]);

  useEffect(() => {
    if (!polledJob.data) {
      return;
    }
    setLiveJob(polledJob.data);
    if (polledJob.data.status === "ready") {
      void queryClient.invalidateQueries({ queryKey: ["available-jobs"] });
    }
  }, [polledJob.data, queryClient]);

  useEffect(() => {
    if (!polledJob.error) {
      return;
    }

    if (polledJob.error instanceof ApiError && polledJob.error.status === 404) {
      clearActiveJob();
      setNotice("Previous download is no longer available.");
      return;
    }

    setNotice(errorMessage(polledJob.error));
  }, [polledJob.error]);

  function setActiveJob(nextJobId: string) {
    setJobId(nextJobId);
    writeStoredJobId(nextJobId);
  }

  function clearActiveJob() {
    setJobId(null);
    clearStoredJobId();
  }

  function submitPreview(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = urlSchema.safeParse(url.trim());
    if (!parsed.success) {
      setNotice(parsed.error.issues[0]?.message ?? "Enter a valid YouTube URL.");
      return;
    }
    previewMutation.mutate(parsed.data);
  }

  function submitJob() {
    if (!preview) {
      return;
    }
    startMutation.mutate({
      url: preview.url,
      kind,
      quality,
      entryIds: preview.kind === "playlist" ? selectedIds : [],
      termsAccepted
    });
  }

  function toggleEntry(entryId: string) {
    setSelectedIds((current) => {
      if (current.includes(entryId)) {
        return current.filter((id) => id !== entryId);
      }
      if (current.length >= MAX_SELECTED_ITEMS) {
        setNotice(`Select at most ${MAX_SELECTED_ITEMS} playlist items.`);
        return current;
      }
      return [...current, entryId];
    });
  }

  function selectAllVisible() {
    if (!preview || preview.kind !== "playlist") {
      return;
    }
    setSelectedIds(preview.entries.slice(0, MAX_SELECTED_ITEMS).map((entry) => entry.id));
  }

  function clearSelection() {
    setSelectedIds([]);
  }

  function changeKind(nextKind: MediaKind | null) {
    if (!nextKind) {
      return;
    }
    setKind(nextKind);
    setQuality("best");
  }

  return (
    <Box className="min-h-screen bg-[radial-gradient(circle_at_top_left,#e9f4f1_0,#f6f7f4_32rem,#f1efe8_100%)]">
      <Container maxWidth="lg" className="py-8 md:py-10">
        <Stack spacing={3}>
          <Header />

          <Paper variant="outlined" className="p-4 md:p-5">
            <Stack component="form" onSubmit={submitPreview} spacing={2}>
              <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
                <TextField
                  fullWidth
                  label="YouTube link"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder="https://www.youtube.com/watch?v=..."
                  autoComplete="off"
                  InputProps={{
                    startAdornment: <LinkIcon size={18} className="mr-2 text-slate-500" />
                  }}
                />
                <Button
                  type="submit"
                  variant="contained"
                  size="large"
                  startIcon={previewMutation.isPending ? <CircularProgress size={18} color="inherit" /> : <Search size={18} />}
                  disabled={previewMutation.isPending}
                  className="md:w-40"
                >
                  Preview
                </Button>
              </Stack>
            </Stack>
          </Paper>

          {preview && (
            <Stack direction={{ xs: "column", lg: "row" }} spacing={3} alignItems="stretch">
              <Paper variant="outlined" className="min-w-0 flex-1 p-4 md:p-5">
                <PreviewPanel preview={preview} selectedIds={selectedIds} onToggle={toggleEntry} onSelectAll={selectAllVisible} onClear={clearSelection} />
              </Paper>

              <Paper variant="outlined" className="w-full p-4 md:w-[360px] md:p-5">
                <Stack spacing={2.5}>
                  <FormatControls kind={kind} quality={quality} onKindChange={changeKind} onQualityChange={setQuality} />

                  <Divider />

                  <Stack spacing={1}>
                    <Stack direction="row" justifyContent="space-between">
                      <Typography variant="body2" color="text.secondary">
                        Selected
                      </Typography>
                      <Chip size="small" label={`${selectedCount} item${selectedCount === 1 ? "" : "s"}`} />
                    </Stack>

                    {preview.kind === "playlist" && preview.entries.length > MAX_SELECTED_ITEMS && (
                      <Alert severity="warning">
                        The first {MAX_SELECTED_ITEMS} items are selected by default. Reduce the playlist selection before starting.
                      </Alert>
                    )}

                    <FormControlLabel
                      control={<Checkbox checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)} />}
                      label="I have the right to download this media."
                    />
                  </Stack>

                  <Button
                    variant="contained"
                    size="large"
                    startIcon={startMutation.isPending ? <CircularProgress size={18} color="inherit" /> : kind === "mp3" ? <FileAudio size={18} /> : <Film size={18} />}
                    onClick={submitJob}
                    disabled={!canStart || startMutation.isPending}
                    fullWidth
                  >
                    Start download
                  </Button>
                </Stack>
              </Paper>
            </Stack>
          )}

          {job && (
            <Paper variant="outlined" className="p-4 md:p-5">
              <ProgressPanel job={job} onCancel={() => cancelMutation.mutate(job.jobId)} cancelling={cancelMutation.isPending} />
            </Paper>
          )}

          {availableJobs.length > 0 && (
            <Paper variant="outlined" className="p-4 md:p-5">
              <AvailableDownloadsPanel
                jobs={availableJobs}
                onClear={(availableJobId) => clearAvailableMutation.mutate(availableJobId)}
                clearingJobId={clearAvailableMutation.variables ?? null}
              />
            </Paper>
          )}
        </Stack>
      </Container>

      <Snackbar open={Boolean(notice)} autoHideDuration={5000} onClose={() => setNotice(null)} anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
        <Alert severity="error" variant="filled" onClose={() => setNotice(null)}>
          {notice}
        </Alert>
      </Snackbar>
    </Box>
  );
}

function readStoredJobId(): string | null {
  try {
    return window.localStorage.getItem(CURRENT_JOB_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredJobId(jobId: string) {
  try {
    window.localStorage.setItem(CURRENT_JOB_STORAGE_KEY, jobId);
  } catch {
    return;
  }
}

function clearStoredJobId() {
  try {
    window.localStorage.removeItem(CURRENT_JOB_STORAGE_KEY);
  } catch {
    return;
  }
}

function Header() {
  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1.25} alignItems="center">
        <Box className="grid h-10 w-10 place-items-center rounded bg-[#1f6f78] text-white">
          <Download size={21} />
        </Box>
        <Box>
          <Typography variant="h4" component="h1" fontWeight={800}>
            SBARadioYTDLP
          </Typography>
          <Typography variant="body2" color="text.secondary">
            YouTube video and playlist downloader
          </Typography>
        </Box>
      </Stack>
    </Stack>
  );
}

interface PreviewPanelProps {
  preview: PreviewResponse;
  selectedIds: string[];
  onToggle: (entryId: string) => void;
  onSelectAll: () => void;
  onClear: () => void;
}

function PreviewPanel({ preview, selectedIds, onToggle, onSelectAll, onClear }: PreviewPanelProps) {
  const isPlaylist = preview.kind === "playlist";

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <Thumbnail src={preview.thumbnail} title={preview.title} />
        <Stack spacing={1} className="min-w-0 flex-1">
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Chip size="small" color={isPlaylist ? "secondary" : "primary"} label={isPlaylist ? "Playlist" : "Video"} />
            {preview.duration ? <Chip size="small" variant="outlined" label={formatDuration(preview.duration)} /> : null}
            {isPlaylist ? <Chip size="small" variant="outlined" label={`${preview.entries.length} items`} /> : null}
          </Stack>
          <Typography variant="h6" fontWeight={800} className="break-words">
            {preview.title}
          </Typography>
          {preview.uploader && (
            <Typography variant="body2" color="text.secondary">
              {preview.uploader}
            </Typography>
          )}
        </Stack>
      </Stack>

      {isPlaylist && (
        <>
          <Stack direction="row" spacing={1} alignItems="center">
            <Button size="small" variant="outlined" onClick={onSelectAll}>
              Select first {Math.min(MAX_SELECTED_ITEMS, preview.entries.length)}
            </Button>
            <Button size="small" color="inherit" onClick={onClear}>
              Clear
            </Button>
            <Typography variant="body2" color="text.secondary" className="ml-auto">
              {selectedIds.length} selected
            </Typography>
          </Stack>

          <TableContainer className="max-h-[460px] rounded border border-slate-200">
            <Table stickyHeader size="small" aria-label="Playlist entries">
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox" />
                  <TableCell>Title</TableCell>
                  <TableCell width={110}>Duration</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {preview.entries.map((entry) => (
                  <PlaylistRow key={`${entry.id}-${entry.index}`} entry={entry} checked={selectedIds.includes(entry.id)} onToggle={onToggle} />
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}
    </Stack>
  );
}

function PlaylistRow({ entry, checked, onToggle }: { entry: PreviewEntry; checked: boolean; onToggle: (entryId: string) => void }) {
  return (
    <TableRow hover selected={checked}>
      <TableCell padding="checkbox">
        <Checkbox checked={checked} onChange={() => onToggle(entry.id)} inputProps={{ "aria-label": `Select ${entry.title}` }} />
      </TableCell>
      <TableCell>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <Thumbnail src={entry.thumbnail} title={entry.title} compact />
          <Box className="min-w-0">
            <Typography variant="body2" fontWeight={700} className="line-clamp-2">
              {entry.title}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              #{entry.index}
            </Typography>
          </Box>
        </Stack>
      </TableCell>
      <TableCell>{entry.duration ? formatDuration(entry.duration) : "-"}</TableCell>
    </TableRow>
  );
}

function Thumbnail({ src, title, compact = false }: { src?: string | null; title: string; compact?: boolean }) {
  const classes = compact ? "h-12 w-20" : "h-32 w-full sm:w-56";

  return (
    <Box className={`${classes} shrink-0 overflow-hidden rounded bg-slate-200`}>
      {src ? (
        <img src={src} alt={title} className="h-full w-full object-cover" loading="lazy" />
      ) : (
        <Box className="grid h-full w-full place-items-center text-slate-500">
          <Film size={compact ? 18 : 32} />
        </Box>
      )}
    </Box>
  );
}

function FormatControls({
  kind,
  quality,
  onKindChange,
  onQualityChange
}: {
  kind: MediaKind;
  quality: string;
  onKindChange: (kind: MediaKind | null) => void;
  onQualityChange: (quality: string) => void;
}) {
  const options = useMemo(() => qualityOptions[kind], [kind]);

  return (
    <Stack spacing={2}>
      <FormControl>
        <FormLabel className="mb-2">Format</FormLabel>
        <ToggleButtonGroup value={kind} exclusive onChange={(_, value) => onKindChange(value)} fullWidth>
          <ToggleButton value="mp4">
            <Stack direction="row" spacing={1} alignItems="center">
              <Film size={18} />
              <span>MP4</span>
            </Stack>
          </ToggleButton>
          <ToggleButton value="mp3">
            <Stack direction="row" spacing={1} alignItems="center">
              <FileAudio size={18} />
              <span>MP3</span>
            </Stack>
          </ToggleButton>
        </ToggleButtonGroup>
      </FormControl>

      <FormControl fullWidth>
        <FormLabel className="mb-2">Quality</FormLabel>
        <Select value={quality} onChange={(event) => onQualityChange(event.target.value)}>
          {options.map((option) => (
            <MenuItem key={option} value={option}>
              {qualityLabel(kind, option)}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Stack>
  );
}

function AvailableDownloadsPanel({
  jobs,
  onClear,
  clearingJobId
}: {
  jobs: JobStatusResponse[];
  onClear: (jobId: string) => void;
  clearingJobId: string | null;
}) {
  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
        <Box>
          <Typography variant="h6" fontWeight={800}>
            Available downloads
          </Typography>
        </Box>
        <Chip size="small" label={`${jobs.length} ready`} />
      </Stack>

      <TableContainer className="rounded border border-slate-200">
        <Table size="small" aria-label="Available downloads">
          <TableHead>
            <TableRow>
              <TableCell>File</TableCell>
              <TableCell width={150}>Ready</TableCell>
              <TableCell align="right" width={220}>
                Actions
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {jobs.map((availableJob) => (
              <TableRow key={availableJob.jobId} hover>
                <TableCell>
                  <Stack spacing={0.5}>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                      <Typography variant="body2" fontWeight={800}>
                        {availableJob.isArchive ? "Playlist archive" : "Media file"}
                      </Typography>
                      <Chip size="small" variant="outlined" label={availableJob.isArchive ? "ZIP" : "Media"} />
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                      {availableJob.message ?? statusLabel(availableJob.status)}
                    </Typography>
                  </Stack>
                </TableCell>
                <TableCell>{formatDateTime(availableJob.updatedAt)}</TableCell>
                <TableCell align="right">
                  <Stack direction="row" spacing={1} justifyContent="flex-end">
                    <Button component="a" href={downloadUrl(availableJob.jobId)} size="small" variant="contained" startIcon={<Download size={16} />}>
                      Download
                    </Button>
                    <Button
                      size="small"
                      color="inherit"
                      variant="outlined"
                      onClick={() => onClear(availableJob.jobId)}
                      disabled={clearingJobId === availableJob.jobId}
                      startIcon={<Trash2 size={16} />}
                    >
                      Clear
                    </Button>
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Stack>
  );
}

function ProgressPanel({ job, onCancel, cancelling }: { job: JobStatusResponse; onCancel: () => void; cancelling: boolean }) {
  const terminal = isTerminalJobStatus(job.status);
  const color = job.status === "failed" ? "error" : job.status === "ready" ? "success" : "primary";

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", md: "center" }}>
        <Stack direction="row" spacing={1} alignItems="center">
          {job.status === "ready" ? <CheckCircle2 size={22} className="text-emerald-700" /> : job.status === "failed" ? <XCircle size={22} className="text-red-700" /> : <PackageCheck size={22} className="text-[#1f6f78]" />}
          <Box>
            <Typography variant="subtitle1" fontWeight={800}>
              {statusLabel(job.status)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {job.message ?? job.currentItem ?? "Working"}
            </Typography>
          </Box>
        </Stack>

        <Stack direction="row" spacing={1}>
          {!terminal && (
            <Button color="inherit" variant="outlined" onClick={onCancel} disabled={cancelling} startIcon={<XCircle size={18} />}>
              Cancel
            </Button>
          )}
          {job.status === "ready" && (
            <Button component="a" href={downloadUrl(job.jobId)} variant="contained" startIcon={<Download size={18} />}>
              Download {job.isArchive ? "ZIP" : "file"}
            </Button>
          )}
        </Stack>
      </Stack>

      <Box>
        <LinearProgress variant="determinate" value={job.progress} color={color} className="h-2 rounded" />
        <Stack direction="row" justifyContent="space-between" className="mt-1">
          <Typography variant="caption" color="text.secondary">
            {job.completedItems} / {job.totalItems || 1} done
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {Math.round(job.progress)}%
          </Typography>
        </Stack>
      </Box>

      {job.currentItem && (
        <Typography variant="body2" className="break-words">
          {job.currentItem}
        </Typography>
      )}

      {job.error && <Alert severity="error">{job.error}</Alert>}
    </Stack>
  );
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong.";
}

function formatDuration(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const secs = safeSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "short",
    timeStyle: "short"
  }).format(new Date(value));
}

function isTerminalJobStatus(status?: JobStatusResponse["status"] | null): boolean {
  return Boolean(status && TERMINAL_JOB_STATUSES.has(status));
}

function statusLabel(status: JobStatusResponse["status"]): string {
  const labels: Record<JobStatusResponse["status"], string> = {
    queued: "Queued",
    metadata: "Reading media",
    downloading: "Downloading",
    converting: "Converting",
    archiving: "Creating archive",
    ready: "Ready",
    failed: "Failed",
    cancelled: "Cancelled"
  };
  return labels[status];
}

function qualityLabel(kind: MediaKind, quality: string): string {
  if (quality === "best") {
    return kind === "mp4" ? "Best available" : "Best audio";
  }
  return quality;
}

export default App;
