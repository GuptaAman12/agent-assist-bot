const els = {
  form: document.getElementById('upload-form'),
  dropzone: document.getElementById('dropzone'),
  fileInput: document.querySelector('input[name="file"]'),
  fileChip: document.getElementById('file-chip'),
  fileName: document.getElementById('file-name'),
  fileClear: document.getElementById('file-clear'),
  submitBtn: document.getElementById('submit-btn'),
  submitLabel: document.getElementById('submit-label'),
  submitSpinner: document.getElementById('submit-spinner'),
  error: document.getElementById('error'),
  stageNote: document.getElementById('stage-note'),
  apiStatus: document.getElementById('api-status'),
  themeToggle: document.getElementById('theme-toggle'),
  iconMoon: document.getElementById('icon-moon'),
  iconSun: document.getElementById('icon-sun'),
  emptyState: document.getElementById('empty-state'),
  resultPanel: document.getElementById('result-panel'),
  transcript: document.getElementById('transcript'),
  intentBadge: document.getElementById('intent-badge'),
  takeoverPill: document.getElementById('takeover-pill'),
  timestamp: document.getElementById('timestamp'),
  response: document.getElementById('response'),
  copyBtn: document.getElementById('copy-btn'),
  sourceText: document.getElementById('source-text'),
  audioCard: document.getElementById('audio-card'),
  audioPlayer: document.getElementById('audio-player'),
  ttsEngineNote: document.getElementById('tts-engine-note'),
  historyCard: document.getElementById('history-card'),
  historyList: document.getElementById('history-list'),
  historyClear: document.getElementById('history-clear'),
  kbCount: document.getElementById('kb-count'),
  kbSearch: document.getElementById('kb-search'),
  kbReloadBtn: document.getElementById('kb-reload-btn'),
  kbList: document.getElementById('kb-list'),
  kbAddForm: document.getElementById('kb-add-form'),
  kbQuestion: document.getElementById('kb-question'),
  kbResponse: document.getElementById('kb-response'),
  kbAddBtn: document.getElementById('kb-add-btn'),
  kbError: document.getElementById('kb-error')
};

let history = [];
let activeIndex = -1;
let current = null;

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function inlineMd(t) {
  return t
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*\n]+)\*/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function renderMarkdown(src) {
  const lines = escapeHtml(src || '').split(/\r?\n/);
  let html = '';
  let listType = null;
  let para = [];

  const closeList = () => {
    if (listType) {
      html += listType === 'ul' ? '</ul>' : '</ol>';
      listType = null;
    }
  };
  const flushPara = () => {
    if (para.length) {
      html += `<p>${para.join('<br>')}</p>`;
      para = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const ulMatch = line.match(/^\s{0,3}[-*+]\s+(.*)$/);
    const olMatch = line.match(/^\s{0,3}\d+[.)]\s+(.*)$/);

    if (ulMatch || olMatch) {
      flushPara();
      const wanted = ulMatch ? 'ul' : 'ol';
      if (listType !== wanted) {
        closeList();
        html += wanted === 'ul' ? '<ul>' : '<ol>';
        listType = wanted;
      }
      html += `<li>${inlineMd((ulMatch || olMatch)[1])}</li>`;
    } else if (line.trim() === '') {
      closeList();
      flushPara();
    } else {
      closeList();
      para.push(inlineMd(line.trim()));
    }
  }
  closeList();
  flushPara();
  return html;
}

async function postJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`);
  }
  return data;
}

function showError(message) {
  els.error.textContent = message;
  els.error.hidden = false;
}

function clearError() {
  els.error.textContent = '';
  els.error.hidden = true;
}

function setStage(text) {
  if (!text) {
    els.stageNote.textContent = '';
    els.stageNote.hidden = true;
  } else {
    els.stageNote.textContent = text;
    els.stageNote.hidden = false;
  }
}

function setBusy(busy) {
  els.submitBtn.disabled = busy || !els.fileInput.files.length;
  els.submitSpinner.hidden = !busy;
  els.submitLabel.textContent = busy ? 'Working…' : 'Transcribe & assist';
}

async function checkHealth() {
  try {
    const res = await fetch('/health');
    if (!res.ok) throw new Error();
    els.apiStatus.textContent = 'API online';
    els.apiStatus.className = 'status-pill status-ok';
  } catch {
    els.apiStatus.textContent = 'API offline';
    els.apiStatus.className = 'status-pill status-down';
  }
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function updateFileChip() {
  const file = els.fileInput.files[0];
  if (file) {
    els.fileName.textContent = `${file.name} (${formatBytes(file.size)})`;
    els.fileChip.hidden = false;
    els.dropzone.style.display = 'none';
  } else {
    els.fileChip.hidden = true;
    els.dropzone.style.display = '';
  }
  setBusy(false);
}

function showResult(item) {
  current = item;
  activeIndex = history.indexOf(item);
  renderHistory();

  els.emptyState.hidden = true;
  els.resultPanel.hidden = false;

  els.transcript.textContent = item.transcript;
  els.intentBadge.textContent = item.intent.replace(/_/g, ' ');
  els.takeoverPill.textContent = item.aiTakeover ? 'AI voice takeover' : 'Agent assisted';
  els.takeoverPill.className = 'takeover-pill ' + (item.aiTakeover ? 'takeover-yes' : 'takeover-no');
  els.timestamp.textContent = new Date(item.at).toLocaleString();
  els.response.innerHTML = item.responseHtml;
  els.sourceText.textContent = item.source;

  if (item.audioUrl) {
    els.audioCard.hidden = false;
    els.audioPlayer.src = item.audioUrl;
    els.ttsEngineNote.textContent = item.ttsEngine === 'gtts-fallback'
      ? 'Voice engine: gTTS fallback (Groq Orpheus unavailable — accept terms at console.groq.com to enable it)'
      : 'Voice engine: Groq Orpheus';
    els.audioPlayer.load();
  } else {
    els.audioCard.hidden = true;
    els.audioPlayer.removeAttribute('src');
  }
}

els.copyBtn.addEventListener('click', async () => {
  if (!current) return;
  try {
    await navigator.clipboard.writeText(current.responseRaw);
    els.copyBtn.textContent = 'Copied';
  } catch {
    els.copyBtn.textContent = 'Copy failed';
  }
  setTimeout(() => { els.copyBtn.textContent = 'Copy'; }, 1500);
});

function renderHistory() {
  els.historyList.innerHTML = '';
  history.forEach((item, i) => {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'history-item' + (i === activeIndex ? ' active' : '');
    const top = document.createElement('div');
    top.className = 'hi-top';
    const intentSpan = document.createElement('span');
    intentSpan.textContent = item.intent.replace(/_/g, ' ');
    const timeSpan = document.createElement('span');
    timeSpan.textContent = new Date(item.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    top.append(intentSpan, timeSpan);
    const snippet = document.createElement('div');
    snippet.className = 'hi-snippet';
    snippet.textContent = item.transcript;
    btn.title = item.transcript;
    btn.append(top, snippet);
    btn.addEventListener('click', () => showResult(item));
    li.appendChild(btn);
    els.historyList.appendChild(li);
  });
}

function pushHistory(item) {
  history.unshift(item);
  if (history.length > 12) history.pop();
  els.historyCard.hidden = false;
  renderHistory();
}

els.historyClear.addEventListener('click', () => {
  history = [];
  activeIndex = -1;
  current = null;
  els.historyCard.hidden = true;
  els.resultPanel.hidden = true;
  els.emptyState.hidden = false;
});

els.dropzone.addEventListener('click', () => els.fileInput.click());
els.dropzone.addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    els.fileInput.click();
  }
});
els.dropzone.addEventListener('dragover', e => {
  e.preventDefault();
  els.dropzone.classList.add('dragover');
});
els.dropzone.addEventListener('dragleave', () => els.dropzone.classList.remove('dragover'));
els.dropzone.addEventListener('drop', e => {
  e.preventDefault();
  els.dropzone.classList.remove('dragover');
  if (e.dataTransfer.files.length) {
    els.fileInput.files = e.dataTransfer.files;
    updateFileChip();
  }
});
els.fileInput.addEventListener('change', updateFileChip);
els.fileClear.addEventListener('click', () => {
  els.fileInput.value = '';
  updateFileChip();
});

els.form.addEventListener('submit', async e => {
  e.preventDefault();
  clearError();

  const file = els.fileInput.files[0];
  if (!file) {
    showError('Please choose a .wav file first.');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);

  setBusy(true);
  try {
    setStage('Uploading and transcribing audio…');
    const { transcript, intent } = await postJson('/transcribe/', {
      method: 'POST',
      body: formData
    });

    setStage('Generating AI response…');
    const assist = await postJson('/assist/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript, intent })
    });

    const item = {
      at: Date.now(),
      transcript,
      intent,
      aiTakeover: assist.ai_takeover,
      responseRaw: assist.response,
      responseHtml: renderMarkdown(assist.response),
      source: assist.source || '',
      audioUrl: assist.audio_url || null,
      ttsEngine: assist.tts_engine || null
    };
    pushHistory(item);
    showResult(item);
  } catch (err) {
    showError(err.message);
  } finally {
    setStage(null);
    setBusy(false);
  }
});

function syncThemeIcon() {
  const dark = document.documentElement.getAttribute('data-theme') === 'dark';
  els.iconMoon.hidden = dark;
  els.iconSun.hidden = !dark;
  const label = dark ? 'Switch to light mode' : 'Switch to dark mode';
  els.themeToggle.setAttribute('aria-label', label);
  els.themeToggle.title = label;
}

els.themeToggle.addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('theme', next); } catch {}
  syncThemeIcon();
});

checkHealth();
syncThemeIcon();

let kbEntries = [];

function showKbError(message) {
  els.kbError.textContent = message;
  els.kbError.hidden = false;
}

function clearKbError() {
  els.kbError.textContent = '';
  els.kbError.hidden = true;
}

function renderKb() {
  const filter = els.kbSearch.value.trim().toLowerCase();
  const visible = kbEntries.filter(e =>
    !filter ||
    e.question.toLowerCase().includes(filter) ||
    e.response.toLowerCase().includes(filter)
  );
  els.kbCount.textContent = kbEntries.length;
  els.kbList.innerHTML = '';
  visible.forEach(entry => {
    const li = document.createElement('li');
    li.className = 'kb-item';
    const text = document.createElement('div');
    text.className = 'kb-text';
    const q = document.createElement('span');
    q.className = 'kb-q';
    q.textContent = entry.question || '(no question)';
    const a = document.createElement('span');
    a.className = 'kb-a';
    a.textContent = entry.response;
    text.append(q, a);
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'kb-del';
    del.textContent = '\u00d7';
    del.title = 'Delete this entry';
    del.setAttribute('aria-label', 'Delete entry');
    del.addEventListener('click', async () => {
      clearKbError();
      try {
        await postJson(`/kb/${entry.id}`, { method: 'DELETE' });
        kbEntries = kbEntries.filter(e => e.id !== entry.id);
        renderKb();
      } catch (err) {
        showKbError(err.message);
      }
    });
    li.append(text, del);
    els.kbList.appendChild(li);
  });
}

async function refreshKb() {
  clearKbError();
  try {
    const data = await postJson('/kb', {});
    kbEntries = data.entries;
    renderKb();
  } catch (err) {
    showKbError(err.message);
  }
}

els.kbSearch.addEventListener('input', renderKb);

els.kbReloadBtn.addEventListener('click', async () => {
  clearKbError();
  try {
    await postJson('/kb/reload', { method: 'POST' });
    await refreshKb();
  } catch (err) {
    showKbError(err.message);
  }
});

els.kbAddForm.addEventListener('submit', async e => {
  e.preventDefault();
  clearKbError();
  const response = els.kbResponse.value.trim();
  if (!response) {
    showKbError('Answer text is required.');
    return;
  }
  els.kbAddBtn.disabled = true;
  try {
    const created = await postJson('/kb', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: els.kbQuestion.value.trim(), response })
    });
    kbEntries.push(created);
    renderKb();
    els.kbQuestion.value = '';
    els.kbResponse.value = '';
  } catch (err) {
    showKbError(err.message);
  } finally {
    els.kbAddBtn.disabled = false;
  }
});

refreshKb();
