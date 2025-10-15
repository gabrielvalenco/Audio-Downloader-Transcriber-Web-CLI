# Audio Downloader & Transcriber (Web + CLI)

Download audio from videos via `yt-dlp` + `FFmpeg`, record audio in-browser, and transcribe files/recordings using an AI transcription model. Includes a simple Web UI, CLI, and Docker support for streamlined setup.

## Highlights
- Web UI: paste a video URL (YouTube/Shorts) and pick `mp3` or `m4a/mp4`.
- Transcription: upload or record audio and get text instantly; copy button included.
- Recording: in-browser recording (ogg/webm) with playable previews.
- CLI: fast downloads with bitrate control and templates.
- Docker: one-command setup with FFmpeg preinstalled.
- Windows-friendly: no need to modify PATH when using Docker.

## Prerequisites (local run)
- Python 3.10+.
- FFmpeg installed and available on `PATH`.
  - Windows: `winget install Gyan.FFmpeg` or `choco install ffmpeg`
  - Or install a local copy with `scripts\install_ffmpeg.ps1` and use `--ffmpeg`.
- Transcription API key:
  - Set `GEMINI_API_KEY` as an environment variable before starting the server.

## Quick Start (Web UI)
```powershell
# Install dependencies
pip install -r requirements.txt

# Set transcription API key
$env:GEMINI_API_KEY="<your_key_here>"

# Run the server
python src/web_app.py
```
Open `http://localhost:5000/`, paste a video URL, choose `mp3` or `m4a/mp4`, and optionally set MP3 bitrate or a custom FFmpeg path.

## Docker (recommended for a consistent setup)
### Using Docker Compose
1) Optionally create a `.env` file with:
```
GEMINI_API_KEY=<your_key_here>
```
2) Start the app:
```powershell
docker compose up --build
```
3) Open `http://localhost:5000/`.

Compose mounts local folders for development:
- `./src` and `./src/static` for live changes in debug.
- `./downloads` to persist outputs on the host.

### Using plain Docker
```powershell
# Build image
docker build -t audio-downloader-web .

# Run container (Windows PowerShell example)
docker run --rm -p 5000:5000 \
  -e GEMINI_API_KEY="<your_key_here>" \
  -e HOST=0.0.0.0 -e PORT=5000 -e DEBUG=1 \
  -v "$(Get-Location)\downloads":/app/downloads \
  audio-downloader-web
```
On bash shells, replace the volume flag with `-v "$(pwd)/downloads:/app/downloads"`.

## CLI Usage
Basic (Windows):
```bash
python src/download_audio.py --format mp3 --output downloads "https://example.com/video-url"
```

Multiple URLs:
```bash
python src/download_audio.py -f m4a -o downloads "https://url1" "https://url2"
```

Control bitrate for MP3 (kbps):
```bash
python src/download_audio.py -f mp3 -b 192 "https://url"
```

Skip playlists:
```bash
python src/download_audio.py --no-playlist "https://playlist-url"
```

Custom output template:
```bash
python src/download_audio.py -t "downloads/%(title)s.%(ext)s" "https://url"
```

Use cookies file (for sites requiring login):
```bash
python src/download_audio.py -c "C:\path\to\cookies.txt" "https://url"
```

Use a local FFmpeg without touching system PATH:
```bash
python src/download_audio.py --ffmpeg "tools/ffmpeg/bin" -f mp3 "https://url"
```

## Configuration
- Environment variables for the Web UI:
  - `GEMINI_API_KEY`: required for transcription.
  - `HOST`: default `0.0.0.0` in Docker, `127.0.0.1` locally.
  - `PORT`: default `5000`.
  - `DEBUG`: `1` or `0`.
- FFmpeg path can be set in the Web UI if not on PATH.

## Project Structure
```
audio/
├─ src/
│  ├─ web_app.py
│  ├─ download_audio.py
│  └─ static/
│     └─ style.css
├─ scripts/
│  ├─ setup.ps1
│  ├─ build.ps1
│  └─ install_ffmpeg.ps1
├─ Dockerfile
├─ docker-compose.yml
├─ .dockerignore
├─ .gitignore
├─ requirements.txt
└─ README.md
```

## Troubleshooting
- 500 Internal Server Error on transcription: ensure `GEMINI_API_KEY` is set.
- Clipboard copy issues: the UI includes a fallback method if permissions are restricted.
- "Open downloads" inside containers cannot launch the host’s file explorer; open `./downloads` on your machine directly.
- If FFmpeg is missing locally, either install it or run with Docker.

## Notes
- Respect platform terms of use and copyright.
- Do not use this tool to circumvent technical protection measures.