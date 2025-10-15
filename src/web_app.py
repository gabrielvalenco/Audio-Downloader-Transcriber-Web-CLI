from flask import Flask, request, render_template_string, jsonify, Response, redirect
import os
import uuid
import json
import queue
import threading
import time
from yt_dlp import YoutubeDL

# Reuse helpers from the CLI module
from download_audio import build_opts, resolve_ffmpeg_location, has_ffmpeg

app = Flask(__name__)
# Simple in-memory job store for SSE progress
jobs: dict[str, dict] = {}

INDEX_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Audio Downloader</title>
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <style>
      :root {
        --bg: #0b0f1a;
        --card: rgba(20, 24, 38, 0.9);
        --border: rgba(255,255,255,0.08);
        --accent: #7c3aed;
        --accent-2: #22d3ee;
        --text: #e7e7ea;
        --muted: #a3a3b2;
        --error: #ef4444;
        --success: #10b981;
      }
      .theme-light {
        --bg: #f6f7fb;
        --card: rgba(255, 255, 255, 0.9);
        --border: rgba(0,0,0,0.08);
        --accent: #3b82f6;
        --accent-2: #22c55e;
        --text: #191b22;
        --muted: #5b5e6a;
      }
      * { box-sizing: border-box; }
      body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Inter, Arial, sans-serif; color: var(--text); background: radial-gradient(1200px 600px at 10% 10%, #0e1726 0%, var(--bg) 40%, #0a0e19 100%); min-height:100vh; transition: background .25s ease; }
      .container { max-width: 900px; margin: 0 auto; padding: 32px; }
      .header { display:flex; align-items:center; justify-content:space-between; margin-bottom: 24px; gap:12px; }
      .brand { font-weight: 700; letter-spacing: 0.3px; font-size: 1.1rem; color: var(--muted); }
      .card { border: 1px solid var(--border); background: var(--card); backdrop-filter: blur(8px); border-radius: 16px; overflow: hidden; }
      .card-header { padding: 20px 24px; border-bottom: 1px solid var(--border); display:flex; align-items:center; gap:12px; }
      .h1 { font-size: 1.25rem; margin:0; }
      .badge { background: linear-gradient(135deg, var(--accent), var(--accent-2)); color:#fff; padding:6px 10px; border-radius:999px; font-size:0.75rem; }
      .card-body { padding: 24px; }
      label { font-size: 0.9rem; color: var(--muted); margin-bottom: 8px; display:block; }
      input[type=text], select { width:100%; padding:12px 14px; border-radius:10px; border:1px solid var(--border); background:#0b1220; color:var(--text); outline: none; transition: border-color .2s, box-shadow .2s; }
      input[type=text]:focus, select:focus { border-color: #3b82f6; box-shadow: 0 0 0 4px rgba(59,130,246,0.15); }
      .grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
      .btn { margin-top: 16px; padding: 12px 16px; border-radius: 10px; border: none; color:#fff; cursor:pointer; font-weight:600; background: linear-gradient(135deg, #3b82f6, #22c55e); box-shadow: 0 8px 20px rgba(34,197,94,0.25); transition: transform .15s ease, box-shadow .2s ease; }
      .btn:hover { transform: translateY(-1px); box-shadow: 0 10px 24px rgba(34,197,94,0.32); }
      .btn:disabled { opacity:0.6; cursor:not-allowed; }
      .examples { margin-top:8px; color: var(--muted); font-size: 0.85rem; }
      .chips { display:flex; gap:8px; flex-wrap: wrap; margin-top:8px; }
      .chip { font-size:0.8rem; padding:6px 10px; border-radius:999px; border:1px solid var(--border); cursor:pointer; background:#0b1220; color:var(--text); }
      .chip:hover { border-color:#3b82f6; }
      .msg { margin-top: 16px; padding: 12px; border-radius: 10px; border: 1px solid var(--border); }
      .msg.success { background: rgba(16,185,129,0.12); border-color: rgba(16,185,129,0.35); }
      .msg.error { background: rgba(239,68,68,0.12); border-color: rgba(239,68,68,0.35); }
      .footer { margin-top: 24px; text-align:center; color: var(--muted); font-size: 0.85rem; }
      .overlay { position:fixed; inset:0; background: rgba(0,0,0,0.35); backdrop-filter: blur(2px); display:none; align-items:center; justify-content:center; z-index: 1000; }
      .spinner { width: 56px; height: 56px; border: 6px solid rgba(59,130,246,0.25); border-top-color: #3b82f6; border-radius: 50%; animation: spin 0.85s linear infinite; }
      @keyframes spin { to { transform: rotate(360deg); } }
      .progress { margin-top:16px; height: 14px; background: #0b1220; border:1px solid var(--border); border-radius: 999px; overflow:hidden; }
      .progress > .bar { height:100%; width:0%; background: linear-gradient(135deg, var(--accent), var(--accent-2)); transition: width .2s ease; }
      .row-actions { display:flex; gap:8px; align-items:center; justify-content:space-between; margin-top:12px; }
      .button-secondary { padding: 10px 14px; border-radius: 10px; border: 1px solid var(--border); background: #0b1220; color: var(--text); cursor: pointer; }
      .button-secondary:hover { border-color:#3b82f6; }
      .history { margin-top:24px; }
      .history h3 { margin:0 0 12px; font-size:1rem; color: var(--muted); }
      .history-list { display:flex; flex-direction:column; gap:8px; }
      .history-item { padding:10px 12px; border:1px solid var(--border); border-radius:10px; display:flex; align-items:center; gap:8px; justify-content:space-between; }
      .history-item .meta { color: var(--muted); font-size:0.85rem; }
      .toggle { padding:8px 12px; border-radius:999px; border:1px solid var(--border); background:#0b1220; color:var(--text); cursor:pointer; }
    </style>
  </head>
  <body>
    <div class="container">
      <div class="header">
        <div class="brand">Audio Downloader</div>
        <div class="badge">YouTube → MP3/M4A</div>
        <button id="theme-toggle" class="toggle" title="Alternar tema">Tema</button>
      </div>
      <div class="card">
        <div class="card-header">
          <h2 class="h1">Convert a video to audio</h2>
        </div>
        <div class="card-body">
          <form id="convert-form">
            <label for="url">Video URL</label>
            <input type="text" id="url" name="url" placeholder="Paste the YouTube video or Shorts URL" required />
            <div class="chips">
              <span class="chip" data-url="https://youtu.be/L8OesNa-pkA?si=a-cVuXG6FEu7IfyD">Sample video</span>
              <span class="chip" data-url="https://youtube.com/shorts/FT_9NOYwWqk?si=eZnIQYx140IKBLlJ">Sample short</span>
            </div>
            <div class="grid" style="margin-top:16px;">
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
            <label for="ffmpeg" style="margin-top:16px;">FFmpeg path (optional)</label>
            <input type="text" id="ffmpeg" name="ffmpeg" placeholder="tools/ffmpeg/bin or C:\\ffmpeg\\bin" />
            <div class="examples">Tip: Run <code>scripts\\install_ffmpeg.ps1</code>, then use <code>tools\\ffmpeg\\bin</code>. Leave empty to auto-detect.</div>
            <button class="btn" type="submit" id="submit-btn">Convert</button>
          </form>
          <div id="message" class="msg" style="display:none;"></div>
          <div class="progress" id="progress" style="display:none;"><div class="bar" id="progress-bar"></div></div>
          <div class="row-actions">
            <div class="examples" id="status" style="display:none;">Preparando…</div>
            <button id="open-downloads" class="button-secondary">Abrir downloads</button>
          </div>
        </div>
      </div>
      <div class="footer">Powered by yt-dlp + FFmpeg</div>
      <div class="history">
        <h3>Histórico</h3>
        <div id="history-list" class="history-list"></div>
      </div>
    </div>
    <div class="overlay" id="overlay"><div class="spinner"></div></div>
    <script>
      const form = document.getElementById('convert-form');
      const msg = document.getElementById('message');
      const btn = document.getElementById('submit-btn');
      const overlay = document.getElementById('overlay');
      const urlInput = document.getElementById('url');
      const formatSel = document.getElementById('format');
      const bitrateInput = document.getElementById('bitrate');
      const progress = document.getElementById('progress');
      const progressBar = document.getElementById('progress-bar');
      const statusEl = document.getElementById('status');
      const themeToggle = document.getElementById('theme-toggle');
      const openDownloadsBtn = document.getElementById('open-downloads');

      const HISTORY_KEY = 'audio_history';

      // Theme toggle
      function applyTheme(t) {
        document.body.classList.toggle('theme-light', t === 'light');
      }
      const storedTheme = localStorage.getItem('theme') || 'dark';
      applyTheme(storedTheme);
      themeToggle.addEventListener('click', () => {
        const next = document.body.classList.contains('theme-light') ? 'dark' : 'light';
        applyTheme(next);
        localStorage.setItem('theme', next);
      });

      function reflectBitrateDisabled() {
        const isMp3 = formatSel.value === 'mp3';
        bitrateInput.disabled = !isMp3;
        bitrateInput.style.opacity = isMp3 ? '1' : '0.6';
      }
      reflectBitrateDisabled();
      formatSel.addEventListener('change', reflectBitrateDisabled);

      document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {
        const url = c.getAttribute('data-url');
        urlInput.value = url;
        urlInput.focus();
      }));

      function setMessage(text, type='success') {
        msg.textContent = text;
        msg.className = 'msg ' + type;
        msg.style.display = 'block';
      }

      function isValidYouTubeUrl(u) {
        try { const x = new URL(u); return /(^|\\.)youtube\\.com$/.test(x.hostname) || x.hostname === 'youtu.be'; } catch { return false; }
      }

      function addHistory(entry) {
        const list = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
        list.unshift(entry);
        localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, 10)));
        renderHistory();
      }

      function renderHistory() {
        const list = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
        const el = document.getElementById('history-list');
        el.innerHTML = '';
        list.forEach(item => {
          const div = document.createElement('div');
          div.className = 'history-item';
          div.innerHTML = `<div><div><strong>${item.format.toUpperCase()}</strong> • ${item.url}</div><div class="meta">${new Date(item.ts).toLocaleString()}</div></div><div class="meta">${item.status}</div>`;
          el.appendChild(div);
        });
      }
      renderHistory();

      async function openDownloads() {
        try {
          const res = await fetch('/open_downloads', { method: 'POST' });
          const data = await res.json();
          if (data.status === 'ok') {
            setMessage('Abrindo pasta de downloads…', 'success');
          } else {
            setMessage(data.message || 'Não foi possível abrir a pasta.', 'error');
          }
        } catch (e) {
          setMessage('Erro ao abrir downloads.', 'error');
        }
      }
      openDownloadsBtn.addEventListener('click', openDownloads);

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        msg.style.display = 'none';
        btn.disabled = true;
        overlay.style.display = 'flex';

        const url = urlInput.value.trim();
        if (!isValidYouTubeUrl(url)) {
          overlay.style.display = 'none';
          btn.disabled = false;
          urlInput.focus();
          urlInput.style.borderColor = '#ef4444';
          setMessage('URL inválida. Informe um link do YouTube ou Shorts.', 'error');
          return;
        }

        try {
          const fd = new FormData(form);
          const res = await fetch('/download', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'fetch' }});
          const data = await res.json().catch(() => null);
          if (data && data.status === 'ok' && data.job_id) {
            progress.style.display = 'block';
            statusEl.style.display = 'block';
            statusEl.textContent = 'Iniciando…';
            const es = new EventSource(`/progress/${data.job_id}`);
            es.onmessage = (ev) => {
              let payload = {}; try { payload = JSON.parse(ev.data); } catch {}
              if (payload.status === 'downloading') {
                const pct = Math.max(0, Math.min(100, payload.pct || 0));
                progressBar.style.width = pct + '%';
                const eta = payload.eta ? `${Math.floor(payload.eta/60)}m ${Math.floor(payload.eta%60)}s` : '--';
                const speed = payload.speed ? (payload.speed/1024/1024).toFixed(2) + ' MB/s' : '--';
                statusEl.textContent = `Baixando… ${pct.toFixed(1)}% • Velocidade ${speed} • ETA ${eta}`;
              } else if (payload.status === 'finished' || payload.stage === 'postprocessing') {
                statusEl.textContent = 'Convertendo áudio…';
              } else if (payload.status === 'complete') {
                progressBar.style.width = '100%';
                statusEl.textContent = (payload.message || 'Concluído!');
                setMessage(payload.message || 'Concluído!', 'success');
                es.close();
                addHistory({ url, format: formatSel.value, ts: Date.now(), status: 'ok' });
                overlay.style.display = 'none';
                btn.disabled = false;
              } else if (payload.status === 'error') {
                statusEl.textContent = payload.message || 'Erro.';
                setMessage(payload.message || 'Erro na conversão.', 'error');
                es.close();
                addHistory({ url, format: formatSel.value, ts: Date.now(), status: 'erro' });
                overlay.style.display = 'none';
                btn.disabled = false;
              }
            };
            es.onerror = () => {
              statusEl.textContent = 'Conexão de progresso perdida.';
            };
          } else {
            const text = (data && data.message) || 'Falha na conversão.';
            setMessage(text, 'error');
          }
        } catch (err) {
          setMessage('Erro de rede. Tente novamente.', 'error');
        } finally {
          btn.disabled = false;
          overlay.style.display = 'none';
        }
      });

      // Drag & drop e atalhos
      const card = document.querySelector('.card');
      card.addEventListener('dragover', (e) => { e.preventDefault(); });
      card.addEventListener('drop', (e) => {
        e.preventDefault();
        const text = e.dataTransfer.getData('text/plain');
        if (text) { urlInput.value = text.trim(); }
      });

      document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key.toLowerCase() === 'enter') { form.requestSubmit(); }
        if (e.ctrlKey && e.key.toLowerCase() === 'o') { openDownloads(); }
        if (e.ctrlKey && e.key.toLowerCase() === 't') { themeToggle.click(); }
      });
    </script>
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
    is_fetch = request.headers.get("X-Requested-With") == "fetch"

    # Auto-detect a local FFmpeg under tools/**/bin if PATH doesn't have it
    def find_local_ffmpeg_bin() -> str | None:
        project_root = os.path.dirname(os.path.dirname(__file__))
        tools_dir = os.path.join(project_root, "tools")
        if not os.path.isdir(tools_dir):
            return None
        # common path produced by our installer
        direct_bin = os.path.join(tools_dir, "ffmpeg", "bin")
        if os.path.isfile(os.path.join(direct_bin, "ffmpeg.exe")) or os.path.isfile(os.path.join(direct_bin, "ffmpeg")):
            return direct_bin
        # otherwise scan all subdirectories for a bin/ffmpeg(.exe)
        try:
            for entry in os.listdir(tools_dir):
                p = os.path.join(tools_dir, entry)
                if os.path.isdir(p):
                    bin_candidate = os.path.join(p, "bin")
                    if os.path.isfile(os.path.join(bin_candidate, "ffmpeg.exe")) or os.path.isfile(os.path.join(bin_candidate, "ffmpeg")):
                        return bin_candidate
        except Exception:
            return None
        return None

    if not ffmpeg_loc and not has_ffmpeg():
        auto_bin = find_local_ffmpeg_bin()
        if auto_bin:
            ffmpeg_loc = auto_bin
        else:
            msg = "FFmpeg not found. Install it (winget/choco) or run scripts\\install_ffmpeg.ps1 and set tools\\ffmpeg\\bin above."
            return (jsonify({"status": "error", "message": msg}) if is_fetch else render_template_string(INDEX_HTML, message=msg))

    ydl_opts = build_opts(
        outdir=outdir,
        audio_format=audio_format,
        bitrate=bitrate,
        no_playlist=True,  # always treat single items from UI
        outtmpl=None,
        cookiefile=None,
        ffmpeg_location=ffmpeg_loc,
    )

    # Job manager and SSE progress
    job_id = uuid.uuid4().hex
    q = queue.Queue()
    jobs[job_id] = {"queue": q, "status": "running", "outdir": outdir, "message": ""}

    def run_job(job_id: str, url: str, opts: dict, job: dict):
        def hook(d):
            status = d.get("status")
            ev = {"status": status}
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0) or 0
                ev["total"] = int(total)
                ev["downloaded"] = int(downloaded)
                ev["pct"] = (downloaded / total * 100) if total else 0.0
                ev["eta"] = d.get("eta")
                ev["speed"] = d.get("speed") or 0
            elif status == "finished":
                ev["stage"] = "postprocessing"
                ev["filename"] = d.get("filename")
            job["queue"].put(ev)

        job_opts = dict(opts)
        job_opts["progress_hooks"] = [hook]  # override hooks for SSE
        try:
            with YoutubeDL(job_opts) as ydl:
                ydl.download([url])
            job["status"] = "done"
            job["message"] = f"Done! Files saved to: {os.path.abspath(job['outdir'])}"
            job["queue"].put({"status": "complete", "message": job["message"]})
        except Exception as e:
            job["status"] = "error"
            job["message"] = f"Error: {e}"
            job["queue"].put({"status": "error", "message": job["message"]})
        finally:
            job["queue"].put(None)

    threading.Thread(target=run_job, args=(job_id, url, ydl_opts, jobs[job_id]), daemon=True).start()

    return jsonify({"status": "ok", "job_id": job_id, "outdir": os.path.abspath(outdir)})


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@app.route("/progress/<job_id>")
def progress(job_id: str):
    job = jobs.get(job_id)
    if not job:
        def gen_notfound():
            yield _sse({"status": "error", "message": "Job não encontrado."})
        return Response(gen_notfound(), mimetype="text/event-stream")

    q: queue.Queue = job["queue"]

    def gen():
        yield _sse({"status": "start"})
        while True:
            try:
                item = q.get(timeout=10)
            except queue.Empty:
                # heartbeat
                yield ":\n\n"
                continue
            if item is None:
                break
            yield _sse(item)
        yield _sse({"status": job.get("status", "done"), "message": job.get("message", ""), "outdir": job.get("outdir", "downloads")})

    return Response(gen(), mimetype="text/event-stream")


@app.route("/open_downloads", methods=["POST"])
def open_downloads():
    path = os.path.abspath("downloads")
    os.makedirs(path, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(path)
        else:
            import subprocess, sys as _sys
            opener = "open" if _sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, path])
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/favicon.svg")
def favicon_svg():
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#7c3aed"/>
      <stop offset="100%" stop-color="#22d3ee"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="14" fill="url(#g)"/>
  <path d="M24 20v24l20-12z" fill="#fff" opacity="0.9"/>
</svg>
"""
    return Response(svg.strip(), mimetype="image/svg+xml")


@app.route("/favicon.ico")
def favicon_ico():
    return redirect("/favicon.svg", code=302)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)