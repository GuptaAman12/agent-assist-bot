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
  sourceCard: document.getElementById('source-card'),
  sourcesList: document.getElementById('sources-list'),
  kbConfidence: document.getElementById('kb-confidence'),
  audioCard: document.getElementById('audio-card'),
  audioPlayer: document.getElementById('audio-player'),
  ttsEngineNote: document.getElementById('tts-engine-note'),
  historyCard: document.getElementById('history-card'),
  historyList: document.getElementById('history-list'),
  historyClear: document.getElementById('history-clear'),
  recordBtn: document.getElementById('record-btn'),
  recordLabel: document.getElementById('record-label'),
  recordingBar: document.getElementById('recording-bar'),
  recordTimer: document.getElementById('record-timer'),
  recordStopBtn: document.getElementById('record-stop-btn')
};

let history = [];
let activeIndex = -1;
let current = null;

let mediaRecorder = null;
let mediaStream = null;
let mediaChunks = [];
let recordStartTime = 0;
let recordTimerId = null;

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

  if (item.sources && item.sources.length) {
    els.sourceCard.hidden = false;
    els.sourcesList.innerHTML = '';
    item.sources.forEach((src, i) => {
      const li = document.createElement('li');
      li.className = 'source-item';
      const idx = document.createElement('span');
      idx.className = 'source-index';
      idx.textContent = String(i + 1).padStart(2, '0');
      const text = document.createElement('span');
      text.className = 'source-text';
      text.textContent = src;
      li.append(idx, text);
      els.sourcesList.appendChild(li);
    });
  } else {
    els.sourceCard.hidden = true;
  }

  if (typeof item.kbScore === 'number') {
    els.kbConfidence.textContent = `Match ${(item.kbScore * 100).toFixed(0)}%`;
    els.kbConfidence.hidden = false;
  } else {
    els.kbConfidence.hidden = true;
  }

  if (item.audioUrl) {
    els.audioCard.hidden = false;
    els.audioPlayer.src = item.audioUrl;
    els.ttsEngineNote.textContent = item.ttsEngine === 'gtts-fallback'
      ? 'Voice engine: gTTS fallback (Groq Orpheus unavailable - accept terms at console.groq.com to enable it)'
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
    showError('Please choose an audio file first.');
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
      sources: Array.isArray(assist.sources) ? assist.sources : (assist.source ? [assist.source] : []),
      kbScore: assist.kb_score,
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

/* Live microphone recording */

function formatRecordTime(ms) {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function setRecordingUI(recording) {
  els.recordBtn.hidden = recording;
  els.recordingBar.hidden = !recording;
  els.recordStopBtn.disabled = !recording;
  if (!recording) {
    els.recordTimer.textContent = '0:00';
    if (recordTimerId) { clearInterval(recordTimerId); recordTimerId = null; }
  }
}

function stopMediaTracks() {
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => t.stop());
    mediaStream = null;
  }
}

function writeString(view, offset, str) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}

async function blobToWavFile(blob) {
  const arrayBuffer = await blob.arrayBuffer();
  const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const ctx = new Ctx(1, 1, 44100);
  const audioBuffer = await ctx.decodeAudioData(arrayBuffer);

  const numCh = audioBuffer.numberOfChannels;
  const sampleRate = audioBuffer.sampleRate;
  const numFrames = audioBuffer.length;
  const bytesPerSample = 2;
  const blockAlign = numCh * bytesPerSample;
  const dataSize = numFrames * blockAlign;

  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numCh, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bytesPerSample * 8, true);
  writeString(view, 36, 'data');
  view.setUint32(40, dataSize, true);

  const channels = [];
  for (let c = 0; c < numCh; c++) channels.push(audioBuffer.getChannelData(c));
  let offset = 44;
  for (let i = 0; i < numFrames; i++) {
    for (let c = 0; c < numCh; c++) {
      const s = Math.max(-1, Math.min(1, channels[c][i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }
  }
  return new File([buffer], 'recording.wav', { type: 'audio/wav' });
}

async function audioBufferToMp3File(audioBuffer) {
  const numCh = audioBuffer.numberOfChannels;
  const sampleRate = audioBuffer.sampleRate;
  const kbps = 128;
  const encoder = new lamejs.Mp3Encoder(numCh, sampleRate, kbps);

  const channelData = [];
  for (let c = 0; c < numCh; c++) channelData.push(audioBuffer.getChannelData(c));

  const samplesPerBlock = 1152;
  const mp3Chunks = [];
  const numFrames = audioBuffer.length;
  const asInt16 = floatArr => {
    const out = new Int16Array(floatArr.length);
    for (let i = 0; i < floatArr.length; i++) {
      const s = Math.max(-1, Math.min(1, floatArr[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  };

  for (let offset = 0; offset < numFrames; offset += samplesPerBlock) {
    const block = Math.min(samplesPerBlock, numFrames - offset);
    const left = asInt16(channelData[0].subarray(offset, offset + block));
    if (numCh === 2) {
      const right = asInt16(channelData[1].subarray(offset, offset + block));
      const buf = encoder.encodeBuffer(left, right);
      if (buf.length) mp3Chunks.push(new Int8Array(buf));
    } else {
      const buf = encoder.encodeBuffer(left);
      if (buf.length) mp3Chunks.push(new Int8Array(buf));
    }
  }
  const end = encoder.flush();
  if (end.length) mp3Chunks.push(new Int8Array(end));

  return new File(mp3Chunks, 'recording.mp3', { type: 'audio/mpeg' });
}

function finishRecording() {
  stopMediaTracks();
  setRecordingUI(false);
  if (!mediaChunks.length) {
    showError('Recording was empty. Try again or upload a file instead.');
    return;
  }
  const rawType = (mediaRecorder.mimeType || 'audio/webm').split(';')[0];
  const rawBlob = new Blob(mediaChunks, { type: rawType });
  mediaChunks = [];

  const setFile = file => {
    const dt = new DataTransfer();
    dt.items.add(file);
    els.fileInput.files = dt.files;
    updateFileChip();
  };

  blobToWavFile(rawBlob)
    .then(wavFile => {
      if (window.lamejs) {
        // Decode the raw recording, then re-encode as MP3 - the only format
        // AssemblyAI has been accepting reliably.
        return rawBlob.arrayBuffer().then(ab => {
          const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
          const ctx = new Ctx(1, 1, 44100);
          return ctx.decodeAudioData(ab);
        }).then(buf => audioBufferToMp3File(buf));
      }
      return wavFile;
    })
    .then(file => setFile(file))
    .catch(() => {
      const ext = rawType === 'audio/mp4' ? 'mp4' : 'webm';
      setFile(new File([rawBlob], `recording.${ext}`, { type: rawType }));
    });
}

async function startRecording() {
  clearError();
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    showError('Recording is not supported in this browser. Upload a file instead.');
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    showError('Microphone access denied. Allow mic permission, or upload a file instead.');
    return;
  }
  mediaStream = stream;
  mediaChunks = [];
  const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
    .find(t => MediaRecorder.isTypeSupported(t));
  mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  mediaRecorder.ondataavailable = e => { if (e.data && e.data.size) mediaChunks.push(e.data); };
  mediaRecorder.onstop = finishRecording;
  mediaRecorder.onerror = () => {
    stopMediaTracks();
    setRecordingUI(false);
    showError('Recording failed. Try again or upload a file instead.');
  };
  mediaRecorder.start();
  recordStartTime = Date.now();
  els.recordTimer.textContent = '0:00';
  recordTimerId = setInterval(() => {
    els.recordTimer.textContent = formatRecordTime(Date.now() - recordStartTime);
  }, 500);
  setRecordingUI(true);
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  } else {
    stopMediaTracks();
    setRecordingUI(false);
  }
}

els.recordBtn.addEventListener('click', startRecording);
els.recordStopBtn.addEventListener('click', stopRecording);

if (!(navigator.mediaDevices && window.MediaRecorder)) {
  els.recordBtn.hidden = true;
  els.recordLabel.textContent = 'Recording not supported';
} else {
  els.recordBtn.hidden = false;
}
