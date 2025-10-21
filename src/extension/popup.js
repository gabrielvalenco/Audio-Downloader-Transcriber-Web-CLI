const urlInput = document.getElementById('url');
const fmtSelect = document.getElementById('format');
const serverInput = document.getElementById('server');
const useCurrentBtn = document.getElementById('use-current');
const downloadBtn = document.getElementById('download');

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

downloadBtn?.addEventListener('click', () => {
  const url = (urlInput.value || '').trim();
  const fmt = (fmtSelect.value || 'mp3').toLowerCase();
  const server = (serverInput.value || '').trim().replace(/\/$/, '');
  if (!url) {
    urlInput.focus();
    urlInput.style.borderColor = '#ef4444';
    return;
  }
  if (!server) {
    serverInput.focus();
    serverInput.style.borderColor = '#ef4444';
    return;
  }
  const target = `${server}/?url=${encodeURIComponent(url)}&format=${encodeURIComponent(fmt)}&submit=1`;
  chrome.tabs.create({ url: target });
});