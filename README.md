# Audio Downloader CLI

Simple command-line tool to download videos and extract audio as MP3 or M4A using `yt-dlp` and `FFmpeg`.

## Features
- Downloads from many sites supported by `yt-dlp` (e.g., YouTube).
- Extracts audio as `mp3` (with configurable bitrate) or `m4a`.
- Handles single videos or playlists.
- Progress feedback in the terminal.
- Output directory customization.

## Prerequisites
- Python 3.10+ installed.
- FFmpeg installed and available on your `PATH`.
  - Windows: `winget install Gyan.FFmpeg` or `choco install ffmpeg`
  - Or install a local copy with `scripts\install_ffmpeg.ps1` and use `--ffmpeg` to point to it.

## Setup
```bash
pip install -r requirements.txt
```

Optionally use a virtual environment:
```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

## Usage
### Web UI (simple interface)
Start the local server:
```powershell
.\.venv\Scripts\python.exe src\web_app.py
```
Open http://localhost:5000/ and paste a video URL (YouTube normal or short), pick `mp3` or `m4a/mp4`, and optionally set the MP3 bitrate or an FFmpeg path.

### CLI
Basic example (Windows):
```bash
python src\\download_audio.py --format mp3 --output downloads "https://example.com/video-url"
```

Multiple URLs:
```bash
python src\\download_audio.py -f m4a -o downloads "https://url1" "https://url2"
```

Control bitrate for MP3 (in kbps):
```bash
python src\\download_audio.py -f mp3 -b 192 "https://url"
```

Skip playlists:
```bash
python src\\download_audio.py --no-playlist "https://playlist-url"
```

Custom output template:
```bash
python src\\download_audio.py -t "downloads/%(title)s.%(ext)s" "https://url"
```

Use cookies file (for sites requiring login):
```bash
python src\\download_audio.py -c "C:\\path\\to\\cookies.txt" "https://url"
```

Note: `--format mp4` is supported as an alias for `m4a` (audio inside MP4 containers is typically `m4a`).
 
Use a local FFmpeg without touching system PATH:
```bash
python src\\download_audio.py --ffmpeg "tools/ffmpeg/bin" -f mp3 "https://url"
```

## Build a standalone executable (Windows)
```bash
pip install pyinstaller
pyinstaller --onefile src\\download_audio.py
```
The executable will be created under `dist/`. Make sure FFmpeg is installed on the target machine.

Alternatively, use the provided PowerShell scripts:
```powershell
# Setup venv and dependencies
scripts\setup.ps1

# Build the executable
scripts\build.ps1
 
# Install a local FFmpeg (no admin required)
scripts\install_ffmpeg.ps1
```

## Project Structure
```
audio/
├─ src/
│  └─ download_audio.py
├─ scripts/
│  ├─ setup.ps1
│  ├─ build.ps1
│  └─ install_ffmpeg.ps1
├─ .gitignore
├─ requirements.txt
└─ README.md
```

## Notes
- Respect platform terms of use and copyright.
- This tool should not be used to circumvent technical protection measures.