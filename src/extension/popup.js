const urlInput = document.getElementById('url');
const fmtSelect = document.getElementById('format');
const serverInput = document.getElementById('server');
const useCurrentBtn = document.getElementById('use-current');
const downloadBtn = document.getElementById('download');

// Oculta o campo de servidor por padrão (mantém no DOM para uso avançado)
const serverRow = document.getElementById('server-row');
if (serverRow) serverRow.style.display = 'none';

// Persistência (chrome.storage) com fallback seguro
async function getStoredServer() {
  try {
    const data = await chrome.storage?.local.get(['server']);
    return (data && data.server) || '';
  } catch (_) {
    return '';
  }
}

async function setStoredServer(value) {
  try {
    await chrome.storage?.local.set({ server: value });
  } catch (_) {
    // ignore
  }
}

// Ping com timeout usando AbortController
async function ping(url, timeoutMs = 800) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort('timeout'), timeoutMs);
  try {
    const res = await fetch(url, { method: 'GET', cache: 'no-store', signal: ctrl.signal });
    return res.ok;
  } catch (_) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function autoDetectServer() {
  const a = 'http://127.0.0.1:5000';
  const b = 'http://localhost:5000';
  // Testar favicon.svg pois existe no app
  const [okA, okB] = await Promise.all([
    ping(a + '/favicon.svg').catch(() => false),
    ping(b + '/favicon.svg').catch(() => false)
  ]);
  if (okA) return a;
  if (okB) return b;
  // Fallback padrão
  return a;
}

async function initServer() {
  // 1) Tenta storage
  let server = (await getStoredServer()) || '';
  // 2) Se vazio, tenta auto-detecção rápida
  if (!server) {
    server = await autoDetectServer();
    await setStoredServer(server);
  }
  // 3) Preenche input (mesmo oculto) para manter compatibilidade
  if (serverInput) {
    serverInput.value = server;
  }
}

// Inicializa sem bloquear UI
initServer().catch(() => {});

useCurrentBtn?.addEventListener('click', async () => {
  try {
    const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    const t = tabs && tabs[0];
    if (t && t.url) {
      urlInput.value = t.url;
    }
  } catch (e) {
    console.warn('Falha ao obter aba atual:', e);
  }
});

// Fluxo de abrir o app já com submit=1

downloadBtn?.addEventListener('click', async () => {
  const url = (urlInput.value || '').trim();
  const fmt = (fmtSelect.value || 'mp3').toLowerCase();

  if (!url) {
    urlInput.focus();
    urlInput.style.borderColor = '#ef4444';
    return;
  }

  let server = (serverInput?.value || '').trim().replace(/\/$/, '');
  if (!server) {
    server = (await getStoredServer()) || 'http://127.0.0.1:5000';
  }
  // Normaliza e persiste
  server = server.replace(/\/$/, '');
  await setStoredServer(server);

  const target = `${server}/?url=${encodeURIComponent(url)}&format=${encodeURIComponent(fmt)}&submit=1`;
  chrome.tabs.create({ url: target });
});