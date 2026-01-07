import os
import subprocess
import sys
import requests
import json
import re

# ==============================
# CONFIGURATION
# ==============================

STATION_ID = "2"
API_KEY = "25caf2bc8383d480:3c911d2dff69a0f70c7d9b7841e3c1d4"
PLAYLIST_URL = "https://music.youtube.com/playlist?list=PLq0zpvHX8lQrhRG4qYCPC0ywFo_UhU_F8"
DOWNLOAD_DIR = "Downloaded"

AZURACAST_API = (
    f"https://radio.maksimtsikvasvili24.thkit.ee/api/station/{STATION_ID}/files"
)

YTDLP_BASE_CMD = [
    "yt-dlp",
    "-f",
    "bestaudio/best",
    "-x",
    "--audio-format",
    "mp3",
    "--embed-metadata",
    "--embed-thumbnail",
    "--convert-thumbnails",
    "jpg",
    "--parse-metadata",
    "%(uploader)s:%(artist)s",
    "-o",
    "%(title)s.%(ext)s",
]

# ==============================
# HELPERS
# ==============================


def normalize(value: str) -> str:
    return (value or "").strip().lower()


def first_two_words(title: str) -> str:
    parts = title.split()
    return " ".join(parts[:2]) if len(parts) >= 2 else title


def has_parentheses(title: str) -> bool:
    return bool(re.search(r"\(.*?\)", title))


def log(msg: str):
    print(msg, flush=True)


# ==============================
# SETUP
# ==============================

log("\n=== AzuraCast Playlist Downloader (Python) ===\n")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
log(f"[INFO] Download folder: {DOWNLOAD_DIR}")

# ==============================
# FETCH EXISTING FILES
# ==============================

log("[INFO] Fetching existing station files...")

headers = {"Authorization": f"Bearer {API_KEY}"}

response = requests.get(AZURACAST_API, headers=headers, timeout=30)

if response.status_code != 200:
    log("[ERROR] Failed to fetch AzuraCast API")
    sys.exit(1)

existing_files = response.json()

existing_songs = [
    {
        "artist": normalize(f.get("artist")),
        "title": normalize(f.get("title")),
        "title_2w": first_two_words(normalize(f.get("title"))),
    }
    for f in existing_files
]

log(f"[INFO] Found {len(existing_songs)} existing songs.\n")

# ==============================
# FETCH PLAYLIST METADATA
# ==============================

log("[INFO] Fetching playlist metadata using yt-dlp...")

playlist_process = subprocess.run(
    ["yt-dlp", "--flat-playlist", "--dump-single-json", PLAYLIST_URL],
    capture_output=True,
    text=True,
)

if playlist_process.returncode != 0:
    log("[ERROR] yt-dlp failed to fetch playlist")
    sys.exit(1)

playlist_json = json.loads(playlist_process.stdout)
entries = playlist_json.get("entries", [])

log(f"[INFO] Playlist contains {len(entries)} tracks.\n")

# ==============================
# FILTER TRACKS
# ==============================

to_download = []

for track in entries:
    title = normalize(track.get("title"))
    artist = normalize(track.get("uploader"))
    title_2w = first_two_words(title)

    # 1. Exact artist + title match
    if any(
        s["title"] == title and s["artist"] == artist for s in existing_songs
    ):
        log(f"[SKIP] Exact match found: {artist} - {title}")
        continue

    # 2. Exact title match
    exact_title_matches = [
        s for s in existing_songs if s["title"] == title
    ]

    if exact_title_matches:
        log("\n[WARNING] Exact title duplicate found:")
        log(f"  Playlist: {artist} - {title}")
        log(
            "  Existing artist(s): "
            + ", ".join({s['artist'] for s in exact_title_matches})
        )

        choice = input("Add to queue anyway? (y/n): ").strip().lower()
        if choice != "y":
            log("[SKIP] Skipped by user.")
            continue

    # 3. First two words match
    two_word_matches = [
        s for s in existing_songs if s["title_2w"] == title_2w
    ]

    if two_word_matches:
        log("\n[WARNING] First 2 title words match:")
        log(f"  Playlist: {artist} - {title}")
        log(
            "  Existing titles: "
            + ", ".join({s['title'] for s in two_word_matches})
        )

        choice = input("Add to queue anyway? (y/n): ").strip().lower()
        if choice != "y":
            log("[SKIP] Skipped by user.")
            continue

    # 4. Parentheses detection (remix, feat, edit, etc.)
    if has_parentheses(title):
        log("\n[WARNING] Title contains parentheses:")
        log(f"  Playlist: {artist} - {title}")

        choice = input("Add to queue anyway? (y/n): ").strip().lower()
        if choice != "y":
            log("[SKIP] Skipped by user.")
            continue

    to_download.append(track)
    log(f"[QUEUE] Added: {artist} - {title}")

# ==============================
# DOWNLOAD
# ==============================

log("\n=== DOWNLOAD START ===")
log(f"Tracks to download: {len(to_download)}\n")

os.chdir(DOWNLOAD_DIR)

for track in to_download:
    url = track.get("url")
    log(f"[DOWNLOADING] {track.get('uploader')} - {track.get('title')}")

    subprocess.run(
        YTDLP_BASE_CMD + [url],
        check=False,
    )

log("\n=== DONE ===")
log(f"Downloaded {len(to_download)} track(s).")