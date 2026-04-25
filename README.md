# SBARadioYTDLP

Local Docker Compose app for downloading YouTube videos or playlists through a React UI and a FastAPI backend powered by `yt-dlp`. The frontend can also be deployed to Vercel and pointed at a separately hosted backend.

## Requirements

- Docker Desktop with WSL integration enabled.
- Enough disk space for temporary media files.

The backend image installs `ffmpeg` and `ffprobe` automatically.

## Run

```bash
docker compose up --build
```

Open:

```text
http://localhost:5173
```

The frontend proxies `/api` and WebSocket progress traffic to the backend container.

## Features

- Validate YouTube video and playlist URLs before previewing.
- Preview single videos and playlists.
- Select playlist entries.
- Choose MP4 or MP3 and quality.
- Track job progress while media downloads and converts.
- Refresh the page and return to the active or completed download while the backend job is still available.
- Show all completed downloads that still have temp files available.
- Download a finished video/audio file or a ZIP archive for playlist selections.
- Temporary files are isolated per job and cleaned after the configured TTL.

## Configuration

Copy `.env.example` to `.env` if you want to change ports or limits.

```bash
cp .env.example .env
```

Service-specific examples are available for hosted deployments:

- `backend/.env.example`: backend and Portainer stack variables.
- `frontend/.env.example`: Vercel/Vite frontend variables.

Useful settings:

- `APP_MAX_PLAYLIST_ITEMS`: maximum selected playlist entries per job.
- `APP_MAX_DURATION_SECONDS`: maximum duration for one item.
- `APP_MAX_ACTIVE_JOBS`: active background jobs allowed at once.
- `APP_CLEANUP_AFTER_SECONDS`: how long completed temp files stay available.

## Deploy the Frontend to Vercel

This repository includes a `vercel.json` for deploying the Vite frontend from the `frontend/` root directory.

1. Deploy the FastAPI backend somewhere that supports long-running processes, local temp files, `ffmpeg`, and WebSockets, such as a VPS, Fly.io, Railway, Render, or another container host.
2. In the backend environment, set `APP_ALLOWED_ORIGINS` to your Vercel site origin:

```bash
APP_ALLOWED_ORIGINS=https://your-project.vercel.app
```

3. In the Vercel project settings, add the values from `frontend/.env.example`:

```bash
VITE_API_BASE=https://your-backend.example.com/api
VITE_ENABLE_JOB_EVENTS=true
```

Set `VITE_ENABLE_JOB_EVENTS=false` if your backend host or proxy does not pass WebSocket traffic. The UI will continue polling job status.

4. Import the repository into Vercel and set the project **Root Directory** to `frontend`. The checked-in `vercel.json` handles install, build, and output directory settings for that root.

The downloader API is intentionally not configured as a Vercel Function. Vercel can run FastAPI, but this backend downloads and converts media, keeps in-memory job state, serves generated files, and streams progress over WebSockets. Those requirements do not fit Vercel Functions well because of function duration limits, response size limits, and realtime connection constraints.

## Deploy the Backend with Portainer

Use `docker-compose.portainer.yml` when deploying the backend to a server through Portainer. It runs only the FastAPI downloader plus Caddy for HTTPS.

If you do not have a domain yet, `api.143.198.60.223.sslip.io` resolves to `143.198.60.223` and can be used as a temporary HTTPS hostname.

In Portainer, create a stack from this Git repository and set the values from `backend/.env.example`:

```bash
Compose path: docker-compose.portainer.yml
BACKEND_HOSTNAME=api.143.198.60.223.sslip.io
APP_ALLOWED_ORIGINS=https://your-vercel-project.vercel.app
```

Make sure ports `80` and `443` are open on the server firewall. After the stack starts, check:

```bash
https://api.143.198.60.223.sslip.io/api/health
```

Then set this in Vercel:

```bash
VITE_API_BASE=https://api.143.198.60.223.sslip.io/api
VITE_ENABLE_JOB_EVENTS=true
```

## Development Notes

This is a local-first tool. V1 does not include accounts or hosted multi-user protections. It does include URL validation, playlist size limits, duration limits, one active job by default, isolated temp folders, filename sanitization, cancellation, and cleanup.
