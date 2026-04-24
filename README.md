# SBARadioYTDLP

Local Docker Compose app for downloading YouTube videos or playlists through a React UI and a FastAPI backend powered by `yt-dlp`.

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

Useful settings:

- `APP_MAX_PLAYLIST_ITEMS`: maximum selected playlist entries per job.
- `APP_MAX_DURATION_SECONDS`: maximum duration for one item.
- `APP_MAX_ACTIVE_JOBS`: active background jobs allowed at once.
- `APP_CLEANUP_AFTER_SECONDS`: how long completed temp files stay available.

## Development Notes

This is a local-first tool. V1 does not include accounts or hosted multi-user protections. It does include URL validation, playlist size limits, duration limits, one active job by default, isolated temp folders, filename sanitization, cancellation, and cleanup.
