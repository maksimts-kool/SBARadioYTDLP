import { useCallback, useEffect, useMemo, useState } from "react";
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
  InputLabel,
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
import {
  Activity,
  Ban,
  CheckCircle2,
  Database,
  Download,
  FileAudio,
  Film,
  HardDrive,
  History,
  Home,
  KeyRound,
  Languages,
  LinkIcon,
  LockKeyhole,
  PackageCheck,
  RefreshCw,
  Search,
  Shield,
  Trash2,
  TriangleAlert,
  UploadCloud,
  UserRound,
  XCircle
} from "lucide-react";
import { z } from "zod";
import {
  ApiError,
  adminFileDownloadUrl,
  adminLogin,
  blockAdminIp,
  cancelJob,
  cleanupAdminTempFiles,
  deleteAdminJobTemp,
  downloadUrl,
  getAdminDashboard,
  getAvailableJobs,
  getJob,
  getServerStatus,
  jobEventsUrl,
  previewUrl,
  startJob,
  unblockAdminIp
} from "./api";
import { LANGUAGE_STORAGE_KEY, isLanguage, languageOptions, translations } from "./i18n";
import type { Language, Translation } from "./i18n";
import type {
  AdminDashboardResponse,
  AdminFileResponse,
  AdminTransferResponse,
  AdminVisitorResponse,
  JobStatusResponse,
  MediaKind,
  PreviewEntry,
  PreviewResponse,
  ServerStatusResponse
} from "./types";

const urlSchema = z.string().url();
const MAX_SELECTED_ITEMS = 50;
const CURRENT_JOB_STORAGE_KEY = "sbaradio-ytdlp-current-job-id";
const ADMIN_TOKEN_STORAGE_KEY = "sbaradio-ytdlp-admin-token";
const TERMINAL_JOB_STATUSES = new Set<JobStatusResponse["status"]>(["ready", "failed", "cancelled"]);
const SERVER_STATUS_HEALTHY_INTERVAL_MS = 30000;
const SERVER_STATUS_PROBLEM_INTERVAL_MS = 5000;
const ADMIN_REFRESH_INTERVAL_MS = 3000;
type ServerStatusState = "checking" | "online" | "degraded" | "offline";
type AppView = "download" | "admin";
type NoticeSeverity = "success" | "info" | "warning" | "error";

interface Notice {
  message: string;
  severity: NoticeSeverity;
}

const qualityOptions: Record<MediaKind, string[]> = {
  mp4: ["best", "1080p", "720p", "480p", "360p"],
  mp3: ["best", "320k", "192k", "128k"]
};

function App() {
  const queryClient = useQueryClient();
  const [language, setLanguage] = useState<Language>(() => readStoredLanguage());
  const [view, setView] = useState<AppView>(() => readViewFromHash());
  const [adminToken, setAdminToken] = useState<string | null>(() => readStoredAdminToken());
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [kind, setKind] = useState<MediaKind>("mp4");
  const [quality, setQuality] = useState("best");
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [jobId, setJobId] = useState<string | null>(() => readStoredJobId());
  const [liveJob, setLiveJob] = useState<JobStatusResponse | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const t = translations[language];

  const showNotice = useCallback((message: string, severity: NoticeSeverity = "error") => {
    setNotice({ message, severity });
  }, []);

  const showError = useCallback((message: string) => {
    showNotice(message, "error");
  }, [showNotice]);

  const showInfo = useCallback((message: string) => {
    showNotice(message, "info");
  }, [showNotice]);

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
    onError: (error) => showError(errorMessage(error, t))
  });

  const startMutation = useMutation({
    mutationFn: startJob,
    onSuccess: (data) => {
      setActiveJob(data.jobId);
      setLiveJob(data);
    },
    onError: (error) => showError(errorMessage(error, t))
  });

  const cancelMutation = useMutation({
    mutationFn: cancelJob,
    onSuccess: (data) => {
      setLiveJob(data);
      void queryClient.invalidateQueries({ queryKey: ["available-jobs"] });
    },
    onError: (error) => showError(errorMessage(error, t))
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

  const serverStatusQuery = useQuery({
    queryKey: ["server-status"],
    queryFn: getServerStatus,
    refetchInterval: (query) =>
      query.state.error || query.state.data?.status === "degraded" ? SERVER_STATUS_PROBLEM_INTERVAL_MS : SERVER_STATUS_HEALTHY_INTERVAL_MS,
    refetchIntervalInBackground: true,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, SERVER_STATUS_PROBLEM_INTERVAL_MS)
  });

  const job = liveJob ?? polledJob.data ?? null;
  const availableJobs = (availableJobsQuery.data ?? []).filter((availableJob) => availableJob.jobId !== job?.jobId);
  const isWorking = job ? !isTerminalJobStatus(job.status) : false;
  const selectedCount = preview?.kind === "playlist" ? selectedIds.length : preview ? 1 : 0;
  const canStart = Boolean(preview) && selectedCount > 0 && selectedCount <= MAX_SELECTED_ITEMS && termsAccepted && !isWorking;
  const serverStatus: ServerStatusState = getServerStatusState(
    serverStatusQuery.data,
    serverStatusQuery.error,
    serverStatusQuery.isPending
  );
  const serverStatusDetail = getServerStatusDetail(
    serverStatusQuery.data,
    serverStatusQuery.error,
    serverStatusQuery.isFetching,
    t
  );

  useEffect(() => {
    document.documentElement.lang = language;
    writeStoredLanguage(language);
  }, [language]);

  useEffect(() => {
    const syncView = () => setView(readViewFromHash());
    window.addEventListener("hashchange", syncView);
    return () => window.removeEventListener("hashchange", syncView);
  }, []);

  useEffect(() => {
    writeStoredAdminToken(adminToken);
  }, [adminToken]);

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
        showNotice(payload.error ? localizeBackendError(payload.error, t) : t.previousDownloadMissing, payload.error ? "error" : "warning");
        return;
      }
      setLiveJob(payload as JobStatusResponse);
    };
    socket.onerror = () => {
      showInfo(t.liveProgressDisconnected);
    };

    return () => socket.close();
  }, [jobId, showInfo, showNotice, t]);

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
      showNotice(t.previousDownloadMissing, "warning");
      return;
    }

    showError(errorMessage(polledJob.error, t));
  }, [polledJob.error, showError, showNotice, t]);

  function setActiveJob(nextJobId: string) {
    setJobId(nextJobId);
    writeStoredJobId(nextJobId);
  }

  function clearActiveJob() {
    setJobId(null);
    clearStoredJobId();
  }

  function changeLanguage(nextLanguage: Language) {
    setLanguage(nextLanguage);
  }

  function changeView(nextView: AppView) {
    setView(nextView);
    if (nextView === "admin") {
      window.location.hash = "admin";
      return;
    }
    if (window.location.hash) {
      window.history.pushState(null, "", `${window.location.pathname}${window.location.search}`);
    }
  }

  function submitPreview(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = urlSchema.safeParse(url.trim());
    if (!parsed.success) {
      showNotice(t.validYouTubeUrl, "warning");
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
      mediaTitle: preview.title,
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
        showNotice(t.selectAtMost(MAX_SELECTED_ITEMS), "warning");
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
    <Box className="app-shell min-h-screen bg-[linear-gradient(180deg,#eff6ff_0%,#ffffff_28rem,#f8fbff_100%)]">
      <Container maxWidth="lg" className="py-8 md:py-10">
        <Stack spacing={3}>
          <Header
            serverStatus={serverStatus}
            serverStatusDetail={serverStatusDetail}
            view={view}
            onViewChange={changeView}
            language={language}
            onLanguageChange={changeLanguage}
            t={t}
          />

          {view === "admin" ? (
            <AdminPanel token={adminToken} onTokenChange={setAdminToken} onNotice={showNotice} t={t} />
          ) : (
            <>
              <Paper variant="outlined" className="motion-card motion-delay-1 p-4 md:p-5">
                <Stack component="form" onSubmit={submitPreview} spacing={2}>
                  <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
                    <TextField
                      fullWidth
                      label={t.youtubeLink}
                      value={url}
                      onChange={(event) => setUrl(event.target.value)}
                      placeholder="https://www.youtube.com/watch?v=..."
                      autoComplete="off"
                      InputProps={{
                        startAdornment: <LinkIcon size={18} className="mr-2 text-blue-500" />
                      }}
                    />
                    <Button
                      type="submit"
                      variant="contained"
                      size="large"
                      startIcon={previewMutation.isPending ? <CircularProgress size={18} color="inherit" /> : <Search size={18} />}
                      disabled={previewMutation.isPending}
                      className="action-button md:w-40"
                    >
                      {t.preview}
                    </Button>
                  </Stack>
                </Stack>
              </Paper>

              {preview && (
                <Stack direction={{ xs: "column", lg: "row" }} spacing={3} alignItems="stretch">
                  <Paper variant="outlined" className="motion-card slide-from-left min-w-0 flex-1 p-4 md:p-5">
                    <PreviewPanel
                      preview={preview}
                      selectedIds={selectedIds}
                      onToggle={toggleEntry}
                      onSelectAll={selectAllVisible}
                      onClear={clearSelection}
                      t={t}
                    />
                  </Paper>

                  <Paper variant="outlined" className="motion-card slide-from-right w-full p-4 md:w-[360px] md:p-5">
                    <Stack spacing={2.5}>
                      <FormatControls kind={kind} quality={quality} onKindChange={changeKind} onQualityChange={setQuality} t={t} />

                      <Divider />

                      <Stack spacing={1}>
                        <Stack direction="row" justifyContent="space-between">
                          <Typography variant="body2" color="text.secondary">
                            {t.selected}
                          </Typography>
                          <Chip size="small" label={t.itemCount(selectedCount)} />
                        </Stack>

                        {preview.kind === "playlist" && preview.entries.length > MAX_SELECTED_ITEMS && (
                          <Alert severity="warning">
                            {t.playlistLimitWarning(MAX_SELECTED_ITEMS)}
                          </Alert>
                        )}

                        <FormControlLabel
                          control={<Checkbox checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)} />}
                          label={t.termsAccepted}
                        />
                      </Stack>

                      <Button
                        variant="contained"
                        size="large"
                        startIcon={startMutation.isPending ? <CircularProgress size={18} color="inherit" /> : kind === "mp3" ? <FileAudio size={18} /> : <Film size={18} />}
                        onClick={submitJob}
                        disabled={!canStart || startMutation.isPending}
                        fullWidth
                        className="action-button"
                      >
                        {t.startDownload}
                      </Button>
                    </Stack>
                  </Paper>
                </Stack>
              )}

              {job && (
                <Paper variant="outlined" className={`motion-card progress-card ${progressCardClass(job.status)} p-4 md:p-5`}>
                  <ProgressPanel job={job} onCancel={() => cancelMutation.mutate(job.jobId)} cancelling={cancelMutation.isPending} t={t} />
                </Paper>
              )}

              {availableJobs.length > 0 && (
                <Paper variant="outlined" className="motion-card motion-delay-2 p-4 md:p-5">
                  <AvailableDownloadsPanel jobs={availableJobs} t={t} />
                </Paper>
              )}
            </>
          )}
        </Stack>
      </Container>

      <Snackbar open={Boolean(notice)} autoHideDuration={5000} onClose={() => setNotice(null)} anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
        <Alert severity={notice?.severity ?? "info"} variant="filled" onClose={() => setNotice(null)}>
          {notice?.message}
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

function readViewFromHash(): AppView {
  return window.location.hash.replace("#", "") === "admin" ? "admin" : "download";
}

function readStoredAdminToken(): string | null {
  try {
    return window.localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredAdminToken(token: string | null) {
  try {
    if (token) {
      window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
    }
  } catch {
    return;
  }
}

function readStoredLanguage(): Language {
  try {
    const storedLanguage = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (isLanguage(storedLanguage)) {
      return storedLanguage;
    }
  } catch {
    return "en";
  }
  return "en";
}

function writeStoredLanguage(language: Language) {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    return;
  }
}

function getServerStatusState(
  data: ServerStatusResponse | undefined,
  error: Error | null,
  isPending: boolean
): ServerStatusState {
  if (isPending) {
    return "checking";
  }
  if (error) {
    return "offline";
  }
  return data?.status === "ok" ? "online" : "degraded";
}

function getServerStatusDetail(
  data: ServerStatusResponse | undefined,
  error: Error | null,
  isFetching: boolean,
  t: Translation
): string {
  if (error) {
    return t.serverDetail.lastCheckFailed(SERVER_STATUS_PROBLEM_INTERVAL_MS / 1000, errorMessage(error, t));
  }
  if (!data) {
    return t.serverDetail.waiting;
  }

  const failedChecks = Object.entries(data.checks)
    .filter(([, check]) => !check.ok)
    .map(([name, check]) => `${name}: ${localizeHealthMessage(check.message, t)}`);
  const summary = failedChecks.length > 0 ? failedChecks.join("; ") : t.serverDetail.activeJobs(data.activeJobs, data.maxActiveJobs);
  const refreshNote = isFetching ? t.serverDetail.refreshing : "";
  return `${summary}. ${t.serverDetail.uptime(formatUptime(data.uptimeSeconds, t))}${refreshNote}`;
}

function formatUptime(totalSeconds: number, t: Translation): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;

  if (hours > 0) {
    return t.uptime.hoursMinutes(hours, minutes);
  }
  if (minutes > 0) {
    return t.uptime.minutesSeconds(minutes, remainingSeconds);
  }
  return t.uptime.seconds(remainingSeconds);
}

function Header({
  serverStatus,
  serverStatusDetail,
  view,
  onViewChange,
  language,
  onLanguageChange,
  t
}: {
  serverStatus: ServerStatusState;
  serverStatusDetail: string;
  view: AppView;
  onViewChange: (view: AppView) => void;
  language: Language;
  onLanguageChange: (language: Language) => void;
  t: Translation;
}) {
  const statusLabel = t.serverStatus[serverStatus];

  const chipColor = {
    checking: "default",
    online: "success",
    degraded: "warning",
    offline: "error"
  }[serverStatus] as "default" | "success" | "warning" | "error";

  return (
    <Stack spacing={1} className="header-motion">
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Box className="logo-mark grid h-10 w-10 place-items-center rounded bg-blue-600 text-white">
            <Download size={21} />
          </Box>
          <Box>
            <Typography variant="h4" component="h1" fontWeight={800}>
              SBA YTDLP
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {t.appSubtitle}
            </Typography>
          </Box>
        </Stack>

        <Stack direction="row" spacing={1} alignItems="center" className="w-full flex-wrap sm:w-auto">
          <Button
            size="small"
            variant={view === "admin" ? "contained" : "outlined"}
            color={view === "admin" ? "primary" : "inherit"}
            onClick={() => onViewChange(view === "admin" ? "download" : "admin")}
            startIcon={view === "admin" ? <Home size={16} /> : <Shield size={16} />}
          >
            {view === "admin" ? t.admin.backToApp : t.admin.openAdmin}
          </Button>
          <FormControl size="small" className="min-w-32" variant="outlined">
            <InputLabel id="language-select-label">{t.languageLabel}</InputLabel>
            <Select
              labelId="language-select-label"
              value={language}
              label={t.languageLabel}
              onChange={(event) => onLanguageChange(event.target.value as Language)}
              startAdornment={<Languages size={16} className="mr-2 text-blue-500" />}
            >
              {languageOptions.map((option) => (
                <MenuItem key={option.code} value={option.code}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Chip
            className="status-chip"
            color={chipColor}
            variant={serverStatus === "online" ? "filled" : "outlined"}
            icon={
              serverStatus === "checking" ? (
                <CircularProgress size={14} color="inherit" />
              ) : serverStatus === "online" ? (
                <CheckCircle2 size={16} />
              ) : serverStatus === "degraded" ? (
                <TriangleAlert size={16} />
              ) : (
                <XCircle size={16} />
              )
            }
            label={statusLabel}
            aria-label={statusLabel}
            title={serverStatusDetail}
          />
        </Stack>
      </Stack>
    </Stack>
  );
}

function AdminPanel({
  token,
  onTokenChange,
  onNotice,
  t
}: {
  token: string | null;
  onTokenChange: (token: string | null) => void;
  onNotice: (message: string, severity?: NoticeSeverity) => void;
  t: Translation;
}) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [ipToBlock, setIpToBlock] = useState("");

  const loginMutation = useMutation({
    mutationFn: adminLogin,
    onSuccess: (session) => {
      onTokenChange(session.token);
      setPassword("");
      onNotice(t.admin.loginSuccess, "success");
    },
    onError: (error) => onNotice(errorMessage(error, t), "error")
  });

  const dashboardQuery = useQuery({
    queryKey: ["admin-dashboard", token],
    queryFn: () => getAdminDashboard(token!),
    enabled: Boolean(token),
    refetchInterval: ADMIN_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: true,
    retry: false
  });

  useEffect(() => {
    if (!dashboardQuery.error) {
      return;
    }
    if (dashboardQuery.error instanceof ApiError && dashboardQuery.error.status === 401) {
      onTokenChange(null);
      onNotice(t.admin.sessionExpired, "warning");
      return;
    }
    onNotice(errorMessage(dashboardQuery.error, t), "error");
  }, [dashboardQuery.error, onNotice, onTokenChange, t]);

  const cleanupMutation = useMutation({
    mutationFn: () => cleanupAdminTempFiles(token!),
    onSuccess: (result) => {
      onNotice(t.admin.cleanupDone(result.removedFiles, formatBytes(result.removedBytes)), "success");
      void queryClient.invalidateQueries({ queryKey: ["admin-dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["available-jobs"] });
    },
    onError: (error) => onNotice(errorMessage(error, t), "error")
  });

  const deleteTempMutation = useMutation({
    mutationFn: (jobId: string) => deleteAdminJobTemp(token!, jobId),
    onSuccess: (result) => {
      onNotice(t.admin.cleanupDone(result.removedFiles, formatBytes(result.removedBytes)), "success");
      void queryClient.invalidateQueries({ queryKey: ["admin-dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["available-jobs"] });
    },
    onError: (error) => onNotice(errorMessage(error, t), "error")
  });

  const blockIpMutation = useMutation({
    mutationFn: (ip: string) => blockAdminIp(token!, ip),
    onSuccess: () => {
      setIpToBlock("");
      void queryClient.invalidateQueries({ queryKey: ["admin-dashboard"] });
    },
    onError: (error) => onNotice(errorMessage(error, t), "error")
  });

  const unblockIpMutation = useMutation({
    mutationFn: (ip: string) => unblockAdminIp(token!, ip),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin-dashboard"] });
    },
    onError: (error) => onNotice(errorMessage(error, t), "error")
  });

  function submitLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    loginMutation.mutate(password);
  }

  function submitBlockIp(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedIp = ipToBlock.trim();
    if (!trimmedIp) {
      onNotice(t.admin.enterIp, "warning");
      return;
    }
    blockIpMutation.mutate(trimmedIp);
  }

  if (!token) {
    return (
      <Paper variant="outlined" className="motion-card motion-delay-1 p-4 md:p-5">
        <Stack component="form" onSubmit={submitLogin} spacing={2} className="max-w-md">
          <Stack direction="row" spacing={1.25} alignItems="center">
            <LockKeyhole size={22} className="text-blue-600" />
            <Box>
              <Typography variant="h6" fontWeight={800}>
                {t.admin.title}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t.admin.loginSubtitle}
              </Typography>
            </Box>
          </Stack>
          <TextField
            label={t.admin.password}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            InputProps={{ startAdornment: <KeyRound size={18} className="mr-2 text-blue-500" /> }}
          />
          <Button
            type="submit"
            variant="contained"
            startIcon={loginMutation.isPending ? <CircularProgress size={18} color="inherit" /> : <Shield size={18} />}
            disabled={loginMutation.isPending || !password}
            className="action-button"
          >
            {t.admin.signIn}
          </Button>
        </Stack>
      </Paper>
    );
  }

  const dashboard = dashboardQuery.data;

  return (
    <Stack spacing={3}>
      <Paper variant="outlined" className="motion-card motion-delay-1 p-4 md:p-5">
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", md: "center" }}>
          <Stack direction="row" spacing={1.25} alignItems="center">
            <Shield size={24} className="text-blue-600" />
            <Box>
              <Typography variant="h6" fontWeight={800}>
                {t.admin.title}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {dashboard ? t.admin.updated(formatDateTime(dashboard.serverTime)) : t.admin.loading}
              </Typography>
            </Box>
          </Stack>
          <Stack direction="row" spacing={1}>
            <Button
              variant="outlined"
              color="inherit"
              onClick={() => dashboardQuery.refetch()}
              startIcon={dashboardQuery.isFetching ? <CircularProgress size={16} /> : <RefreshCw size={16} />}
            >
              {t.admin.refresh}
            </Button>
            <Button color="inherit" variant="outlined" onClick={() => onTokenChange(null)}>
              {t.admin.logout}
            </Button>
          </Stack>
        </Stack>
      </Paper>

      {dashboardQuery.isPending && (
        <Paper variant="outlined" className="motion-card p-4 md:p-5">
          <Stack direction="row" spacing={1.5} alignItems="center">
            <CircularProgress size={20} />
            <Typography>{t.admin.loading}</Typography>
          </Stack>
        </Paper>
      )}

      {dashboard && (
        <>
          <AdminStats dashboard={dashboard} t={t} />
          <AdminJobsPanel dashboard={dashboard} t={t} />
          <AdminFilesPanel
            dashboard={dashboard}
            deletingJobId={deleteTempMutation.variables ?? null}
            cleanupPending={cleanupMutation.isPending}
            onDeleteJob={(jobId) => deleteTempMutation.mutate(jobId)}
            onCleanup={() => cleanupMutation.mutate()}
            t={t}
          />
          <AdminTransfersPanel dashboard={dashboard} t={t} />
          <AdminVisitorsPanel
            visitors={dashboard.visitors}
            ipToBlock={ipToBlock}
            blockingIp={blockIpMutation.isPending}
            unblockingIp={unblockIpMutation.variables ?? null}
            onIpChange={setIpToBlock}
            onSubmitBlock={submitBlockIp}
            onBlock={(ip) => blockIpMutation.mutate(ip)}
            onUnblock={(ip) => unblockIpMutation.mutate(ip)}
            t={t}
          />
          <AdminEventsPanel dashboard={dashboard} t={t} />
        </>
      )}
    </Stack>
  );
}

function AdminStats({ dashboard, t }: { dashboard: AdminDashboardResponse; t: Translation }) {
  return (
    <Box className="admin-stat-grid">
      <AdminStat icon={<Activity size={20} />} label={t.admin.stats.activeJobs} value={`${dashboard.activeJobs}/${dashboard.maxActiveJobs}`} />
      <AdminStat icon={<UploadCloud size={20} />} label={t.admin.stats.activeUploads} value={String(dashboard.activeUploads.length)} />
      <AdminStat icon={<Database size={20} />} label={t.admin.stats.tempUsed} value={formatBytes(dashboard.disk.tempBytes)} />
      <AdminStat icon={<HardDrive size={20} />} label={t.admin.stats.diskFree} value={formatBytes(dashboard.disk.freeBytes)} detail={`${dashboard.disk.usagePercent}% ${t.admin.stats.used}`} />
      <AdminStat icon={<UserRound size={20} />} label={t.admin.stats.visitors} value={String(dashboard.visitors.length)} />
      <AdminStat icon={<Ban size={20} />} label={t.admin.stats.blockedIps} value={String(dashboard.blockedIps.length)} />
    </Box>
  );
}

function AdminStat({ icon, label, value, detail }: { icon: React.ReactNode; label: string; value: string; detail?: string }) {
  return (
    <Paper variant="outlined" className="motion-card admin-stat p-3">
      <Stack direction="row" spacing={1.25} alignItems="center">
        <Box className="grid h-9 w-9 shrink-0 place-items-center rounded bg-blue-50 text-blue-600">{icon}</Box>
        <Box className="min-w-0">
          <Typography variant="caption" color="text.secondary">
            {label}
          </Typography>
          <Typography variant="subtitle1" fontWeight={800} className="break-words">
            {value}
          </Typography>
          {detail && (
            <Typography variant="caption" color="text.secondary">
              {detail}
            </Typography>
          )}
        </Box>
      </Stack>
    </Paper>
  );
}

function AdminJobsPanel({ dashboard, t }: { dashboard: AdminDashboardResponse; t: Translation }) {
  const currentRows = dashboard.currentJobs.slice(0, 20);
  const historyRows = dashboard.jobHistory.slice(0, 30);

  return (
    <Paper variant="outlined" className="motion-card p-4 md:p-5">
      <Stack spacing={2}>
        <PanelTitle icon={<History size={20} />} title={t.admin.jobs.title} subtitle={t.admin.jobs.subtitle} />
        <AdminJobTable title={t.admin.jobs.current} jobs={currentRows} emptyText={t.admin.empty.currentJobs} t={t} />
        <Divider />
        <AdminJobTable title={t.admin.jobs.history} jobs={historyRows} emptyText={t.admin.empty.jobHistory} t={t} />
      </Stack>
    </Paper>
  );
}

function AdminJobTable({ title, jobs, emptyText, t }: { title: string; jobs: JobStatusResponse[]; emptyText: string; t: Translation }) {
  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2" fontWeight={800}>
        {title}
      </Typography>
      {jobs.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {emptyText}
        </Typography>
      ) : (
        <TableContainer className="rounded border border-blue-100">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t.admin.jobs.job}</TableCell>
                <TableCell>{t.admin.jobs.status}</TableCell>
                <TableCell>{t.admin.jobs.progress}</TableCell>
                <TableCell>{t.admin.jobs.updated}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {jobs.map((job) => (
                <TableRow key={`${title}-${job.jobId}`} hover className="animated-row">
                  <TableCell>
                    <Typography variant="body2" fontWeight={800}>
                      {shortId(job.jobId)}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" className="line-clamp-2">
                      {job.currentItem || job.message || "-"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip size="small" color={adminStatusColor(job.status)} variant="outlined" label={statusLabel(job.status, t)} />
                  </TableCell>
                  <TableCell>{Math.round(job.progress)}%</TableCell>
                  <TableCell>{formatDateTime(job.updatedAt)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Stack>
  );
}

function AdminFilesPanel({
  dashboard,
  deletingJobId,
  cleanupPending,
  onDeleteJob,
  onCleanup,
  t
}: {
  dashboard: AdminDashboardResponse;
  deletingJobId: string | null;
  cleanupPending: boolean;
  onDeleteJob: (jobId: string) => void;
  onCleanup: () => void;
  t: Translation;
}) {
  return (
    <Paper variant="outlined" className="motion-card p-4 md:p-5">
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
          <PanelTitle icon={<HardDrive size={20} />} title={t.admin.files.title} subtitle={dashboard.disk.tempRoot} />
          <Button
            color="error"
            variant="outlined"
            onClick={onCleanup}
            disabled={cleanupPending}
            startIcon={cleanupPending ? <CircularProgress size={16} /> : <Trash2 size={16} />}
          >
            {t.admin.files.deleteTemp}
          </Button>
        </Stack>
        <AdminFileTable
          title={t.admin.files.available}
          files={dashboard.availableFiles.slice(0, 20)}
          deletingJobId={deletingJobId}
          onDeleteJob={onDeleteJob}
          emptyText={t.admin.empty.files}
          t={t}
          showDownload
        />
        <Divider />
        <AdminFileTable
          title={t.admin.files.temp}
          files={dashboard.tempFiles.slice(0, 50)}
          deletingJobId={deletingJobId}
          onDeleteJob={onDeleteJob}
          emptyText={t.admin.empty.tempFiles}
          t={t}
        />
      </Stack>
    </Paper>
  );
}

function AdminFileTable({
  title,
  files,
  deletingJobId,
  onDeleteJob,
  emptyText,
  showDownload = false,
  t
}: {
  title: string;
  files: AdminFileResponse[];
  deletingJobId: string | null;
  onDeleteJob: (jobId: string) => void;
  emptyText: string;
  showDownload?: boolean;
  t: Translation;
}) {
  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2" fontWeight={800}>
        {title}
      </Typography>
      {files.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {emptyText}
        </Typography>
      ) : (
        <TableContainer className="rounded border border-blue-100">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t.admin.files.file}</TableCell>
                <TableCell>{t.admin.files.size}</TableCell>
                <TableCell>{t.admin.files.modified}</TableCell>
                <TableCell align="right">{t.admin.files.actions}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {files.map((file) => (
                <TableRow key={`${title}-${file.relativePath}`} hover className="animated-row">
                  <TableCell>
                    <Typography variant="body2" fontWeight={800} className="break-words">
                      {file.name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" className="break-words">
                      {file.relativePath}
                    </Typography>
                  </TableCell>
                  <TableCell>{formatBytes(file.sizeBytes)}</TableCell>
                  <TableCell>{formatDateTime(file.modifiedAt)}</TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={1} justifyContent="flex-end">
                      {showDownload && file.downloadUrl && (
                        <Button component="a" href={adminFileDownloadUrl(file.downloadUrl)} size="small" variant="contained" startIcon={<Download size={16} />}>
                          {t.downloads.download}
                        </Button>
                      )}
                      {file.jobId && (
                        <Button
                          size="small"
                          color="error"
                          variant="outlined"
                          onClick={() => onDeleteJob(file.jobId!)}
                          disabled={!file.deletable || deletingJobId === file.jobId}
                          startIcon={deletingJobId === file.jobId ? <CircularProgress size={16} /> : <Trash2 size={16} />}
                        >
                          {t.admin.files.delete}
                        </Button>
                      )}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Stack>
  );
}

function AdminTransfersPanel({ dashboard, t }: { dashboard: AdminDashboardResponse; t: Translation }) {
  return (
    <Paper variant="outlined" className="motion-card p-4 md:p-5">
      <Stack spacing={2}>
        <PanelTitle icon={<UploadCloud size={20} />} title={t.admin.uploads.title} subtitle={t.admin.uploads.subtitle} />
        <AdminTransferTable title={t.admin.uploads.active} transfers={dashboard.activeUploads} emptyText={t.admin.empty.activeUploads} t={t} />
        <Divider />
        <AdminTransferTable title={t.admin.uploads.history} transfers={dashboard.uploadHistory.slice(0, 30)} emptyText={t.admin.empty.uploadHistory} t={t} />
      </Stack>
    </Paper>
  );
}

function AdminTransferTable({ title, transfers, emptyText, t }: { title: string; transfers: AdminTransferResponse[]; emptyText: string; t: Translation }) {
  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2" fontWeight={800}>
        {title}
      </Typography>
      {transfers.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {emptyText}
        </Typography>
      ) : (
        <TableContainer className="rounded border border-blue-100">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t.admin.uploads.file}</TableCell>
                <TableCell>{t.admin.uploads.ip}</TableCell>
                <TableCell>{t.admin.uploads.size}</TableCell>
                <TableCell>{t.admin.uploads.time}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {transfers.map((transfer) => (
                <TableRow key={transfer.transferId} hover className="animated-row">
                  <TableCell>
                    <Typography variant="body2" fontWeight={800} className="break-words">
                      {transfer.fileName}
                    </Typography>
                    <Chip size="small" variant="outlined" label={transfer.status} />
                  </TableCell>
                  <TableCell>{transfer.ip}</TableCell>
                  <TableCell>{formatBytes(transfer.sizeBytes)}</TableCell>
                  <TableCell>{formatDateTime(transfer.completedAt ?? transfer.startedAt)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Stack>
  );
}

function AdminVisitorsPanel({
  visitors,
  ipToBlock,
  blockingIp,
  unblockingIp,
  onIpChange,
  onSubmitBlock,
  onBlock,
  onUnblock,
  t
}: {
  visitors: AdminVisitorResponse[];
  ipToBlock: string;
  blockingIp: boolean;
  unblockingIp: string | null;
  onIpChange: (value: string) => void;
  onSubmitBlock: (event: React.FormEvent<HTMLFormElement>) => void;
  onBlock: (ip: string) => void;
  onUnblock: (ip: string) => void;
  t: Translation;
}) {
  return (
    <Paper variant="outlined" className="motion-card p-4 md:p-5">
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", md: "center" }}>
          <PanelTitle icon={<UserRound size={20} />} title={t.admin.visitors.title} subtitle={t.admin.visitors.subtitle} />
          <Stack component="form" onSubmit={onSubmitBlock} direction={{ xs: "column", sm: "row" }} spacing={1}>
            <TextField size="small" label={t.admin.visitors.ip} value={ipToBlock} onChange={(event) => onIpChange(event.target.value)} />
            <Button type="submit" color="error" variant="outlined" disabled={blockingIp} startIcon={blockingIp ? <CircularProgress size={16} /> : <Ban size={16} />}>
              {t.admin.visitors.block}
            </Button>
          </Stack>
        </Stack>
        {visitors.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t.admin.empty.visitors}
          </Typography>
        ) : (
          <TableContainer className="rounded border border-blue-100">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t.admin.visitors.ip}</TableCell>
                  <TableCell>{t.admin.visitors.lastSeen}</TableCell>
                  <TableCell>{t.admin.visitors.requests}</TableCell>
                  <TableCell>{t.admin.visitors.lastPath}</TableCell>
                  <TableCell align="right">{t.admin.files.actions}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visitors.map((visitor) => (
                  <TableRow key={visitor.ip} hover className="animated-row">
                    <TableCell>
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                        <Typography variant="body2" fontWeight={800}>
                          {visitor.ip}
                        </Typography>
                        {visitor.blocked && <Chip size="small" color="error" variant="outlined" label={t.admin.visitors.blocked} />}
                      </Stack>
                      <Typography variant="caption" color="text.secondary" className="line-clamp-2">
                        {visitor.userAgent || "-"}
                      </Typography>
                    </TableCell>
                    <TableCell>{formatDateTime(visitor.lastSeen)}</TableCell>
                    <TableCell>{visitor.requestCount}</TableCell>
                    <TableCell>
                      <Typography variant="caption" className="break-words">
                        {visitor.lastPath || "-"}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      {visitor.blocked ? (
                        <Button size="small" color="inherit" variant="outlined" onClick={() => onUnblock(visitor.ip)} disabled={unblockingIp === visitor.ip}>
                          {t.admin.visitors.unblock}
                        </Button>
                      ) : (
                        <Button size="small" color="error" variant="outlined" onClick={() => onBlock(visitor.ip)}>
                          {t.admin.visitors.block}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Stack>
    </Paper>
  );
}

function AdminEventsPanel({ dashboard, t }: { dashboard: AdminDashboardResponse; t: Translation }) {
  return (
    <Paper variant="outlined" className="motion-card p-4 md:p-5">
      <Stack spacing={2}>
        <PanelTitle icon={<Activity size={20} />} title={t.admin.events.title} subtitle={t.admin.events.subtitle} />
        {dashboard.events.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t.admin.empty.events}
          </Typography>
        ) : (
          <TableContainer className="rounded border border-blue-100">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t.admin.events.time}</TableCell>
                  <TableCell>{t.admin.events.category}</TableCell>
                  <TableCell>{t.admin.events.message}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {dashboard.events.slice(0, 40).map((event) => (
                  <TableRow key={event.eventId} hover className="animated-row">
                    <TableCell>{formatDateTime(event.createdAt)}</TableCell>
                    <TableCell>
                      <Chip size="small" variant="outlined" label={event.category} />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" className="break-words">
                        {event.message}
                      </Typography>
                      {(event.ip || event.jobId) && (
                        <Typography variant="caption" color="text.secondary">
                          {[event.ip, event.jobId ? shortId(event.jobId) : null].filter(Boolean).join(" / ")}
                        </Typography>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Stack>
    </Paper>
  );
}

function PanelTitle({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <Stack direction="row" spacing={1.25} alignItems="center" className="min-w-0">
      <Box className="grid h-9 w-9 shrink-0 place-items-center rounded bg-blue-50 text-blue-600">{icon}</Box>
      <Box className="min-w-0">
        <Typography variant="h6" fontWeight={800}>
          {title}
        </Typography>
        {subtitle && (
          <Typography variant="body2" color="text.secondary" className="break-words">
            {subtitle}
          </Typography>
        )}
      </Box>
    </Stack>
  );
}

interface PreviewPanelProps {
  preview: PreviewResponse;
  selectedIds: string[];
  onToggle: (entryId: string) => void;
  onSelectAll: () => void;
  onClear: () => void;
  t: Translation;
}

function PreviewPanel({ preview, selectedIds, onToggle, onSelectAll, onClear, t }: PreviewPanelProps) {
  const isPlaylist = preview.kind === "playlist";

  return (
    <Stack spacing={2} className="preview-motion">
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <Thumbnail src={preview.thumbnail} title={preview.title} />
        <Stack spacing={1} className="min-w-0 flex-1">
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Chip size="small" color={isPlaylist ? "secondary" : "primary"} label={isPlaylist ? t.mediaKind.playlist : t.mediaKind.video} />
            {preview.duration ? <Chip size="small" variant="outlined" label={formatDuration(preview.duration)} /> : null}
            {isPlaylist ? <Chip size="small" variant="outlined" label={t.entries.count(preview.entries.length)} /> : null}
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
              {t.entries.selectFirst(Math.min(MAX_SELECTED_ITEMS, preview.entries.length))}
            </Button>
            <Button size="small" color="inherit" onClick={onClear}>
              {t.entries.clear}
            </Button>
            <Typography variant="body2" color="text.secondary" className="ml-auto">
              {t.entries.selected(selectedIds.length)}
            </Typography>
          </Stack>

          <TableContainer className="max-h-[460px] rounded border border-blue-100">
            <Table stickyHeader size="small" aria-label={t.entries.tableAria}>
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox" />
                  <TableCell>{t.entries.title}</TableCell>
                  <TableCell width={110}>{t.entries.duration}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {preview.entries.map((entry) => (
                  <PlaylistRow key={`${entry.id}-${entry.index}`} entry={entry} checked={selectedIds.includes(entry.id)} onToggle={onToggle} t={t} />
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}
    </Stack>
  );
}

function PlaylistRow({
  entry,
  checked,
  onToggle,
  t
}: {
  entry: PreviewEntry;
  checked: boolean;
  onToggle: (entryId: string) => void;
  t: Translation;
}) {
  return (
    <TableRow hover selected={checked} className="animated-row">
      <TableCell padding="checkbox">
        <Checkbox checked={checked} onChange={() => onToggle(entry.id)} inputProps={{ "aria-label": t.entries.selectEntry(entry.title) }} />
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
    <Box className={`thumbnail-frame ${classes} shrink-0 overflow-hidden rounded bg-blue-50`}>
      {src ? (
        <img src={src} alt={title} className="thumbnail-image h-full w-full object-cover" loading="lazy" />
      ) : (
        <Box className="grid h-full w-full place-items-center text-blue-500">
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
  onQualityChange,
  t
}: {
  kind: MediaKind;
  quality: string;
  onKindChange: (kind: MediaKind | null) => void;
  onQualityChange: (quality: string) => void;
  t: Translation;
}) {
  const options = useMemo(() => qualityOptions[kind], [kind]);

  return (
    <Stack spacing={2}>
      <FormControl>
        <FormLabel className="mb-2">{t.controls.format}</FormLabel>
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
        <FormLabel className="mb-2">{t.controls.quality}</FormLabel>
        <Select value={quality} onChange={(event) => onQualityChange(event.target.value)}>
          {options.map((option) => (
            <MenuItem key={option} value={option}>
              {qualityLabel(kind, option, t)}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Stack>
  );
}

function AvailableDownloadsPanel({
  jobs,
  t
}: {
  jobs: JobStatusResponse[];
  t: Translation;
}) {
  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
        <Box>
          <Typography variant="h6" fontWeight={800}>
            {t.downloads.available}
          </Typography>
        </Box>
        <Chip size="small" label={t.downloads.readyCount(jobs.length)} />
      </Stack>

      <TableContainer className="rounded border border-blue-100">
        <Table size="small" aria-label={t.downloads.tableAria}>
          <TableHead>
            <TableRow>
              <TableCell>{t.downloads.title}</TableCell>
              <TableCell width={130}>{t.controls.quality}</TableCell>
              <TableCell width={190}>{t.downloads.expires}</TableCell>
              <TableCell align="right" width={130}>
                {t.downloads.actions}
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {jobs.map((availableJob) => (
              <TableRow key={availableJob.jobId} hover className="animated-row">
                <TableCell>
                  <Stack spacing={0.25}>
                    <Typography variant="body2" fontWeight={800} className="break-words">
                      {availableJob.mediaTitle || (availableJob.isArchive ? t.downloads.playlistArchive : t.downloads.mediaFile)}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {downloadFileTypeLabel(availableJob, t)}
                    </Typography>
                  </Stack>
                </TableCell>
                <TableCell>{downloadQualityLabel(availableJob, t)}</TableCell>
                <TableCell>{availableJob.expiresAt ? formatDateTime(availableJob.expiresAt) : "-"}</TableCell>
                <TableCell align="right">
                  <Stack direction="row" spacing={1} justifyContent="flex-end">
                    <Button component="a" href={downloadUrl(availableJob.jobId)} size="small" variant="contained" startIcon={<Download size={16} />}>
                      {t.downloads.download}
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

function ProgressPanel({ job, onCancel, cancelling, t }: { job: JobStatusResponse; onCancel: () => void; cancelling: boolean; t: Translation }) {
  const terminal = isTerminalJobStatus(job.status);
  const color = job.status === "failed" ? "error" : job.status === "ready" ? "success" : "primary";
  const statusMessage = job.message ? localizeBackendMessage(job.message, t) : job.currentItem ?? t.progress.working;
  const progressClass = terminal ? "progress-bar progress-bar-static h-2 rounded" : "progress-bar progress-bar-active h-2 rounded";

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", md: "center" }}>
        <Stack direction="row" spacing={1} alignItems="center">
          {job.status === "ready" ? <CheckCircle2 size={22} className="text-green-700" /> : job.status === "failed" ? <XCircle size={22} className="text-red-700" /> : <PackageCheck size={22} className="text-blue-600" />}
          <Box>
            <Typography variant="subtitle1" fontWeight={800}>
              {statusLabel(job.status, t)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {statusMessage}
            </Typography>
          </Box>
        </Stack>

        <Stack direction="row" spacing={1}>
          {!terminal && (
            <Button color="inherit" variant="outlined" onClick={onCancel} disabled={cancelling} startIcon={<XCircle size={18} />}>
              {t.progress.cancel}
            </Button>
          )}
          {job.status === "ready" && (
            <Button component="a" href={downloadUrl(job.jobId)} variant="contained" startIcon={<Download size={18} />}>
              {t.downloads.downloadReady(job.isArchive)}
            </Button>
          )}
        </Stack>
      </Stack>

      <Box>
        <LinearProgress variant="determinate" value={job.progress} color={color} className={progressClass} />
        <Stack direction="row" justifyContent="space-between" className="mt-1">
          <Typography variant="caption" color="text.secondary">
            {t.progress.done(job.completedItems, job.totalItems || 1)}
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

      {job.error && <Alert severity="error">{localizeBackendError(job.error, t)}</Alert>}
    </Stack>
  );
}

function errorMessage(error: unknown, t: Translation): string {
  if (error instanceof ApiError) {
    return localizeBackendError(error.message, t);
  }
  if (error instanceof Error) {
    return localizeBackendError(error.message, t);
  }
  return t.somethingWentWrong;
}

function progressCardClass(status: JobStatusResponse["status"]): string {
  if (status === "ready") {
    return "progress-card-ready";
  }
  if (status === "failed") {
    return "progress-card-failed";
  }
  if (status === "cancelled") {
    return "progress-card-cancelled";
  }
  return "progress-card-active";
}

function localizeBackendMessage(message: string, t: Translation): string {
  const exactMessages: Record<string, string> = {
    Queued: t.backendMessages.queued,
    "Reading media information": t.backendMessages.readingMedia,
    "Starting download": t.backendMessages.startingDownload,
    "Converting or merging media": t.backendMessages.converting,
    "Creating ZIP archive": t.backendMessages.creatingArchive,
    "Ready to download": t.backendMessages.readyToDownload,
    Cancelled: t.backendMessages.cancelled,
    Cancelling: t.backendMessages.cancelling,
    "Download failed": t.backendMessages.downloadFailed
  };
  if (exactMessages[message]) {
    return exactMessages[message];
  }

  const progressMatch = message.match(/^Downloading (\d+) of (\d+)(?: - (.*))?$/);
  if (progressMatch) {
    const [, current, total, detail] = progressMatch;
    const translated = t.backendMessages.downloadingOf(Number(current), Number(total));
    if (!detail) {
      return translated;
    }
    return `${translated} - ${localizeProgressDetail(detail, t)}`;
  }

  return message;
}

function localizeProgressDetail(detail: string, t: Translation): string {
  return detail
    .split(" - ")
    .map((part) => {
      const etaMatch = part.match(/^ETA\s+(.+)$/);
      return etaMatch ? t.backendMessages.eta(etaMatch[1]) : part;
    })
    .join(" - ");
}

function localizeBackendError(message: string, t: Translation): string {
  const exactErrors: Record<string, string> = {
    "Request failed.": t.requestFailed,
    "Confirm that you have the right to download this media.": t.backendErrors.confirmRights,
    "Job not found.": t.backendErrors.jobNotFound,
    "Download is not ready yet.": t.backendErrors.downloadNotReady,
    "The temporary file is no longer available.": t.backendErrors.temporaryFileMissing,
    "Enter a valid YouTube URL.": t.backendErrors.invalidYouTubeUrl,
    "Enter a YouTube video or playlist URL.": t.backendErrors.videoOrPlaylistUrl,
    "This item is longer than the configured duration limit.": t.backendErrors.durationLimit,
    "Could not read media information.": t.backendErrors.couldNotReadMedia,
    "This link does not contain downloadable videos. Paste a YouTube video or playlist URL.": t.backendErrors.notDownloadableList,
    "This link does not contain downloadable videos.": t.backendErrors.notDownloadableList,
    "This link is not a downloadable YouTube video or playlist.": t.backendErrors.notDownloadableLink,
    "This link is not a downloadable YouTube video.": t.backendErrors.notDownloadableLink,
    "No selected playlist items were found.": t.backendErrors.noSelectedItems,
    "Another download is already running.": t.backendErrors.anotherDownloadRunning,
    "YouTube asked for sign-in/bot verification. Configure APP_YTDLP_COOKIE_FILE with exported browser cookies, or APP_YTDLP_COOKIES_FROM_BROWSER where available, then retry.":
      t.backendErrors.botVerification
  };
  if (exactErrors[message]) {
    return exactErrors[message];
  }

  const unsupportedMatch = message.match(/^Unsupported ([A-Z0-9]+) quality\. Choose one of: (.+)\.$/);
  if (unsupportedMatch) {
    return t.backendErrors.unsupportedQuality(unsupportedMatch[1], unsupportedMatch[2]);
  }

  const playlistLimitMatch = message.match(/^Select at most (\d+) playlist items\.$/);
  if (playlistLimitMatch) {
    return t.selectAtMost(Number(playlistLimitMatch[1]));
  }

  return message;
}

function localizeHealthMessage(message: string, t: Translation): string {
  const exactMessages: Record<string, string> = {
    "Temp root is writable": t.healthMessages.tempRootWritable,
    "Redis check disabled": t.healthMessages.redisDisabled,
    "Redis package is not installed": t.healthMessages.redisPackageMissing,
    "Redis ping succeeded": t.healthMessages.redisPingSucceeded
  };
  if (exactMessages[message]) {
    return exactMessages[message];
  }

  if (message.startsWith("Temp root is not writable:")) {
    return message.replace("Temp root is not writable", t.healthMessages.tempRootNotWritable);
  }
  if (message.startsWith("Redis is not reachable:")) {
    return message.replace("Redis is not reachable", t.healthMessages.redisNotReachable);
  }
  return message;
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
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Tallinn",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  }).formatToParts(new Date(value));
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.day}.${byType.month}.${byType.year}, ${byType.hour}:${byType.minute}`;
}

function downloadFileTypeLabel(job: JobStatusResponse, t: Translation): string {
  if (job.isArchive) {
    return t.downloads.playlistZipFile;
  }
  return t.downloads.mediaFileType(job.mediaKind.toUpperCase());
}

function downloadQualityLabel(job: JobStatusResponse, t: Translation): string {
  if (job.quality !== "best") {
    return job.quality;
  }
  return job.mediaKind === "mp3" ? "320k" : t.downloads.highestAvailable;
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  return `${value >= 10 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`;
}

function shortId(value: string): string {
  return value.length > 10 ? value.slice(0, 10) : value;
}

function adminStatusColor(status: JobStatusResponse["status"]): "default" | "primary" | "success" | "warning" | "error" {
  if (status === "ready") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  if (status === "cancelled") {
    return "warning";
  }
  if (status === "queued") {
    return "default";
  }
  return "primary";
}

function isTerminalJobStatus(status?: JobStatusResponse["status"] | null): boolean {
  return Boolean(status && TERMINAL_JOB_STATUSES.has(status));
}

function statusLabel(status: JobStatusResponse["status"], t: Translation): string {
  return t.jobStatus[status];
}

function qualityLabel(kind: MediaKind, quality: string, t: Translation): string {
  if (quality === "best") {
    return t.controls.qualityBest[kind];
  }
  return quality;
}

export default App;
