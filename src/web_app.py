from flask import Flask, request, render_template_string
import os
from yt_dlp import YoutubeDL

# Reuse helpers from the CLI module
from download_audio import build_opts, resolve_ffmpeg_location, has_ffmpeg

app = Flask(__name__)

INDEX_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Audio Downloader</title>
    <style>
      body { font-family: system-ui, sans-serif; margin: 2rem; background:#111; color:#eee; }
      .card { max-width: 720px; margin: 0 auto; padding: 1.5rem; border-radius: 8px; background:#1a1a1a; box-shadow: 0 2px 8px rgba(0,0,0,0.4); }
      label { display:block; margin: 0.5rem 0 0.25rem; }
      input[type=text], select { width: 100%; padding: 0.5rem; border-radius: 6px; border: 1px solid #333; background:#0f0f0f; color:#eee; }
      .row { display:flex; gap: 1rem; }
      .row > div { flex:1; }
      button { margin-top: 1rem; padding: 0.6rem 1rem; border: 0; border-radius: 6px; background: #3b82f6; color: white; cursor: pointer; }
      button:hover { background: #2563eb; }
      .examples { font-size: 0.9rem; color:#bbb; }
      .msg { margin-top: 1rem; padding: 0.75rem; border-radius: 6px; background:#0d1b2a; border:1px solid #1b263b; }
      footer { margin-top: 2rem; text-align:center; font-size:0.85rem; color:#888; }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Audio Downloader (YouTube → MP3/M4A)</h1>
      <p class="examples">Paste a video or short URL. Examples:<br>
      • Video: <code>https://youtu.be/L8OesNa-pkA?si=a-cVuXG6FEu7IfyD</code><br>
      • Short: <code>https://youtube.com/shorts/FT_9NOYwWqk?si=eZnIQYx140IKBLlJ</code></p>

      <form method="post" action="/download">
        <label for="url">Video URL</label>
        <input type="text" id="url" name="url" placeholder="Paste the video URL here" required />

        <div class="row">
          <div>
            <label for="format">Audio Format</label>
            <select id="format" name="format">
              <option value="mp3" selected>MP3</option>
              <option value="m4a">M4A</option>
              <option value="mp4">MP4 (alias for M4A)</option>
            </select>
          </div>
          <div>
            <label for="bitrate">Bitrate (MP3)</label>
            <input type="text" id="bitrate" name="bitrate" value="320" />
          </div>
        </div>

        <label for="ffmpeg">FFmpeg path (optional)</label>
        <input type="text" id="ffmpeg" name="ffmpeg" placeholder="e.g., tools/ffmpeg/bin or C:\\ffmpeg\\bin" />

        <button type="submit">Convert</button>
      </form>

      {% if message %}
        <div class="msg">{{ message }}</div>
      {% endif %}
    </div>

    <footer>Powered by yt-dlp + FFmpeg</footer>
  </body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML, message=None)


@app.route("/download", methods=["POST"])
def download():
    url = (request.form.get("url") or "").strip()
    audio_format = (request.form.get("format") or "mp3").strip()
    bitrate_str = (request.form.get("bitrate") or "320").strip()
    ffmpeg_path = (request.form.get("ffmpeg") or "").strip() or None

    try:
        bitrate = int(bitrate_str)
    except ValueError:
        bitrate = 320

    outdir = "downloads"
    os.makedirs(outdir, exist_ok=True)

    ffmpeg_loc = resolve_ffmpeg_location(ffmpeg_path) if ffmpeg_path else None
    if not ffmpeg_loc and not has_ffmpeg():
        return render_template_string(INDEX_HTML, message="FFmpeg not found. Install it or provide the path above.")

    ydl_opts = build_opts(
        outdir=outdir,
        audio_format=audio_format,
        bitrate=bitrate,
        no_playlist=True,  # always treat single items from UI
        outtmpl=None,
        cookiefile=None,
        ffmpeg_location=ffmpeg_loc,
    )

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        msg = f"Done! Files saved to: {os.path.abspath(outdir)}"
    except Exception as e:
        msg = f"Error: {e}"

    return render_template_string(INDEX_HTML, message=msg)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)