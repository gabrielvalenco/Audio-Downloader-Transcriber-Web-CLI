from flask import Flask, request, render_template_string, jsonify, Response, redirect, send_from_directory
import os
from dotenv import load_dotenv
load_dotenv()
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
    <title>VoxHub</title>
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
    <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
    <script>
      window.SUPABASE_URL = "{{ supabase_url }}";
      window.SUPABASE_KEY = "{{ supabase_key }}";
    </script>
    <style>
      /* Auth Styles */
      .auth-modal {
        display: none;
        position: fixed;
        top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0, 0, 0, 0.6);
        backdrop-filter: blur(5px);
        z-index: 1000;
        justify-content: center;
        align-items: center;
        opacity: 0;
        transition: opacity 0.3s ease;
      }
      .auth-modal.open { 
        display: flex; 
        opacity: 1;
      }
      
      .auth-card {
        background: var(--card);
        padding: 32px;
        border-radius: 16px;
        border: 1px solid var(--border);
        width: 100%;
        max-width: 380px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.5);
        transform: translateY(20px) scale(0.95);
        transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
        font-family: 'JetBrains Mono', monospace;
      }

      .auth-modal.open .auth-card {
        transform: translateY(0) scale(1);
      }

      .auth-header { 
        font-size: 24px; 
        font-weight: 700; 
        margin-bottom: 24px; 
        text-align: center;
        color: var(--text);
        letter-spacing: -0.5px;
      }
      
      .auth-form input { 
        width: 100%; 
        margin-bottom: 16px; 
        padding: 12px 16px;
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid var(--border);
        border-radius: 8px;
        color: var(--text);
        font-family: inherit;
        font-size: 14px;
        transition: all 0.2s ease;
      }
      
      .auth-form input:focus {
        outline: none;
        border-color: var(--accent);
        background: rgba(255, 255, 255, 0.08);
        box-shadow: 0 0 0 4px rgba(225, 48, 108, 0.15);
      }
      
      .auth-actions { 
        display: flex; 
        flex-direction: column; 
        gap: 12px; 
        margin-top: 8px;
      }
      
      .auth-actions button {
        width: 100%;
        padding: 12px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 14px;
        cursor: pointer;
        transition: all 0.2s;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      #auth-submit {
        background: var(--accent, #e1306c);
        color: white;
        border: none;
        box-shadow: 0 4px 12px rgba(225, 48, 108, 0.3);
      }
      
      #auth-submit:hover {
        background: var(--accent-hover, #c12055);
        transform: translateY(-1px);
        box-shadow: 0 6px 16px rgba(225, 48, 108, 0.4);
      }
      
      #auth-submit:active {
        transform: translateY(0);
      }
      
      #auth-cancel {
        background: transparent;
        border: 1px solid var(--border);
        color: var(--muted);
      }
      
      #auth-cancel:hover {
        background: rgba(255, 255, 255, 0.05);
        color: var(--text);
        border-color: var(--muted);
      }

      .auth-link {
        font-size: 13px; 
        color: var(--muted); 
        text-align: center; 
        margin-top: 20px; 
        cursor: pointer; 
        text-decoration: none;
        transition: color 0.2s;
      }
      
      .auth-link:hover {
        color: var(--accent);
        text-decoration: underline;
      }
      
      .user-menu { display: flex; align-items: center; gap: 12px; margin-left: auto; position: relative; }
      .user-avatar { 
        width: 40px; height: 40px; border-radius: 50%; background: var(--accent); 
        color: #fff; display: flex; align-items: center; justify-content: center; font-weight: bold;
        cursor: pointer;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        user-select: none;
        font-size: 16px;
      }
      
      .header-actions .button-secondary {
        height: 40px;
        padding: 0 20px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .user-dropdown {
        position: absolute;
        top: 100%;
        right: 0;
        margin-top: 10px;
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 12px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        min-width: 200px;
        display: none;
        flex-direction: column;
        z-index: 1000;
        overflow: hidden;
        animation: fadeIn 0.2s ease;
      }
      .user-dropdown.show { display: flex; }
      .user-dropdown-item {
        padding: 12px 16px;
        cursor: pointer;
        font-size: 14px;
        color: var(--text);
        transition: all 0.2s;
        text-align: left;
        background: none;
        border: none;
        width: 100%;
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .user-dropdown-item:hover {
        background: var(--bg);
        color: var(--accent);
      }
      .user-dropdown-divider {
        height: 1px;
        background: var(--border);
        margin: 4px 0;
      }
      .user-email-display {
        font-size: 12px;
        color: var(--muted);
        cursor: default !important;
        font-weight: 500;
        padding-bottom: 8px;
      }
      .user-email-display:hover {
        background: none !important;
        color: var(--muted) !important;
      }
      .hidden { display: none !important; }
    </style>
  </head>
  <body>
    <div class="container">
      <div class="header">
        <div class="header-left">
          <div class="brand">VoxHub</div>
        </div>
        <div class="header-actions">
          <div id="auth-section" class="user-menu hidden">
             <div id="user-avatar" class="user-avatar" title="Perfil">U</div>
             <div id="user-dropdown" class="user-dropdown">
                <div id="user-email-display" class="user-dropdown-item user-email-display"></div>
                <div class="user-dropdown-divider"></div>
                <a href="/history" class="user-dropdown-item" style="text-decoration:none;">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  Histórico
                </a>
                <button id="logout-btn" class="user-dropdown-item">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  Sair
                </button>
             </div>
          </div>
          <button id="login-btn" class="button-secondary">Entrar</button>
          <button id="theme-toggle" class="toggle theme-toggle" title="Alternar tema" aria-label="Alternar tema">
            <svg class="moon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
              <path d="M21 12.79A9 9 0 0111.21 3c-.2 0-.39 0-.58.02a8 8 0 1010.35 10.35c.02-.19.02-.38.02-.58z" fill="currentColor"></path>
            </svg>
            <svg class="sun" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
              <path d="M12 4V2m0 20v-2M4 12H2m20 0h-2M5.64 5.64L4.22 4.22m15.56 15.56l-1.42-1.42M18.36 5.64l1.42-1.42M5.64 18.36l-1.42 1.42" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              <circle cx="12" cy="12" r="5" fill="currentColor"/>
            </svg>
          </button>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <h2 class="h1">Converter vídeo para áudio</h2>
        </div>
        <div class="card-body">
          <form id="convert-form">
            <label for="url">URL do Vídeo</label>
            <input type="text" id="url" name="url" placeholder="Cole a URL do vídeo do YouTube ou Shorts" required />
            <div class="chips">
              <span class="chip chip-video" data-url="https://youtu.be/L8OesNa-pkA?si=a-cVuXG6FEu7IfyD">Exemplo vídeo</span>
              <span class="chip chip-short" data-url="https://youtube.com/shorts/FT_9NOYwWqk?si=eZnIQYx140IKBLlJ">Exemplo short</span>
            </div>
            <div class="grid" style="margin-top:16px;">
              <div>
                <label for="format">Formato</label>
                <select id="format" name="format" class="hidden-select">
                  <option value="mp3" selected>MP3</option>
                  <option value="m4a">M4A</option>
                  <option value="mp4">MP4 (alias para M4A)</option>
                </select>
                <div class="select-wrap" id="format-custom">
                  <button type="button" id="format-display" class="select-display">MP3</button>
                  <div id="format-menu" class="select-menu" role="listbox" aria-labelledby="format-display">
                    <div class="select-item" role="option" data-val="mp3">MP3</div>
                    <div class="select-item" role="option" data-val="m4a">M4A</div>
                    <div class="select-item" role="option" data-val="mp4">MP4 (alias para M4A)</div>
                  </div>
                </div>
              </div>
              <div>
                <label for="bitrate">Bitrate (MP3)</label>
                <input type="text" id="bitrate" name="bitrate" value="320" />
              </div>
            </div>
            <label for="ffmpeg" style="margin-top:16px;">Caminho FFmpeg (opcional)</label>
            <input type="text" id="ffmpeg" name="ffmpeg" placeholder="tools/ffmpeg/bin ou C:\\ffmpeg\\bin" />
            <div class="examples">Dica: Rode <code>scripts\\install_ffmpeg.ps1</code>, depois use <code>tools\\ffmpeg\\bin</code>. Deixe vazio para auto-detectar.</div>
            <button class="btn" type="submit" id="submit-btn">Converter</button>
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
          <h2 class="h1">Gravar áudio</h2>
        </div>
        <div class="card-body">
          <div id="recorder">
            <div class="rec-controls">
              <button id="rec-start" class="btn">Iniciar gravação</button>
              <div class="rec-right">
                <div id="rec-timer" class="rec-timer" style="display:none;">00:00</div>
                <button id="rec-stop" class="button-secondary" style="display:none;">Parar</button>
              </div>
            </div>
            <audio id="rec-audio" controls style="display:none;margin-top:12px;"></audio>
            <div class="row-actions">
              <button id="rec-download" class="button-secondary" style="display:none;" disabled>Baixar gravação</button>
              <button id="rec-delete" class="button-secondary" style="display:none;" disabled>Excluir gravação</button>
            </div>
            <div class="examples" id="rec-status" style="display:none; margin-top:8px;"></div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <h2 class="h1">Transcrever áudio</h2>
        </div>
        <div class="card-body">
            <div id="transcribe">
            <label for="trans-file" style="margin-top:12px;">Arquivo de áudio</label>
            <div id="trans-dropzone" class="dropzone" tabindex="0" role="button" aria-label="Select or drop audio file">
              <div class="dz-text">Arraste e solte um áudio aqui ou clique para escolher</div>
              <input type="file" id="trans-file" accept="audio/*" style="display:none;" />
            </div>
            <div class="row-actions" style="margin-top:12px;">
              <button id="use-recording" class="button-secondary" style="display:none;" disabled>Usar última gravação</button>
              <button id="clear-trans-file" class="button-secondary" type="button" title="Excluir arquivo" style="display:none;">Excluir arquivo</button>
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
<button id="scroll-top" class="btn scroll-top" title="Subir ao topo" aria-label="Subir ao topo">
  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
    <path d="M12 4l-6 6h4v8h4v-8h4l-6-6z"></path>
  </svg>
</button>
    </div>
    <div class="overlay" id="overlay"><div class="spinner"></div></div>

    <!-- Auth Modal -->
    <div id="auth-modal" class="auth-modal">
      <div class="auth-card">
        <div class="auth-header" id="auth-title">Entrar</div>
        <div class="auth-form">
          <input type="email" id="auth-email" placeholder="Email" />
          <input type="password" id="auth-password" placeholder="Senha" />
          <div class="auth-actions">
            <button id="auth-submit" class="btn">Entrar</button>
            <button id="auth-cancel" class="button-secondary">Cancelar</button>
          </div>
          <div id="auth-msg" class="examples" style="text-align:center;margin-top:8px;display:none;"></div>
          <div id="auth-switch" class="auth-link">Não tem conta? Cadastre-se</div>
        </div>
      </div>
    </div>
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
      const scrollTopBtn = document.getElementById('scroll-top');
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
        const transDropzone = document.getElementById('trans-dropzone');
        const transDzText = transDropzone ? transDropzone.querySelector('.dz-text') : null;
        const clearTransFileBtn = document.getElementById('clear-trans-file');
        // Etapas melhoradas para o loading de transcrição
        const TRANS_STEPS = [
          'Preparando áudio…',
          'Validando formato e tamanho…',
          'Enviando arquivo para o agente…',
          'Analisando conteúdo…',
          'Detectando idioma…',
          'Transcrevendo fala…',
          'Refinando pontuação…'
        ];
        let recStream = null, mediaRecorder = null, recChunks = [], recBlob = null, recTimer = null, recStartAt = 0, recMime = null;
        let currentHistoryBtn = null;
        let transLoadingTimers = [];
        let transActiveIdx = 0;
        let transDone = [];

       // ---- Drag & Drop para transcrição ----
       function setTransFileFromFile(file) {
         try {
           const dt = new DataTransfer();
           dt.items.add(file);
           transFileInput.files = dt.files;
         } catch (_) {
           // Alguns navegadores não permitem setar programaticamente. Usuário pode clicar.
         }
         if (transDzText && file) { transDzText.textContent = file.name || 'Arquivo selecionado'; }
       }

       transDropzone?.addEventListener('click', () => { transFileInput?.click(); });
       transDropzone?.addEventListener('keydown', (e) => {
         if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); transFileInput?.click(); }
       });
       transDropzone?.addEventListener('dragenter', (e) => { e.preventDefault(); e.stopPropagation(); transDropzone.classList.add('dragover'); });
       transDropzone?.addEventListener('dragover', (e) => { e.preventDefault(); e.stopPropagation(); transDropzone.classList.add('dragover'); });
       transDropzone?.addEventListener('dragleave', () => { transDropzone.classList.remove('dragover'); });
       transDropzone?.addEventListener('drop', (e) => {
         e.preventDefault(); e.stopPropagation(); transDropzone.classList.remove('dragover');
         const files = e.dataTransfer?.files;
         if (files && files.length) {
           const f = files[0];
           setTransFileFromFile(f);
         }
       });
       transFileInput?.addEventListener('change', () => {
         const f = transFileInput.files && transFileInput.files[0];
         if (f) { if (transDzText) transDzText.textContent = f.name; }
       });

       clearTransFileBtn?.addEventListener('click', () => {
         try { transFileInput.value = ''; } catch {}
         try { transFileInput.files = new DataTransfer().files; } catch {}
         if (transDzText) transDzText.textContent = 'Arraste e solte um áudio aqui ou clique para escolher';
         transStatusEl.style.display = 'none';
         transOutputWrap.style.display = 'none';
       });

       useRecordingBtn?.addEventListener('click', () => {
         if (!recBlob) { transStatusEl.textContent = 'Nenhuma gravação disponível.'; transStatusEl.style.display = 'block'; return; }
         const file = new File([recBlob], 'recording.webm', { type: recMime || 'audio/webm' });
         setTransFileFromFile(file);
       });

       // Loading fictício para transcrição
       function renderTransSteps() {
         const html = ['<ul class="trans-steps">'];
         for (let i = 0; i < TRANS_STEPS.length; i++) {
           const isDone = !!transDone[i];
           const isActive = i === transActiveIdx && !isDone;
           const cls = ['trans-step', isActive ? 'active' : '', isDone ? 'done' : ''].filter(Boolean).join(' ');
           const icon = isDone ? '<span class="step-check">✓</span>' : (isActive ? '<span class="spinner-mini"></span>' : '<span class="step-dot">•</span>');
           html.push(`<li class="${cls}">${icon} ${TRANS_STEPS[i]}</li>`);
         }
         html.push('</ul>');
         transStatusEl.innerHTML = html.join('');
       }
       function renderTransStepsAllDone(finalText) {
         for (let i = 0; i < TRANS_STEPS.length; i++) transDone[i] = true;
         transActiveIdx = TRANS_STEPS.length - 1;
         const html = ['<ul class="trans-steps">'];
         for (let i = 0; i < TRANS_STEPS.length; i++) {
           html.push(`<li class="trans-step done"><span class="step-check">✓</span> ${TRANS_STEPS[i]}</li>`);
         }
         html.push('</ul>');
         if (finalText) html.push(`<div class="final-line">${finalText}</div>`);
         transStatusEl.innerHTML = html.join('');
       }
       function renderTransStepsError(errorText) {
         const html = ['<ul class="trans-steps">'];
         for (let i = 0; i < TRANS_STEPS.length; i++) {
           if (i < transActiveIdx) {
             html.push(`<li class="trans-step done"><span class="step-check">✓</span> ${TRANS_STEPS[i]}</li>`);
           } else if (i === transActiveIdx) {
             html.push(`<li class="trans-step error"><span class="step-dot">•</span> ${TRANS_STEPS[i]}</li>`);
           } else {
             html.push(`<li class="trans-step"><span class="step-dot">•</span> ${TRANS_STEPS[i]}</li>`);
           }
         }
         html.push('</ul>');
         if (errorText) html.push(`<div class="final-line">${errorText}</div>`);
         transStatusEl.innerHTML = html.join('');
       }
       function startTransLoading() {
         transLoadingTimers.forEach(id => clearTimeout(id));
         transLoadingTimers = [];
         transStatusEl.style.display = 'block';
         transStatusEl.classList.remove('status-ok', 'status-error', 'status-progress');
         transStatusEl.classList.add('status-progress');
         transActiveIdx = 0;
         transDone = Array(TRANS_STEPS.length).fill(false);
         renderTransSteps();
         // Avança sequencialmente pelas primeiras etapas, depois mantém em "Transcrevendo fala…"
         const durations = [700, 800, 900, 900, 900]; // soma cumulativa para agendamento
         let acc = 0;
         for (let k = 0; k < 4; k++) { // avança do passo 0 ao 4 rapidamente
           acc += durations[k];
           transLoadingTimers.push(setTimeout(() => {
             transDone[transActiveIdx] = true;
             transActiveIdx = Math.min(transActiveIdx + 1, 5); // manter em "Transcrevendo fala…" (índice 5)
             renderTransSteps();
           }, acc));
         }
       }
       function stopTransLoading() {
         transLoadingTimers.forEach(id => clearTimeout(id));
         transLoadingTimers = [];
       }

       async function submitTranscription() {
         transOutputWrap.style.display = 'none';
         startTransLoading();
         try {
           let file = transFileInput.files && transFileInput.files[0];
           if (!file && recBlob) { file = new File([recBlob], 'recording.webm', { type: recMime || 'audio/webm' }); }
           if (!file) { 
             stopTransLoading();
             transStatusEl.classList.remove('status-progress');
             transStatusEl.classList.add('status-error');
             renderTransStepsError('Selecione ou arraste um arquivo de áudio.');
             return; 
           }
           const fd = new FormData();
           fd.append('audio', file);
           const res = await fetch('/transcribe', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'fetch' }});
           const data = await res.json().catch(() => null);
           if (data && data.status === 'ok') {
             stopTransLoading();
             transOutputEl.textContent = data.text || '';
             transOutputWrap.style.display = 'block';
             transStatusEl.classList.remove('status-progress');
             transStatusEl.classList.add('status-ok');
             renderTransStepsAllDone('Transcrição concluída');
             
             addHistory({ 
               url: 'Transcrição: ' + (file.name || 'Áudio gravado'), 
               format: 'txt', 
               ts: Date.now(), 
               status: 'ok' 
             });
           } else {
             stopTransLoading();
             transStatusEl.classList.remove('status-progress');
             transStatusEl.classList.add('status-error');
             renderTransStepsError((data && data.message) || 'Falha na transcrição.');
           }
         } catch (_) {
           stopTransLoading();
           transStatusEl.classList.remove('status-progress');
           transStatusEl.classList.add('status-error');
           renderTransStepsError('Erro ao enviar áudio.');
         }
       }
       transcribeBtn?.addEventListener('click', submitTranscription);

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
        if (!el) return;
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

      // Pré-preencher via parâmetros de URL e enviar automaticamente
      try {
        const params = new URLSearchParams(window.location.search);
        const qUrl = params.get('url');
        const qFormat = params.get('format');
        const qSubmit = params.get('submit');
        if (qUrl) {
          urlInput.value = qUrl;
          if (qFormat) {
            formatSel.value = qFormat.toLowerCase();
            if (typeof reflectBitrateDisabled === 'function') { reflectBitrateDisabled(); }
            if (typeof syncFormatDisplay === 'function') { syncFormatDisplay(); }
          }
          if (qSubmit && (qSubmit === '1' || qSubmit.toLowerCase() === 'true')) {
            // Agendar após registrar listeners do formulário para evitar envio padrão
            setTimeout(() => {
              if (typeof form.requestSubmit === 'function') {
                form.requestSubmit();
              } else {
                document.getElementById('submit-btn').click();
              }
            }, 0);
          }
        }
      } catch (_) {}

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

      window.addEventListener('scroll', () => {
        const show = window.scrollY > 200;
        if (scrollTopBtn) {
          scrollTopBtn.style.display = show ? 'inline-flex' : 'none';
        }
      });
      scrollTopBtn?.addEventListener('click', () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });

      // --- SUPABASE INTEGRATION ---
      const supabaseClient = window.SUPABASE_URL ? supabase.createClient(window.SUPABASE_URL, window.SUPABASE_KEY) : null;
      let currentUser = null;

      const loginBtn = document.getElementById('login-btn');
      const logoutBtn = document.getElementById('logout-btn');
      const authSection = document.getElementById('auth-section');
      const userAvatar = document.getElementById('user-avatar');
      const authModal = document.getElementById('auth-modal');
      const authEmail = document.getElementById('auth-email');
      const authPass = document.getElementById('auth-password');
      const authSubmit = document.getElementById('auth-submit');
      const authCancel = document.getElementById('auth-cancel');
      const authSwitch = document.getElementById('auth-switch');
      const authMsg = document.getElementById('auth-msg');
      const authTitle = document.getElementById('auth-title');
      const userDropdown = document.getElementById('user-dropdown');
      const userEmailDisplay = document.getElementById('user-email-display');

      // Dropdown toggle logic
      userAvatar?.addEventListener('click', (e) => {
        e.stopPropagation();
        userDropdown.classList.toggle('show');
      });

      document.addEventListener('click', (e) => {
        if (userDropdown && !userDropdown.contains(e.target) && e.target !== userAvatar) {
          userDropdown.classList.remove('show');
        }
      });

      let isLoginMode = true;

      function toggleAuthModal(show) {
        authModal.classList.toggle('open', show);
        if (show) {
          authEmail.value = ''; authPass.value = ''; authMsg.style.display = 'none';
          isLoginMode = true; updateAuthMode();
        }
      }

      function updateAuthMode() {
        authTitle.textContent = isLoginMode ? 'Entrar' : 'Criar conta';
        authSubmit.textContent = isLoginMode ? 'Entrar' : 'Cadastrar';
        authSwitch.textContent = isLoginMode ? 'Não tem conta? Cadastre-se' : 'Já tem conta? Entre';
      }

      authSwitch?.addEventListener('click', () => {
        isLoginMode = !isLoginMode;
        updateAuthMode();
      });

      loginBtn?.addEventListener('click', () => toggleAuthModal(true));
      authCancel?.addEventListener('click', () => toggleAuthModal(false));
      authModal?.addEventListener('click', (e) => { if (e.target === authModal) toggleAuthModal(false); });

      authSubmit?.addEventListener('click', async () => {
        const email = authEmail.value.trim();
        const password = authPass.value.trim();
        if (!email || !password) {
          authMsg.textContent = 'Preencha todos os campos.';
          authMsg.style.display = 'block';
          authMsg.className = 'examples status-error';
          return;
        }
        authSubmit.disabled = true;
        authSubmit.textContent = 'Processando...';
        
        try {
          let error = null;
          if (isLoginMode) {
            const res = await supabaseClient.auth.signInWithPassword({ email, password });
            error = res.error;
          } else {
            const res = await supabaseClient.auth.signUp({ email, password });
            error = res.error;
            if (!error && res.data.user && !res.data.session) {
              authMsg.textContent = 'Verifique seu email para confirmar o cadastro.';
              authMsg.className = 'examples status-ok';
              authMsg.style.display = 'block';
              authSubmit.disabled = false;
              authSubmit.textContent = 'Cadastrar';
              return;
            }
          }

          if (error) {
            authMsg.textContent = error.message;
            authMsg.className = 'examples status-error';
            authMsg.style.display = 'block';
          } else {
            toggleAuthModal(false);
          }
        } catch (err) {
          console.error(err);
          authMsg.textContent = 'Erro inesperado.';
          authMsg.className = 'examples status-error';
          authMsg.style.display = 'block';
        }
        authSubmit.disabled = false;
        updateAuthMode();
      });

      logoutBtn?.addEventListener('click', async () => {
        await supabaseClient.auth.signOut();
      });

      if (supabaseClient) {
        supabaseClient.auth.onAuthStateChange((event, session) => {
          currentUser = session?.user || null;
          if (currentUser) {
            loginBtn.classList.add('hidden');
            authSection.classList.remove('hidden');
            userAvatar.textContent = (currentUser.email || 'U').charAt(0).toUpperCase();
            if (userEmailDisplay) userEmailDisplay.textContent = currentUser.email;
            loadSupabaseHistory();
          } else {
            loginBtn.classList.remove('hidden');
            authSection.classList.add('hidden');
            // Reverter para LocalStorage se deslogar
            originalRenderHistory();
          }
        });
      }

      // Sobrescrever funções de histórico para usar Supabase
      const originalAddHistory = addHistory;
      const originalRenderHistory = renderHistory;

      addHistory = function(entry) {
        // Sempre salva localmente
        originalAddHistory(entry);
        
        // Se logado, salva no Supabase
        if (currentUser && supabaseClient) {
          // Remover filtro de gravação para salvar tudo
          // if (entry.format === 'rec') return;

          supabaseClient.from('history').insert({
            user_id: currentUser.id,
            url: entry.url,
            format: entry.format,
            created_at: new Date().toISOString()
          }).then(({ error }) => {
            if (!error) loadSupabaseHistory();
          });
        }
      };

      renderHistory = function() {
        if (currentUser) {
           loadSupabaseHistory();
        } else {
           originalRenderHistory();
        }
      };

      async function loadSupabaseHistory() {
        if (!currentUser || !supabaseClient) return;
        const { data, error } = await supabaseClient
          .from('history')
          .select('*')
          .order('created_at', { ascending: false })
          .limit(10);
        
        if (data && !error) {
          const el = document.getElementById('history-list');
          if (!el) return;
          el.innerHTML = '';
          data.forEach(item => {
             const entry = {
               url: item.url,
               format: item.format,
               ts: new Date(item.created_at).getTime(),
               status: 'salvo'
             };
             
             const div = document.createElement('div');
             const fmt = (entry.format || 'mp3').toLowerCase();
             div.className = 'history-item format-' + fmt;
             const badge = `<span class="format-badge format-${fmt}">${fmt.toUpperCase()}</span>`;
             const dlIcon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 3v10m0 0l4-4m-4 4l-4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M20 21H4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
             const right = (isValidYouTubeUrl(entry.url))
                ? `<button class="icon-btn history-download" title="Baixar novamente" data-url="${entry.url}" data-format="${fmt}">${dlIcon}</button>`
                : '';
             const statusClass = 'status-saved';
             div.innerHTML = `<div><div>${badge} • ${entry.url}</div><div class="meta">${new Date(entry.ts).toLocaleString()}</div></div><div style="display:flex;align-items:center;gap:8px;"><div class="meta ${statusClass}">Supabase</div>${right}</div>`;
             el.appendChild(div);
          });
        }
      }
    </script>
  </body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    return render_template_string(
        INDEX_HTML, 
        message=None,
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_key=os.environ.get("SUPABASE_KEY", "")
    )


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

    is_vercel = os.environ.get("VERCEL") == "1"
    outdir = "/tmp/downloads" if is_vercel else "downloads"
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
        elif not is_vercel:
            # On Vercel, we might not have ffmpeg, but we proceed to try (some formats might work)
            # or we fail later.
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
    # Store necessary info to run the job later (in /progress)
    jobs[job_id] = {
        "queue": q,
        "status": "pending",
        "outdir": outdir,
        "message": "",
        "url": url,
        "ydl_opts": ydl_opts
    }

    # On Vercel (or generally to avoid freezing), we start the thread when the client connects to SSE.
    # However, for local dev, starting immediately is fine. 
    # To be consistent, we will defer execution to the /progress endpoint.
    
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
        else:
            return jsonify({"status": "ok", "text": "Transcrição concluída (mock)."})
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

    # Define the worker function
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

    # If job is pending, start it now (Lazy execution for Serverless)
    if job.get("status") == "pending":
        job["status"] = "running"
        threading.Thread(target=run_job, args=(job_id, job["url"], job["ydl_opts"], job), daemon=True).start()

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
    if os.environ.get("VERCEL") == "1":
         return jsonify({"status": "error", "message": "Cannot open server folder on Vercel."}), 400

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
    return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")


@app.route("/favicon.ico")
def favicon_ico():
    return redirect("/favicon.svg", code=302)


HISTORY_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>VoxHub - Histórico</title>
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
    <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
    <script>
      window.SUPABASE_URL = "{{ supabase_url }}";
      window.SUPABASE_KEY = "{{ supabase_key }}";
    </script>
    <style>
      .history-container { 
        max-width: 900px; 
        margin: 0 auto; 
        padding: 32px;
        min-height: 100vh;
      }
      .history-header {
        display: flex;
        align-items: center;
        margin-bottom: 24px;
        gap: 16px;
      }
      .empty-history {
        color: var(--muted);
        text-align: center;
        margin: 36px;
        font-size: 16px;
        display: none;
      }
      .history-list {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 12px;
        overflow: hidden;
      }
      .history-item {
        padding: 16px 20px;
        border-bottom: 1px solid var(--border);
        display: flex;
        align-items: center;
        justify-content: space-between;
        transition: background 0.2s;
      }
      .history-item:last-child { border-bottom: none; }
      .history-item:hover { background: rgba(255,255,255,0.02); }
      
      .back-btn {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        color: var(--muted);
        text-decoration: none;
        font-weight: 500;
        transition: color 0.2s;
        cursor: pointer;
      }
      .back-btn:hover { color: var(--text); }
      
      .format-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        margin-right: 8px;
        background: rgba(255,255,255,0.1);
        color: var(--text);
      }
      .format-mp3 { background: rgba(29, 185, 84, 0.15); color: #1db954; }
      .format-m4a { background: rgba(255, 107, 0, 0.15); color: #ff6b00; }
      .format-rec { background: rgba(225, 48, 108, 0.15); color: #e1306c; }
      .format-txt { background: rgba(66, 133, 244, 0.15); color: #4285f4; }
      
      .meta { font-size: 12px; color: var(--muted); margin-top: 2px; }
      .icon-btn {
        background: none; border: none; color: var(--muted); cursor: pointer; padding: 8px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center; transition: all 0.2s;
      }
      .icon-btn:hover { background: rgba(255,255,255,0.1); color: var(--text); }

      /* Auth Warning */
      #auth-warning {
        background: rgba(255, 179, 2, 0.1);
        border: 1px solid rgba(255, 179, 2, 0.3);
        color: #ffb302;
        padding: 12px;
        border-radius: 8px;
        margin-bottom: 20px;
        text-align: center;
        display: none;
      }
    </style>
  </head>
  <body>
    <div class="history-container">
      <div class="history-header">
        <a href="/" class="back-btn">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5m7-7l-7 7 7 7"/></svg>
          Voltar
        </a>
      </div>
      
      <div id="auth-warning"></div>

      <div class="card">
        <div class="card-header">
          <h2 class="h1">Histórico de Conversões</h2>
        </div>
        <div class="card-body" style="padding:0;">
          <div id="loading" class="empty-history" style="display:block;">Carregando...</div>
          <div id="history-list"></div>
          <div id="empty-msg" class="empty-history">
            Nenhum histórico encontrado.
          </div>
        </div>
      </div>
    </div>

    <script>
      const supabaseClient = window.SUPABASE_URL ? supabase.createClient(window.SUPABASE_URL, window.SUPABASE_KEY) : null;
      const listEl = document.getElementById('history-list');
      const loadingEl = document.getElementById('loading');
      const emptyEl = document.getElementById('empty-msg');
      const authWarning = document.getElementById('auth-warning');
      
      async function loadHistory() {
        if (!supabaseClient) return;
        
        const { data: { user } } = await supabaseClient.auth.getUser();
        
        if (!user) {
            loadingEl.style.display = 'none';
            authWarning.style.display = 'block';
            return;
        }

        const { data, error } = await supabaseClient
          .from('history')
          .select('*')
          .order('created_at', { ascending: false })
          .limit(50);
          
        loadingEl.style.display = 'none';
        
        if (error) {
            console.error(error);
            // Códigos comuns para tabela inexistente: 42P01 (undefined_table) ou status 404
            if (error.code === '42P01' || error.code === 'PGRST301' || (error.message && error.message.includes('404'))) {
                 authWarning.innerHTML = 'Tabela de histórico não encontrada.<br>Por favor, execute o SQL de configuração no painel do Supabase.';
            } else {
                 authWarning.textContent = 'Erro ao carregar histórico: ' + (error.message || 'Desconhecido');
            }
            authWarning.style.display = 'block';
            return;
        }
        
        if (!data || data.length === 0) {
            emptyEl.style.display = 'block';
            return;
        }

        renderList(data);
      }
      
      function renderList(data) {
        listEl.innerHTML = '';
        data.forEach(item => {
             const div = document.createElement('div');
             const fmt = (item.format || 'mp3').toLowerCase();
             div.className = 'history-item';
             
             const badge = `<span class="format-badge format-${fmt}">${fmt.toUpperCase()}</span>`;
             const ts = new Date(item.created_at).toLocaleString();
             
             const dlIcon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 3v10m0 0l4-4m-4 4l-4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M20 21H4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
             
             let isYt = false;
             try { const x = new URL(item.url); isYt = /(^|\\.)youtube\\.com$/.test(x.hostname) || x.hostname === 'youtu.be'; } catch {}

             const action = isYt 
                ? `<a href="/?url=${encodeURIComponent(item.url)}&format=${fmt}" class="icon-btn" title="Baixar novamente">${dlIcon}</a>` 
                : '';

             div.innerHTML = `
                <div>
                  <div style="font-weight:500; margin-bottom:4px; word-break: break-all;">${badge} ${item.url}</div>
                  <div class="meta">${ts}</div>
                </div>
                <div>${action}</div>
             `;
             listEl.appendChild(div);
        });
      }
      
      if (localStorage.getItem('theme') === 'light') {
        document.body.classList.add('theme-light');
      }
      
      loadHistory();
    </script>
  </body>
</html>
"""


@app.route("/history")
def history_page():
    return render_template_string(
        HISTORY_HTML,
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_key=os.environ.get("SUPABASE_KEY", "")
    )


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("PORT", "5000"))
    except Exception:
        port = 5000
    debug_flag = os.environ.get("DEBUG", "1")
    debug = (debug_flag not in ("0", "false", "False"))
    app.run(host=host, port=port, debug=debug)