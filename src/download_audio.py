import argparse
import os
import sys
import shutil
from yt_dlp import YoutubeDL


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def resolve_ffmpeg_location(path: str | None) -> str | None:
    if not path:
        return None
    p = os.path.expandvars(os.path.expanduser(path))
    if os.path.isfile(p):
        return p
    if os.path.isdir(p):
        cand = os.path.join(p, "ffmpeg.exe") if os.name == "nt" else os.path.join(p, "ffmpeg")
        if os.path.isfile(cand):
            return p
        bin_cand = os.path.join(p, "bin", "ffmpeg.exe") if os.name == "nt" else os.path.join(p, "bin", "ffmpeg")
        if os.path.isfile(bin_cand):
            return os.path.join(p, "bin")
    return None


def _format_bytes(num: float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def _format_eta(seconds: int | None) -> str:
    if not seconds or seconds < 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _bar(pct: float, width: int = 30) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(width * pct / 100.0)
    return "#" * filled + "." * (width - filled)


def progress_hook(d):
    status = d.get("status")
    if status == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        downloaded = d.get("downloaded_bytes", 0) or 0
        speed = d.get("speed") or 0
        eta = d.get("eta")
        pct = (downloaded / total * 100) if total else 0.0

        bar = _bar(pct)
        dl_str = _format_bytes(downloaded)
        tot_str = _format_bytes(total) if total else "?"
        spd_str = _format_bytes(speed) + "/s" if speed else "--"
        eta_str = _format_eta(eta)
        msg = f"[{bar}] {pct:5.1f}%  {dl_str}/{tot_str}  {spd_str}  ETA {eta_str}"
        print(msg, end="\r", flush=True)
    elif status == "finished":
        print("\nDownload finished, extracting/converting audio...")


def build_opts(outdir: str, audio_format: str, bitrate: int, no_playlist: bool, outtmpl: str | None, cookiefile: str | None, ffmpeg_location: str | None):
    postprocessors = []
    # Support 'mp4' as an alias for 'm4a' to match user expectation
    if audio_format == "mp4":
        audio_format = "m4a"

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

    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(outdir, "%(title)s.%(ext)s") if not outtmpl else outtmpl,
        "postprocessors": postprocessors,
        "noplaylist": no_playlist,
        "restrictfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
    }

    if ffmpeg_location:
        opts["ffmpeg_location"] = ffmpeg_location

    if cookiefile:
        opts["cookiefile"] = cookiefile

    return opts


def main():
    parser = argparse.ArgumentParser(
        description="Download videos and extract audio as MP3 or M4A."
    )
    parser.add_argument("urls", nargs="+", help="One or more video URLs")
    parser.add_argument(
        "-f",
        "--format",
        choices=["mp3", "m4a", "mp4"],
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
    parser.add_argument(
        "-t",
        "--template",
        default=None,
        help="Custom output template (overrides default). Example: 'downloads/%(title)s.%(ext)s'",
    )
    parser.add_argument(
        "-c",
        "--cookies",
        default=None,
        help="Path to cookies file for sites requiring login",
    )
    parser.add_argument(
        "--ffmpeg",
        default=None,
        help="Path to FFmpeg binary or directory containing it (e.g., tools/ffmpeg/bin)",
    )

    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)

    ffmpeg_loc = resolve_ffmpeg_location(args.ffmpeg)
    if args.ffmpeg and not ffmpeg_loc:
        print("Provided --ffmpeg path is invalid. Set to ffmpeg.exe or its folder.", file=sys.stderr)
        sys.exit(1)
    if not args.ffmpeg and not has_ffmpeg():
        print("FFmpeg not found on PATH. Install FFmpeg or use --ffmpeg.", file=sys.stderr)
        sys.exit(1)

    ydl_opts = build_opts(
        outdir=args.output,
        audio_format=args.format,
        bitrate=args.bitrate,
        no_playlist=args.no_playlist,
        outtmpl=args.template,
        cookiefile=args.cookies,
        ffmpeg_location=ffmpeg_loc,
    )
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