import argparse
import os
import sys
import shutil
from yt_dlp import YoutubeDL


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def progress_hook(d):
    status = d.get("status")
    if status == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes", 0)
        if total:
            pct = downloaded / total * 100
            print(f"{pct:5.1f}% downloading...", end="\r", flush=True)
    elif status == "finished":
        print("\nDownload finished, extracting/converting audio...")


def build_opts(outdir: str, audio_format: str, bitrate: int, no_playlist: bool):
    postprocessors = []
    if audio_format == "mp3":
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": str(bitrate),
        })
    elif audio_format == "m4a":
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "m4a",
        })
    else:
        raise ValueError("Invalid format. Use 'mp3' or 'm4a'.")

    return {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(outdir, "%(title)s.%(ext)s"),
        "postprocessors": postprocessors,
        "noplaylist": no_playlist,
        "restrictfilenames": True,
        "quiet": False,
        "progress_hooks": [progress_hook],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Download videos and extract audio as MP3 or M4A."
    )
    parser.add_argument("urls", nargs="+", help="One or more video URLs")
    parser.add_argument(
        "-f",
        "--format",
        choices=["mp3", "m4a"],
        default="mp3",
        help="Output audio format (mp3 or m4a)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="downloads",
        help="Output directory",
    )
    parser.add_argument(
        "-b",
        "--bitrate",
        type=int,
        default=320,
        help="Bitrate for MP3 (kbps)",
    )
    parser.add_argument(
        "--no-playlist",
        action="store_true",
        help="Do not download playlists, only the single video",
    )

    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)

    if not has_ffmpeg():
        print("FFmpeg not found on PATH. Install FFmpeg and try again.", file=sys.stderr)
        sys.exit(1)

    ydl_opts = build_opts(args.output, args.format, args.bitrate, args.no_playlist)
    try:
        with YoutubeDL(ydl_opts) as ydl:
            for url in args.urls:
                ydl.download([url])
        print(f"Done! Files saved to: {os.path.abspath(args.output)}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()