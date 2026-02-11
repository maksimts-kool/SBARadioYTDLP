import os
import subprocess
import requests
import json
import re
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)

# ==============================
# CONFIGURATION
# ==============================
DEFAULT_CONFIG = {
    "STATION_ID": "2",
    "API_KEY": "25caf2bc8383d480:3c911d2dff69a0f70c7d9b7841e3c1d4",
    "PLAYLIST_URL": "https://music.youtube.com/playlist?list=PLq0zpvHX8lQrhRG4qYCPC0ywFo_UhU_F8",
    "DOWNLOAD_DIR": "Downloaded"
}

# ==============================
# HELPERS
# ==============================

def normalize(value: str) -> str:
    return (value or "").strip().lower()

def clean_for_ffmpeg(text: str) -> str:
    if not text: return ""
    return text.replace('"', "'").replace('\\', '')

def clean_junk(text: str) -> str:
    if not text: return ""
    junk_keywords = (
        "official|video|audio|lyric|visualizer|hq|hd|clean|music|version|4k|1080p|"
        "clip|performance|live|remastered|extended|radio edit|explicit|visual"
    )
    text = re.sub(r'(?i)\s*[\[\(].*?(' + junk_keywords + r').*?[\]\)]', '', text)
    text = re.sub(r'#\S+', '', text)
    text = re.sub(r'(?i)\s+(official|video|audio|lyric|lyrics|music|clean)+$', '', text)
    return text.strip()

def smart_parse(raw_title: str, raw_uploader: str):
    """Smartly detects Artist/Title based on channel type and title structure."""
    clean_full_title = clean_junk(raw_title)
    
    # 1. Clean uploader and detect if it's an official Topic/VEVO channel
    is_official = False
    clean_uploader = "Unknown Artist"
    if raw_uploader and raw_uploader != "NA":
        if re.search(r"(?i)\s*-\s*Topic$|VEVO$", raw_uploader):
            is_official = True
        clean_uploader = re.sub(r"(?i)\s*-\s*Topic$", "", raw_uploader)
        clean_uploader = re.sub(r"(?i)\s*VEVO$", "", clean_uploader).strip()

    # Pattern for separator: hyphen with at least one space on either side
    separator_pattern = r'\s+[-–—]\s+'
    
    final_artist = ""
    final_title = ""

    if re.search(separator_pattern, clean_full_title):
        parts = re.split(separator_pattern, clean_full_title)
        
        # Case A: Title starts with the uploader name (e.g. "Artist - Song")
        if normalize(parts[0]) == normalize(clean_uploader):
            final_artist = parts[0]
            final_title = " - ".join(parts[1:])
        
        # Case B: It's an official channel but title has a hyphen (e.g. "Song - Part 2")
        # Here we trust the uploader name as the artist
        elif is_official:
            final_artist = clean_uploader
            final_title = clean_full_title
            
        # Case C: Generic split for non-official channels
        elif len(parts) >= 2:
            final_artist = parts[0]
            final_title = " - ".join(parts[1:])
    else:
        # No separator found: Full title is song name, uploader is artist
        final_title = clean_full_title
        final_artist = clean_uploader

    if not final_title: final_title = raw_title or "Unknown Title"
    if not final_artist or final_artist == "NA":
        final_artist = clean_uploader if clean_uploader else "Unknown Artist"

    return final_artist, final_title

def first_two_words(title: str) -> str:
    parts = title.split()
    return " ".join(parts[:2]) if len(parts) >= 2 else title

def has_parentheses(title: str) -> bool:
    return bool(re.search(r"\(.*?\)", title))

# ==============================
# ROUTES
# ==============================

@app.route('/')
def index():
    return render_template('index.html', config=DEFAULT_CONFIG)

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    station_id = data.get('station_id')
    api_key = data.get('api_key')
    playlist_url = data.get('playlist_url')
    download_dir_name = data.get('download_dir', 'Downloaded')
    
    azuracast_api = f"https://radio.maksimtsikvasvili24.thkit.ee/api/station/{station_id}/files"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    try:
        resp = requests.get(azuracast_api, headers=headers, timeout=30)
        existing_files = resp.json() if resp.status_code == 200 else []
    except:
        existing_files = []

    existing_songs = [
        {
            "artist": normalize(f.get("artist")),
            "title": normalize(f.get("title")),
            "clean_title": normalize(clean_junk(f.get("title"))),
            "orig_artist": f.get("artist"),
        }
        for f in existing_files
    ]

    app_root = os.path.dirname(os.path.abspath(__file__))
    abs_download_dir = os.path.join(app_root, download_dir_name)
    local_filenames_normalized = set()
    if os.path.exists(abs_download_dir):
        for f in os.listdir(abs_download_dir):
            if os.path.isfile(os.path.join(abs_download_dir, f)):
                name_no_ext = os.path.splitext(f)[0]
                local_filenames_normalized.add(normalize(name_no_ext))

    cmd = ["yt-dlp", "--flat-playlist", "--dump-single-json", playlist_url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        playlist_json = json.loads(proc.stdout)
    except:
        return jsonify({"error": "Failed to fetch playlist"}), 500

    entries = playlist_json.get("entries", [])
    results = []

    for track in entries:
        raw_artist = track.get("uploader")
        raw_title = track.get("title")
        final_artist, final_title = smart_parse(raw_title, raw_artist)

        norm_title = normalize(final_title)
        norm_artist = normalize(final_artist)
        
        predicted_filename = normalize(f"{clean_for_ffmpeg(final_artist)} - {clean_for_ffmpeg(final_title)}")

        status = "ok"
        message = ""
        should_check = True

        if predicted_filename in local_filenames_normalized:
            status = "file_exists"
            message = "File already on disk."
            should_check = False
        elif any(s["clean_title"] == norm_title and s["artist"] == norm_artist for s in existing_songs):
            status = "skip"
            message = "Exact match on Station."
            should_check = False
        
        if should_check:
            title_matches = [s for s in existing_songs if s["clean_title"] == norm_title]
            if title_matches:
                status = "warning"
                match_str = ", ".join({str(s['orig_artist']) for s in title_matches})
                message += f"Title exists (Artist: {match_str}). "

        results.append({
            "id": track.get("id"),
            "url": track.get("url"),
            "original_artist": raw_artist, 
            "clean_artist": final_artist,
            "title": final_title,
            "status": status,
            "message": message,
            "checked": should_check
        })

    return jsonify({"tracks": results})

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    tracks = data.get('tracks', [])
    download_dir = data.get('download_dir', 'Downloaded')
    app_root = os.path.dirname(os.path.abspath(__file__))
    abs_download_dir = os.path.abspath(os.path.join(app_root, download_dir))
    os.makedirs(abs_download_dir, exist_ok=True)

    def generate_log():
        for track in tracks:
            url = track.get('url')
            artist = track.get('clean_artist')
            title = track.get('title')
            safe_artist = clean_for_ffmpeg(artist)
            safe_title = clean_for_ffmpeg(title)
            yield f"Processing: {artist} - {title}\n"
            cmd = [
                "yt-dlp", "--newline", "-f", "bestaudio/best",
                "--extractor-args", "youtube:player_client=android",
                "-x", "--audio-format", "mp3", "--embed-metadata", "--embed-thumbnail",
                "--convert-thumbnails", "jpg",
                "--postprocessor-args", f"ffmpeg:-metadata artist=\"{safe_artist}\" -metadata title=\"{safe_title}\"",
                "-o", f"{safe_artist} - {safe_title}.%(ext)s", url
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=abs_download_dir)
            for line in proc.stdout: yield line
            proc.wait()
            if proc.returncode == 0: yield f"SUCCESS: {artist} - {title}\n"
            else: yield f"ERROR: Failed to download {title}\n"

    return Response(generate_log(), mimetype='text/plain')

if __name__ == '__main__':
    app.run(debug=True, port=5000)