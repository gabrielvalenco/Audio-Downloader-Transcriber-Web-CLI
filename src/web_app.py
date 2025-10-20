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

# Gemini SDK (opcional, só usado na rota /transcribe)
try:
    import google.generativeai as genai  # type: ignore
except Exception:
    genai = None  # fallback: rota /transcribe retorna erro orientando instalar dependência

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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
  </head>
  <body>
    <div class="container">
      <div class="header">
      <div class="brand">Audio Downloader</div>
      <div class="badge">YouTube → MP3/M4A</div>
        <button id="theme-toggle" class="toggle" title="Alternar tema">Tema</button>
        <button id="toggle-history" class="toggle" title="Mostrar histórico">Histórico</button>
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
              <span class="chip chip-video" data-url="https://youtu.be/L8OesNa-pkA?si=a-cVuXG6FEu7IfyD">Sample video</span>
              <span class="chip chip-short" data-url="https://youtube.com/shorts/FT_9NOYwWqk?si=eZnIQYx140IKBLlJ">Sample short</span>
            </div>
            <div class="grid" style="margin-top:16px;">
              <div>
                <label for="format">Audio Format</label>
                <select id="format" name="format" class="hidden-select">
                  <option value="mp3" selected>MP3</option>
                  <option value="m4a">M4A</option>
                  <option value="mp4">MP4 (alias for M4A)</option>
                </select>
                <div class="select-wrap" id="format-custom">
                  <button type="button" id="format-display" class="select-display">MP3</button>
                  <div id="format-menu" class="select-menu" role="listbox" aria-labelledby="format-display">
                    <div class="select-item" role="option" data-val="mp3">MP3</div>
                    <div class="select-item" role="option" data-val="m4a">M4A</div>
                    <div class="select-item" role="option" data-val="mp4">MP4 (alias for M4A)</div>
                  </div>
                </div>
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
          <div class="examples" id="status" style="display:none;">Preparando…</div>
          <div class="row-actions" id="downloads-actions" style="margin-top:8px;">
            <button id="open-downloads" class="button-secondary" style="display:none;">Abrir downloads</button>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <h2 class="h1">Record audio</h2>
        </div>
        <div class="card-body">
          <div id="recorder">
            <div class="rec-controls">
              <button id="rec-start" class="btn">Start recording</button>
              <div class="rec-right">
                <div id="rec-timer" class="rec-timer" style="display:none;">00:00</div>
                <button id="rec-stop" class="button-secondary" style="display:none;">Stop</button>
              </div>
            </div>
            <audio id="rec-audio" controls style="display:none;margin-top:12px;"></audio>
            <div class="row-actions">
              <button id="rec-download" class="button-secondary" style="display:none;" disabled>Download recording</button>
              <button id="rec-delete" class="button-secondary" style="display:none;" disabled>Delete recording</button>
            </div>
            <div class="examples" id="rec-status" style="display:none; margin-top:8px;"></div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <h2 class="h1">Transcribe audio</h2>
        </div>
        <div class="card-body">
            <div id="transcribe">
            <label for="trans-file" style="margin-top:12px;">Audio file</label>
            <div id="trans-dropzone" class="dropzone" tabindex="0" role="button" aria-label="Select or drop audio file">
              <div class="dz-text">Arraste e solte um áudio aqui ou clique para escolher</div>
              <input type="file" id="trans-file" accept="audio/*" style="display:none;" />
            </div>
            <div class="row-actions" style="margin-top:12px;">
              <button id="use-recording" class="button-secondary" style="display:none;" disabled>Usar última gravação</button>
              <button id="transcribe-btn" class="btn">Transcrever</button>
            </div>
            <div class="examples" id="trans-status" style="display:none; margin-top:8px;"></div>
            <div id="trans-output-wrap" class="trans-output-wrap" style="display:none; margin-top:12px;">
              <div class="trans-output-toolbar">
                <div class="toolbar-title">Transcrição</div>
                <button id="copy-transcript" class="icon-btn" title="Copiar texto">Copiar</button>
              </div>
              <div id="trans-output" class="trans-output"></div>
            </div>
          </div>
        </div>
      </div>
      <div class="footer">Powered by yt-dlp + FFmpeg • <a href="https://github.com/gabrielvalenco" target="_blank" rel="noopener">github.com/gabrielvalenco</a></div>
      <div class="history" style="display:none;">
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
      const formatWrap = document.getElementById('format-custom');
      const formatDisplay = document.getElementById('format-display');
      const formatMenu = document.getElementById('format-menu');
      const bitrateInput = document.getElementById('bitrate');
      const progress = document.getElementById('progress');
      const progressBar = document.getElementById('progress-bar');
      const statusEl = document.getElementById('status');
      const themeToggle = document.getElementById('theme-toggle');
      const openDownloadsBtn = document.getElementById('open-downloads');
      const historyToggle = document.getElementById('toggle-history');
       const historySection = document.querySelector('.history');
       // Recorder elements
       const recStartBtn = document.getElementById('rec-start');
       const recStopBtn = document.getElementById('rec-stop');
       const recTimerEl = document.getElementById('rec-timer');
       const recAudioEl = document.getElementById('rec-audio');
       const recDownloadBtn = document.getElementById('rec-download');
       const recDeleteBtn = document.getElementById('rec-delete');
       const recStatusEl = document.getElementById('rec-status');
       // Transcription elements
       const transFileInput = document.getElementById('trans-file');
       const transcribeBtn = document.getElementById('transcribe-btn');
       const useRecordingBtn = document.getElementById('use-recording');
        const transStatusEl = document.getElementById('trans-status');
        const transOutputWrap = document.getElementById('trans-output-wrap');
        const transOutputEl = document.getElementById('trans-output');
        const copyTranscriptBtn = document.getElementById('copy-transcript');
       let recStream = null, mediaRecorder = null, recChunks = [], recBlob = null, recTimer = null, recStartAt = 0, recMime = null;
       let currentHistoryBtn = null;

      const HISTORY_KEY = 'audio_history';
      const HISTORY_VISIBLE_KEY = 'history_visible';

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

       // Chave da API agora é lida do ambiente no backend

      // Toggle de histórico (padrão oculto)
      function setHistoryVisible(v) {
        historySection.style.display = v ? 'block' : 'none';
        historyToggle.textContent = v ? 'Ocultar histórico' : 'Mostrar histórico';
      }
      const storedHistoryVisible = localStorage.getItem(HISTORY_VISIBLE_KEY);
      setHistoryVisible(storedHistoryVisible === 'true');
      historyToggle.addEventListener('click', () => {
        const next = historySection.style.display === 'none';
        setHistoryVisible(next);
        localStorage.setItem(HISTORY_VISIBLE_KEY, next ? 'true' : 'false');
        if (next) {
          historySection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });

      // Gravação de áudio via MediaRecorder
      function formatTime(ms) {
        const s = Math.floor(ms/1000); const m = Math.floor(s/60); const r = s % 60;
        return String(m).padStart(2,'0') + ':' + String(r).padStart(2,'0');
      }
      function updateRecTimer() {
        recTimerEl.textContent = formatTime(Date.now() - recStartAt);
      }
      async function startRecording() {
        recStatusEl.style.display = 'none';
        try {
          recStream = await navigator.mediaDevices.getUserMedia({ audio: true });
          recChunks = []; recBlob = null;
          const prefer = ['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/webm'];
          recMime = prefer.find(t => window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) || undefined;
          mediaRecorder = new MediaRecorder(recStream, recMime ? { mimeType: recMime } : {});
          mediaRecorder.ondataavailable = (ev) => { if (ev.data && ev.data.size > 0) recChunks.push(ev.data); };
          mediaRecorder.onstop = () => {
            recBlob = new Blob(recChunks, { type: recMime || 'audio/webm' });
            const url = URL.createObjectURL(recBlob);
            recAudioEl.src = url;
            recAudioEl.style.display = 'block';
            recDownloadBtn.disabled = false;
            recDeleteBtn.disabled = false;
            if (recDownloadBtn) { recDownloadBtn.style.display = 'inline-block'; }
            if (recDeleteBtn) { recDeleteBtn.style.display = 'inline-block'; }
            if (openDownloadsBtn) { openDownloadsBtn.style.display = 'inline-block'; }
            if (useRecordingBtn) { useRecordingBtn.disabled = false; useRecordingBtn.style.display = 'inline-block'; }
            recStatusEl.textContent = 'Gravação finalizada';
            recStatusEl.style.display = 'block';
            recStatusEl.classList.remove('status-deleted', 'status-saved');
            recStatusEl.classList.add('status-recorded');
          };
          mediaRecorder.start();
          recStartAt = Date.now();
          recTimerEl.style.display = 'block';
          updateRecTimer();
          recTimer = setInterval(updateRecTimer, 500);
          recStartBtn.disabled = true; 
          recStopBtn.style.display = 'inline-block';
          recStopBtn.disabled = false;
        } catch (err) {
          recStatusEl.textContent = 'Não foi possível acessar o microfone.';
          recStatusEl.style.display = 'block';
        }
      }
      function stopRecording() {
        try { mediaRecorder && mediaRecorder.stop(); } catch {}
        try { recStream && recStream.getTracks().forEach(t => t.stop()); } catch {}
        recStream = null;
        clearInterval(recTimer); recTimer = null;
        recTimerEl.style.display = 'none';
        recStartBtn.disabled = false; 
        recStopBtn.disabled = true; 
        recStopBtn.style.display = 'none';
      }
      recStartBtn.addEventListener('click', startRecording);
      recStopBtn.addEventListener('click', stopRecording);
      recDownloadBtn.addEventListener('click', () => {
        if (!recBlob) return;
        const a = document.createElement('a');
        const href = URL.createObjectURL(recBlob);
        a.href = href;
        const ext = (recMime && recMime.includes('ogg')) ? 'ogg' : 'webm';
        a.download = `recording-${new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')}.${ext}`;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(href); a.remove(); }, 1000);
        // Registrar no histórico como gravação local
        addHistory({ url: 'Gravação local', format: 'rec', ts: Date.now(), status: 'salvo' });
        recStatusEl.textContent = 'Gravação salva';
        recStatusEl.style.display = 'block';
        recStatusEl.classList.remove('status-recorded', 'status-deleted');
        recStatusEl.classList.add('status-saved');
      });
      recDeleteBtn.addEventListener('click', () => {
        try { recAudioEl.pause(); } catch {}
        try { 
          if (recAudioEl.src && recAudioEl.src.startsWith('blob:')) { 
            try { URL.revokeObjectURL(recAudioEl.src); } catch {}
          }
          recAudioEl.removeAttribute('src'); 
          recAudioEl.load(); 
        } catch {}
        recAudioEl.style.display = 'none';
        recBlob = null; recChunks = []; recMime = null;
        recDownloadBtn.disabled = true;
        recDeleteBtn.disabled = true;
        if (recDownloadBtn) { recDownloadBtn.style.display = 'none'; }
        if (recDeleteBtn) { recDeleteBtn.style.display = 'none'; }
        if (openDownloadsBtn) { openDownloadsBtn.style.display = 'none'; }
        if (useRecordingBtn) { useRecordingBtn.disabled = true; useRecordingBtn.style.display = 'none'; }
        // se estava preferindo gravação, limpar indicação
        try { window.preferRec = false; } catch {}
        recStatusEl.textContent = 'Gravação excluída';
        recStatusEl.style.display = 'block';
        recStatusEl.classList.remove('status-recorded', 'status-saved');
        recStatusEl.classList.add('status-deleted');
      });

      function reflectBitrateDisabled() {
        const isMp3 = formatSel.value === 'mp3';
        bitrateInput.disabled = !isMp3;
        bitrateInput.style.opacity = isMp3 ? '1' : '0.6';
      }
      reflectBitrateDisabled();
      formatSel.addEventListener('change', reflectBitrateDisabled);

      // Select custom: sincroniza display com select oculto
      function syncFormatDisplay() {
        const opt = formatSel.options[formatSel.selectedIndex];
        formatDisplay.textContent = opt ? opt.text : formatSel.value.toUpperCase();
      }
      syncFormatDisplay();
      formatDisplay.addEventListener('click', () => {
        formatWrap.classList.toggle('open');
      });
      document.querySelectorAll('#format-menu .select-item').forEach(it => {
        it.addEventListener('click', () => {
          const val = it.getAttribute('data-val');
          formatSel.value = val;
          syncFormatDisplay();
          formatWrap.classList.remove('open');
          reflectBitrateDisabled();
          formatSel.dispatchEvent(new Event('change'));
        });
      });
      document.addEventListener('click', (e) => {
        if (!formatWrap.contains(e.target)) { formatWrap.classList.remove('open'); }
      });

      document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {
        const url = c.getAttribute('data-url');
        urlInput.value = url;
        urlInput.focus();
      }));

      // Baixar novamente a partir do histórico
      document.addEventListener('click', (e) => {
        const hbtn = e.target.closest('.history-download');
        if (!hbtn) return;
        const url = hbtn.getAttribute('data-url');
        const fmt = hbtn.getAttribute('data-format') || 'mp3';
        if (url) {
          urlInput.value = url;
          formatSel.value = fmt;
          reflectBitrateDisabled();
          // Estado de loading no botão do histórico e dispara o submit oficial
          currentHistoryBtn?.classList.remove('loading');
          currentHistoryBtn?.removeAttribute('disabled');
          currentHistoryBtn = hbtn;
          hbtn.classList.add('loading');
          hbtn.setAttribute('disabled', 'true');
          document.getElementById('submit-btn').click();
        }
      });

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
        localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, 5)));
        renderHistory();
      }

      function renderHistory() {
        const list = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
        const el = document.getElementById('history-list');
        el.innerHTML = '';
        (list.slice(0, 5)).forEach(item => {
          const div = document.createElement('div');
          const fmt = (item.format || 'mp3').toLowerCase();
          div.className = 'history-item format-' + fmt;
          const badge = `<span class="format-badge format-${fmt}">${fmt.toUpperCase()}</span>`;
          const dlIcon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 3v10m0 0l4-4m-4 4l-4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M20 21H4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
          const right = (fmt !== 'rec' && isValidYouTubeUrl(item.url))
            ? `<button class="icon-btn history-download" title="Baixar novamente" data-url="${item.url}" data-format="${fmt}">${dlIcon}</button>`
            : '';
          const result = (item.status || '').toLowerCase();
          const statusClass = (result === 'ok')
            ? 'status-ok'
            : ((result === 'error' || result === 'erro')
              ? 'status-error'
              : (result === 'salvo')
                ? 'status-saved'
                : '');
          div.innerHTML = `<div><div>${badge} • ${item.url}</div><div class="meta">${new Date(item.ts).toLocaleString()}</div></div><div style="display:flex;align-items:center;gap:8px;"><div class="meta ${statusClass}">${item.status}</div>${right}</div>`;
          el.appendChild(div);
        });
      }
      renderHistory();

      // Handler de envio do formulário de conversão
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
          if (currentHistoryBtn) { currentHistoryBtn.classList.remove('loading'); currentHistoryBtn.removeAttribute('disabled'); currentHistoryBtn = null; }
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
            statusEl.classList.remove('status-ok', 'status-error');
            statusEl.classList.add('status-progress');
            const es = new EventSource(`/progress/${data.job_id}`);
            es.onmessage = (ev) => {
              let payload = {}; try { payload = JSON.parse(ev.data); } catch {}
              if (payload.status === 'downloading') {
                const pct = Math.max(0, Math.min(100, payload.pct || 0));
                progressBar.style.width = pct + '%';
                const eta = payload.eta ? `${Math.floor(payload.eta/60)}m ${Math.floor(payload.eta%60)}s` : '--';
                const speed = payload.speed ? (payload.speed/1024/1024).toFixed(2) + ' MB/s' : '--';
                statusEl.textContent = `Baixando… ${pct.toFixed(1)}% • Velocidade ${speed} • ETA ${eta}`;
                statusEl.classList.remove('status-ok', 'status-error');
                statusEl.classList.add('status-progress');
              } else if (payload.status === 'finished' || payload.stage === 'postprocessing') {
                statusEl.textContent = 'Convertendo áudio…';
                statusEl.classList.remove('status-ok', 'status-error');
                statusEl.classList.add('status-progress');
              } else if (payload.status === 'complete') {
                progressBar.style.width = '100%';
                statusEl.textContent = (payload.message || 'Concluído!');
                statusEl.classList.remove('status-error', 'status-progress');
                statusEl.classList.add('status-ok');
                setMessage(payload.message || 'Concluído!', 'success');
                if (openDownloadsBtn) { openDownloadsBtn.style.display = 'inline-block'; }
                es.close();
                addHistory({ url, format: formatSel.value, ts: Date.now(), status: 'ok' });
                overlay.style.display = 'none';
                btn.disabled = false;
                if (currentHistoryBtn) { currentHistoryBtn.classList.remove('loading'); currentHistoryBtn.removeAttribute('disabled'); currentHistoryBtn = null; }
              } else if (payload.status === 'error') {
                statusEl.textContent = payload.message || 'Erro.';
                statusEl.classList.remove('status-ok', 'status-progress');
                statusEl.classList.add('status-error');
                setMessage(payload.message || 'Erro na conversão.', 'error');
                if (openDownloadsBtn) { openDownloadsBtn.style.display = 'none'; }
                es.close();
                addHistory({ url, format: formatSel.value, ts: Date.now(), status: 'erro' });
                overlay.style.display = 'none';
                btn.disabled = false;
                if (currentHistoryBtn) { currentHistoryBtn.classList.remove('loading'); currentHistoryBtn.removeAttribute('disabled'); currentHistoryBtn = null; }
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
          if (currentHistoryBtn) { currentHistoryBtn.classList.remove('loading'); currentHistoryBtn.removeAttribute('disabled'); currentHistoryBtn = null; }
        } finally {
          btn.disabled = false;
          overlay.style.display = 'none';
        }
      });

      async function openDownloads() {
        try {
          const res = await fetch('/open_downloads', { method: 'POST' });
          const data = await res.json();
          if (data.status === 'ok') {
            setMessage('Abrindo pasta de downloads…', 'success');
          } else {
            setMessage(data.message || 'Não foi possível abrir a pasta.', 'error');
          }
        } catch (err) {
          setMessage('Erro ao abrir downloads.', 'error');
        }
      }
      openDownloadsBtn?.addEventListener('click', openDownloads);

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


@app.route("/transcribe", methods=["POST"])
def transcribe():
    # Validar dependência
    if genai is None:  # type: ignore
        return jsonify({"status": "error", "message": "Dependência 'google-generativeai' não instalada. Rode: python -m pip install google-generativeai"}), 500
    # Ler chave do ambiente (preferir GEMINI_API_KEY, aceitar GOOGLE_API_KEY)
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return jsonify({"status": "error", "message": "Defina a variável de ambiente GEMINI_API_KEY (ou GOOGLE_API_KEY) para usar a transcrição."}), 500

    f = request.files.get("audio")
    if not f:
        return jsonify({"status": "error", "message": "Envie um arquivo de áudio ou use a gravação."}), 400

    model_name = (request.form.get("model") or "gemini-2.5-flash").strip()
    prompt = (request.form.get("prompt") or "Transcribe the audio to text with punctuation.").strip()

    # Ler bytes diretamente e enviar inline ao modelo (evita upload/ragStore)
    try:
        # Em alguns ambientes, f.read pode já ter consumido o stream; garantir seek(0)
        try:
            audio_bytes = f.read()
        except Exception:
            f.stream.seek(0)
            audio_bytes = f.stream.read()

        mime = (getattr(f, "mimetype", None) or "").strip().lower()
        if not mime:
            name = (f.filename or "").lower()
            if name.endswith(".wav"):
                mime = "audio/wav"
            elif name.endswith(".mp3") or name.endswith(".mpeg"):
                mime = "audio/mpeg"
            elif name.endswith(".m4a") or name.endswith(".mp4"):
                mime = "audio/mp4"
            elif name.endswith(".ogg"):
                mime = "audio/ogg"
            elif name.endswith(".webm"):
                mime = "audio/webm"
            else:
                mime = "audio/webm"

        genai.configure(api_key=key)  # type: ignore
        try:
            model = genai.GenerativeModel(model_name)  # type: ignore
        except Exception:
            model = genai.GenerativeModel("gemini-1.5-flash")  # type: ignore

        parts = [{"mime_type": mime, "data": audio_bytes}, prompt]
        resp = model.generate_content(parts)  # type: ignore

        text = getattr(resp, "text", None)
        if not text:
            try:
                text = resp.candidates[0].content.parts[0].text  # type: ignore
            except Exception:
                text = ""
        return jsonify({"status": "ok", "text": text or ""})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("PORT", "5000"))
    except Exception:
        port = 5000
    debug_flag = os.environ.get("DEBUG", "1")
    debug = (debug_flag not in ("0", "false", "False"))
    app.run(host=host, port=port, debug=debug)