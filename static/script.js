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
  statusSummaryBadge: document.getElementById('status-summary-badge'),
  serviceList: document.getElementById('service-list'),
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
  handoffBanner: document.getElementById('handoff-banner'),
  handoffText: document.getElementById('handoff-text'),
  handoffTicket: document.getElementById('handoff-ticket'),
  recordBtn: document.getElementById('record-btn'),
  recordLabel: document.getElementById('record-label'),
  recordingBar: document.getElementById('recording-bar'),
  recordTimer: document.getElementById('record-timer'),
  recordStopBtn: document.getElementById('record-stop-btn'),
  recordVisualizer: document.getElementById('record-visualizer'),
  voiceSelect: document.getElementById('voice-select'),
  audioDownloadBtn: document.getElementById('audio-download-btn'),
  resultsToolbar: document.getElementById('results-toolbar'),
  viewCardsBtn: document.getElementById('view-cards-btn'),
  viewChatBtn: document.getElementById('view-chat-btn'),
  exportTranscriptBtn: document.getElementById('export-transcript-btn'),
  autoplayToggle: document.getElementById('autoplay-toggle'),
  sentimentPill: document.getElementById('sentiment-pill'),
  editedIndicator: document.getElementById('edited-indicator'),
  editDraftBtn: document.getElementById('edit-draft-btn'),
  responseEditWrap: document.getElementById('response-edit-wrap'),
  responseEditInput: document.getElementById('response-edit-input'),
  saveDraftBtn: document.getElementById('save-draft-btn'),
  cancelDraftBtn: document.getElementById('cancel-draft-btn'),
  audioMuteBtn: document.getElementById('audio-mute-btn'),
  muteIconUnmuted: document.getElementById('mute-icon-unmuted'),
  muteIconMuted: document.getElementById('mute-icon-muted'),
  muteBtnText: document.getElementById('mute-btn-text'),
  voiceVisualizer: document.getElementById('voice-visualizer'),
  chatTimelinePanel: document.getElementById('chat-timeline-panel'),
  chatCountBadge: document.getElementById('chat-count-badge'),
  chatStreamList: document.getElementById('chat-stream-list')
};

let history = [];
let activeIndex = -1;
let current = null;
let currentView = localStorage.getItem('agent_view_mode') || 'cards';
let isVoiceMuted = localStorage.getItem('agent_muted') === 'true';
let voicePlayAnimId = null;

let mediaRecorder = null;
let mediaStream = null;
let mediaChunks = [];
let recordStartTime = 0;
let recordTimerId = null;

function detectSentiment(text) {
  const t = (text || '').toLowerCase();
  const urgentKeywords = [
    'urgent', 'immediately', 'asap', 'emergency', 'manager', 'supervisor',
    'lawyer', 'legal', 'sue', 'police', 'fraud', 'scam', 'stolen',
    'unacceptable', 'worst service', 'ridiculous', 'robbed'
  ];
  if (urgentKeywords.some(w => t.includes(w))) {
    return { label: 'Urgent', class: 'sentiment-urgent', emoji: '🔴' };
  }

  const frustratedKeywords = [
    'angry', 'annoyed', 'terrible', 'horrible', 'awful', 'waste',
    'useless', 'broken', 'failed', 'never works', 'disappointed', 'fed up',
    'hate', 'garbage', 'trash', 'screwed', 'lied', 'stupid', 'not working'
  ];
  if (frustratedKeywords.some(w => t.includes(w))) {
    return { label: 'Frustrated', class: 'sentiment-frustrated', emoji: '🟠' };
  }

  const positiveKeywords = [
    'thank', 'thanks', 'great', 'awesome', 'excellent', 'wonderful',
    'perfect', 'helpful', 'appreciate', 'love', 'good job', 'solved', 'works now'
  ];
  if (positiveKeywords.some(w => t.includes(w))) {
    return { label: 'Satisfied', class: 'sentiment-positive', emoji: '🟢' };
  }

  return { label: 'Neutral', class: 'sentiment-neutral', emoji: '⚪' };
}

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
  if (!els.apiStatus) return;
  try {
    const res = await fetch('/health');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const services = data.services || {};
    const keys = Object.keys(services);

    let onlineCount = 0;
    keys.forEach(k => {
      if (services[k].status === 'online') onlineCount++;
    });

    const isAllOnline = keys.length > 0 && onlineCount === keys.length;
    if (isAllOnline) {
      els.apiStatus.textContent = 'All systems online';
      els.apiStatus.className = 'status-pill status-ok';
      els.apiStatus.title = 'All systems online (hover for details)';
    } else if (onlineCount > 0) {
      els.apiStatus.textContent = `${onlineCount}/${keys.length} systems online`;
      els.apiStatus.className = 'status-pill status-degraded';
      els.apiStatus.title = `${keys.length - onlineCount} system(s) offline (hover for details)`;
    } else {
      els.apiStatus.textContent = 'Systems offline';
      els.apiStatus.className = 'status-pill status-down';
      els.apiStatus.title = 'All systems offline';
    }

    if (els.statusSummaryBadge) {
      els.statusSummaryBadge.textContent = `${onlineCount}/${keys.length} online`;
      els.statusSummaryBadge.className = `status-summary-badge ${isAllOnline ? 'all-ok' : 'has-offline'}`;
    }

    if (els.serviceList && keys.length) {
      els.serviceList.innerHTML = keys.map(k => {
        const s = services[k];
        const isOnline = s.status === 'online';
        const cls = isOnline ? 'online' : 'offline';
        const label = isOnline ? 'Online' : 'Offline';
        return `<li class="service-item">
          <div class="service-info">
            <span class="service-dot ${cls}"></span>
            <div class="service-text">
              <span class="service-name">${escapeHtml(s.name || k)}</span>
              <span class="service-desc">${escapeHtml(s.description || '')}</span>
            </div>
          </div>
          <span class="service-status-pill ${cls}">${label}</span>
        </li>`;
      }).join('');
    }
  } catch (err) {
    els.apiStatus.textContent = 'Systems offline';
    els.apiStatus.className = 'status-pill status-down';
    els.apiStatus.title = 'Backend server offline';
    if (els.statusSummaryBadge) {
      els.statusSummaryBadge.textContent = 'Offline';
      els.statusSummaryBadge.className = 'status-summary-badge has-offline';
    }
    if (els.serviceList) {
      els.serviceList.innerHTML = `<li class="service-item">
        <div class="service-info">
          <span class="service-dot offline"></span>
          <div class="service-text">
            <span class="service-name">API Server</span>
            <span class="service-desc">Unreachable</span>
          </div>
        </div>
        <span class="service-status-pill offline">Offline</span>
      </li>`;
    }
  }
}

const statusWrapper = els.apiStatus?.closest('.system-status-wrapper');
if (statusWrapper) {
  els.apiStatus.addEventListener('click', (e) => {
    e.stopPropagation();
    statusWrapper.classList.toggle('is-open');
  });
  document.addEventListener('click', (e) => {
    if (!statusWrapper.contains(e.target)) {
      statusWrapper.classList.remove('is-open');
    }
  });
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
  if (els.resultsToolbar) els.resultsToolbar.hidden = false;

  if (currentView === 'cards') {
    els.resultPanel.hidden = false;
    if (els.chatTimelinePanel) els.chatTimelinePanel.hidden = true;
  } else {
    els.resultPanel.hidden = true;
    if (els.chatTimelinePanel) {
      els.chatTimelinePanel.hidden = false;
      renderChatStream();
    }
  }

  els.transcript.textContent = item.transcript;
  els.intentBadge.textContent = item.intent.replace(/_/g, ' ');

  const sentiment = item.sentiment || detectSentiment(item.transcript);
  item.sentiment = sentiment;
  if (els.sentimentPill) {
    els.sentimentPill.className = 'sentiment-pill ' + sentiment.class;
    els.sentimentPill.textContent = `${sentiment.emoji} ${sentiment.label}`;
    els.sentimentPill.hidden = false;
  }

  els.takeoverPill.textContent = item.aiTakeover ? 'AI voice takeover' : 'Agent assisted';
  els.takeoverPill.className = 'takeover-pill ' + (item.aiTakeover ? 'takeover-yes' : 'takeover-no');
  els.timestamp.textContent = new Date(item.at).toLocaleString();
  els.response.innerHTML = item.responseHtml;

  if (els.editedIndicator) {
    els.editedIndicator.hidden = !item.edited;
  }
  if (els.responseEditWrap) {
    els.responseEditWrap.hidden = true;
    els.response.hidden = false;
  }

  const feedbackRow = document.getElementById('feedback-row');
  if (feedbackRow) {
    feedbackRow.hidden = false;
    document.getElementById('feedback-up').classList.remove('active');
    document.getElementById('feedback-down').classList.remove('active');
    document.getElementById('feedback-up').disabled = false;
    document.getElementById('feedback-down').disabled = false;
    document.getElementById('feedback-thanks').hidden = true;
  }

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

  if (item.handoff) {
    els.handoffBanner.hidden = false;
    if (item.ticketId) {
      els.handoffText.textContent = `A human agent has been notified - ticket #${item.ticketId}.`;
      els.handoffTicket.textContent = '';
    } else {
      els.handoffText.textContent = 'A human agent has been notified - ticket opened.';
      els.handoffTicket.textContent = '';
    }
  } else {
    els.handoffBanner.hidden = true;
  }

  if (item.audioUrl) {
    els.audioCard.hidden = false;
    els.audioPlayer.src = item.audioUrl;
    const voiceName = item.voice || (els.voiceSelect ? els.voiceSelect.value : 'troy');
    els.ttsEngineNote.textContent = item.ttsEngine === 'gtts-fallback'
      ? 'Voice engine: gTTS fallback (Groq Orpheus unavailable - accept terms at console.groq.com to enable it)'
      : `Voice engine: Groq Orpheus (${voiceName})`;

    // Preserve active playback rate
    const activeSpeedBtn = document.querySelector('.speed-btn.active');
    const speed = activeSpeedBtn ? parseFloat(activeSpeedBtn.dataset.speed) || 1 : 1;
    els.audioPlayer.playbackRate = speed;
    els.audioPlayer.muted = isVoiceMuted;
    updateMuteUI(isVoiceMuted);

    if (els.audioDownloadBtn) {
      els.audioDownloadBtn.href = item.audioUrl;
      const safeIntent = (item.intent || 'response').replace(/[^a-zA-Z0-9_-]/g, '_');
      els.audioDownloadBtn.download = `ai_voice_${safeIntent}.wav`;
    }
    els.audioPlayer.load();

    const shouldAutoplay = els.autoplayToggle ? els.autoplayToggle.checked : true;
    if (shouldAutoplay && !isVoiceMuted) {
      els.audioPlayer.play().catch(() => {});
    }
  } else {
    els.audioCard.hidden = true;
    els.audioPlayer.removeAttribute('src');
    if (els.audioDownloadBtn) {
      els.audioDownloadBtn.removeAttribute('href');
    }
  }

  saveSessionState();
}

els.copyBtn.addEventListener('click', async () => {
  if (!current) return;
  try {
    await navigator.clipboard.writeText(current.responseRaw);
    els.copyBtn.textContent = 'Copied';
  } catch {
    els.copyBtn.textContent = 'Copy failed';
  }
  setTimeout(() => els.copyBtn.textContent = 'Copy', 2000);
});

/* Human Agent Draft & Edit Mode */
if (els.editDraftBtn) {
  els.editDraftBtn.addEventListener('click', () => {
    if (!current) return;
    const isHidden = els.responseEditWrap.hidden;
    if (isHidden) {
      els.responseEditInput.value = current.responseRaw || '';
      els.responseEditWrap.hidden = false;
      els.response.hidden = true;
      els.responseEditInput.focus();
    } else {
      els.responseEditWrap.hidden = true;
      els.response.hidden = false;
    }
  });
}

if (els.cancelDraftBtn) {
  els.cancelDraftBtn.addEventListener('click', () => {
    els.responseEditWrap.hidden = true;
    els.response.hidden = false;
  });
}

if (els.saveDraftBtn) {
  els.saveDraftBtn.addEventListener('click', () => {
    if (!current) return;
    const updated = els.responseEditInput.value.trim();
    if (!updated) return;
    current.responseRaw = updated;
    current.responseHtml = renderMarkdown(updated);
    current.edited = true;
    els.response.innerHTML = current.responseHtml;
    if (els.editedIndicator) els.editedIndicator.hidden = false;
    els.responseEditWrap.hidden = true;
    els.response.hidden = false;
    saveSessionState();
    if (currentView === 'chat') renderChatStream();
  });
}

/* Audio Mute & Autoplay Setup */
function updateMuteUI(muted) {
  if (els.muteIconUnmuted && els.muteIconMuted && els.muteBtnText) {
    els.muteIconUnmuted.hidden = muted;
    els.muteIconMuted.hidden = !muted;
    els.muteBtnText.textContent = muted ? 'Unmute' : 'Mute';
    if (els.audioMuteBtn) {
      els.audioMuteBtn.title = muted ? 'Unmute audio playback' : 'Mute audio playback';
    }
  }
}

if (els.audioMuteBtn) {
  els.audioMuteBtn.addEventListener('click', () => {
    isVoiceMuted = !isVoiceMuted;
    if (els.audioPlayer) els.audioPlayer.muted = isVoiceMuted;
    localStorage.setItem('agent_muted', isVoiceMuted ? 'true' : 'false');
    updateMuteUI(isVoiceMuted);
  });
}

if (els.autoplayToggle) {
  const savedAutoplay = localStorage.getItem('agent_autoplay');
  els.autoplayToggle.checked = savedAutoplay !== 'false';
  els.autoplayToggle.addEventListener('change', () => {
    localStorage.setItem('agent_autoplay', els.autoplayToggle.checked ? 'true' : 'false');
  });
}

/* View Mode Switching (Cards vs Chat Stream) */
function switchView(view) {
  currentView = view;
  localStorage.setItem('agent_view_mode', view);
  if (els.viewCardsBtn && els.viewChatBtn) {
    els.viewCardsBtn.classList.toggle('active', view === 'cards');
    els.viewChatBtn.classList.toggle('active', view === 'chat');
  }

  if (history.length > 0) {
    els.emptyState.hidden = true;
    if (els.resultsToolbar) els.resultsToolbar.hidden = false;
    if (view === 'cards') {
      els.resultPanel.hidden = false;
      if (els.chatTimelinePanel) els.chatTimelinePanel.hidden = true;
    } else {
      els.resultPanel.hidden = true;
      if (els.chatTimelinePanel) {
        els.chatTimelinePanel.hidden = false;
        renderChatStream();
      }
    }
  } else {
    els.resultPanel.hidden = true;
    if (els.chatTimelinePanel) els.chatTimelinePanel.hidden = true;
    els.emptyState.hidden = false;
    if (els.resultsToolbar) els.resultsToolbar.hidden = true;
  }
}

if (els.viewCardsBtn) els.viewCardsBtn.addEventListener('click', () => switchView('cards'));
if (els.viewChatBtn) els.viewChatBtn.addEventListener('click', () => switchView('chat'));

/* Export Transcript Log */
function exportTranscriptLog() {
  if (!history || history.length === 0) {
    showError('No conversation turns in this session to export.');
    return;
  }
  const dateStr = new Date().toLocaleString();
  const chronological = [...history].reverse();
  const md = [
    `# 🎙️ Customer Call Transcript & AI Resolution Log`,
    `*Session Exported: ${dateStr}*`,
    `*Total Dialog Turns: ${history.length}*`,
    `\n---\n`,
    chronological.map((turn, i) => {
      const turnNum = i + 1;
      const time = new Date(turn.at).toLocaleTimeString();
      const s = turn.sentiment ? `${turn.sentiment.emoji} ${turn.sentiment.label}` : '⚪ Neutral';
      const type = turn.aiTakeover ? `AI Voice Takeover (${turn.voice || 'Troy'})` : 'Agent Assisted';
      const handoffLine = turn.handoff ? `\n> **Escalation**: Ticket #${turn.ticketId || 'Pending'}` : '';
      const sourcesLine = turn.sources && turn.sources.length ? `\n> **KB Sources**: ${turn.sources.join(' | ')}` : '';
      const editedLine = turn.edited ? `\n> *(Draft modified by human agent)*` : '';

      return `## Turn ${turnNum} — ${time}
- **Intent**: \`${turn.intent || 'unknown'}\`
- **Customer Sentiment**: ${s}
- **Resolution Type**: ${type}${handoffLine}${sourcesLine}${editedLine}

### Customer:
> "${turn.transcript}"

### Assistant Response:
${turn.responseRaw}
`;
    }).join('\n---\n')
  ].join('\n');

  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `call_transcript_${new Date().toISOString().slice(0, 10)}_${Date.now().toString().slice(-4)}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

if (els.exportTranscriptBtn) {
  els.exportTranscriptBtn.addEventListener('click', exportTranscriptLog);
}

/* Chat Stream Timeline Rendering */
function renderChatStream() {
  if (!els.chatStreamList || !els.chatCountBadge) return;
  els.chatCountBadge.textContent = `${history.length} turn${history.length === 1 ? '' : 's'}`;
  els.chatStreamList.innerHTML = '';

  const chronological = [...history].reverse();

  chronological.forEach(item => {
    const turn = document.createElement('div');
    turn.className = 'chat-turn';

    const sentiment = item.sentiment || detectSentiment(item.transcript);

    // Customer message bubble
    const userMsg = document.createElement('div');
    userMsg.className = 'chat-bubble chat-bubble-user';
    userMsg.innerHTML = `
      <div class="chat-bubble-head">
        <span class="chat-role-user">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          Customer
        </span>
        <div style="display:flex;align-items:center;gap:6px;">
          <span class="sentiment-pill ${sentiment.class}">${sentiment.emoji} ${sentiment.label}</span>
          <span class="intent-badge">${escapeHtml((item.intent || 'unknown').replace(/_/g, ' '))}</span>
        </div>
      </div>
      <div class="chat-bubble-content">${escapeHtml(item.transcript)}</div>
      <div class="chat-bubble-meta">
        <span>${new Date(item.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      </div>
    `;

    // Agent response message bubble
    const botMsg = document.createElement('div');
    botMsg.className = 'chat-bubble chat-bubble-agent';
    const isVoice = item.aiTakeover && item.audioUrl;
    const roleTitle = item.aiTakeover ? `AI Voice Assistant (${item.voice || 'Troy'})` : 'Agent Assist Bot';
    const editedBadge = item.edited ? '<span class="badge-edited">Edited</span>' : '';

    let audioControlsHtml = '';
    if (isVoice) {
      audioControlsHtml = `
        <div style="margin-top:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
          <audio controls src="${item.audioUrl}" style="height:32px;max-width:240px;"></audio>
          <span class="chat-voice-pill">🔊 Spoken Resolution</span>
        </div>
      `;
    }

    let sourcesHtml = '';
    if (item.sources && item.sources.length) {
      sourcesHtml = `
        <details style="margin-top:8px;font-size:12px;color:var(--muted);cursor:pointer;">
          <summary style="font-weight:600;">KB Sources (${item.sources.length})</summary>
          <ul style="margin:6px 0 0 16px;padding:0;">
            ${item.sources.map(s => `<li>${escapeHtml(s)}</li>`).join('')}
          </ul>
        </details>
      `;
    }

    let handoffHtml = '';
    if (item.handoff) {
      handoffHtml = `<div style="margin-top:6px;font-size:11.5px;color:var(--danger);font-weight:600;">⚠️ Escalated to human agent ${item.ticketId ? `(#${item.ticketId})` : ''}</div>`;
    }

    const origIdx = history.indexOf(item);
    botMsg.innerHTML = `
      <div class="chat-bubble-head">
        <span class="chat-role-agent">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v1a7 7 0 0 1-14 0v-1"/></svg>
          ${roleTitle} ${editedBadge}
        </span>
        <button type="button" class="chat-inspect-btn" data-idx="${origIdx}">Inspect Card</button>
      </div>
      <div class="chat-bubble-content response-prose">${item.responseHtml || renderMarkdown(item.responseRaw)}</div>
      ${sourcesHtml}
      ${audioControlsHtml}
      ${handoffHtml}
      <div class="chat-bubble-meta">
        <span>${new Date(item.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
        ${typeof item.kbScore === 'number' ? `<span>• Match ${(item.kbScore * 100).toFixed(0)}%</span>` : ''}
      </div>
    `;

    turn.append(userMsg, botMsg);
    els.chatStreamList.appendChild(turn);
  });

  els.chatStreamList.querySelectorAll('.chat-inspect-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.idx, 10);
      if (idx >= 0 && history[idx]) {
        switchView('cards');
        showResult(history[idx]);
      }
    });
  });

  if (els.chatTimelinePanel) {
    els.chatTimelinePanel.scrollTop = els.chatTimelinePanel.scrollHeight;
  }
}

/* Active Voice Playback Waveform Visualizer */
function initVoiceVisualizer() {
  const canvas = els.voiceVisualizer;
  if (!canvas || !els.audioPlayer) return;
  const ctx = canvas.getContext('2d');

  function drawIdle() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const count = 16;
    const barWidth = 3;
    const gap = 5;
    const totalW = count * (barWidth + gap) - gap;
    let x = Math.max(0, (canvas.width - totalW) / 2);
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    ctx.fillStyle = isDark ? 'rgba(34, 211, 238, 0.25)' : 'rgba(8, 145, 178, 0.25)';
    for (let i = 0; i < count; i++) {
      const h = 3;
      const y = (canvas.height - h) / 2;
      ctx.fillRect(x, y, barWidth, h);
      x += barWidth + gap;
    }
  }

  function startAnimation() {
    if (voicePlayAnimId) cancelAnimationFrame(voicePlayAnimId);
    let phase = 0;

    function frame() {
      if (els.audioPlayer.paused || els.audioPlayer.ended) {
        drawIdle();
        return;
      }
      voicePlayAnimId = requestAnimationFrame(frame);
      phase += 0.15;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const count = 16;
      const barWidth = 3;
      const gap = 5;
      const totalW = count * (barWidth + gap) - gap;
      let x = Math.max(0, (canvas.width - totalW) / 2);
      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

      for (let i = 0; i < count; i++) {
        const s1 = Math.sin(phase + i * 0.45);
        const s2 = Math.cos(phase * 0.75 + i * 0.3);
        const norm = Math.max(0.12, (s1 * 0.5 + s2 * 0.5 + 1) / 2);
        const h = Math.max(3, Math.round(norm * (canvas.height - 4)));
        const y = Math.round((canvas.height - h) / 2);

        const grad = ctx.createLinearGradient(0, y, 0, y + h);
        if (isDark) {
          grad.addColorStop(0, '#22d3ee');
          grad.addColorStop(1, '#0284c7');
        } else {
          grad.addColorStop(0, '#0891b2');
          grad.addColorStop(1, '#0369a1');
        }
        ctx.fillStyle = grad;
        ctx.beginPath();
        if (ctx.roundRect) {
          ctx.roundRect(x, y, barWidth, h, 2);
        } else {
          ctx.rect(x, y, barWidth, h);
        }
        ctx.fill();
        x += barWidth + gap;
      }
    }
    frame();
  }

  els.audioPlayer.addEventListener('play', startAnimation);
  els.audioPlayer.addEventListener('pause', () => {
    if (voicePlayAnimId) cancelAnimationFrame(voicePlayAnimId);
    drawIdle();
  });
  els.audioPlayer.addEventListener('ended', () => {
    if (voicePlayAnimId) cancelAnimationFrame(voicePlayAnimId);
    drawIdle();
  });

  drawIdle();
}

['up', 'down'].forEach(type => {
  const btn = document.getElementById(`feedback-${type}`);
  if (btn) {
    btn.addEventListener('click', async () => {
      if (!current) return;
      document.getElementById('feedback-up').disabled = true;
      document.getElementById('feedback-down').disabled = true;
      btn.classList.add('active');
      document.getElementById('feedback-thanks').hidden = false;
      
      try {
        await fetch('/analytics/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            transcript: current.transcript,
            positive: type === 'up'
          })
        });
      } catch (e) {
        console.error('Failed to submit feedback', e);
      }
    });
  }
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

function saveSessionState() {
  try {
    sessionStorage.setItem('dashboard_state', JSON.stringify({ history, activeIndex }));
  } catch {}
}

function pushHistory(item) {
  history.unshift(item);
  if (history.length > 12) history.pop();
  els.historyCard.hidden = false;
  if (els.resultsToolbar) els.resultsToolbar.hidden = false;
  renderHistory();
  saveSessionState();
  if (currentView === 'chat') renderChatStream();
}

function restoreSessionState() {
  let raw = null;
  try { raw = sessionStorage.getItem('dashboard_state'); } catch {}
  if (!raw) return;
  try {
    const saved = JSON.parse(raw);
    if (!Array.isArray(saved.history) || !saved.history.length) return;
    history = saved.history;
    history.forEach(item => {
      if (!item.sentiment) item.sentiment = detectSentiment(item.transcript);
    });
    activeIndex = typeof saved.activeIndex === 'number' ? saved.activeIndex : 0;
    if (activeIndex >= history.length) activeIndex = 0;
    current = history[activeIndex];
    els.historyCard.hidden = false;
    if (els.resultsToolbar) els.resultsToolbar.hidden = false;
    renderHistory();
    if (current) showResult(current);
    switchView(currentView);
  } catch {}
}

els.historyClear.addEventListener('click', () => {
  history = [];
  activeIndex = -1;
  current = null;
  els.historyCard.hidden = true;
  els.resultPanel.hidden = true;
  if (els.chatTimelinePanel) els.chatTimelinePanel.hidden = true;
  if (els.chatStreamList) els.chatStreamList.innerHTML = '';
  if (els.resultsToolbar) els.resultsToolbar.hidden = true;
  els.emptyState.hidden = false;
  try { sessionStorage.removeItem('dashboard_state'); } catch {}
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
    // history[] is newest-first (unshift); backend expects chronological
    // oldest->newest and keeps the tail, so reverse the window.
    const historyForLlm = history.slice(0, 5).reverse().map(h => ({
      transcript: h.transcript,
      response: h.responseRaw
    }));
    const selectedVoice = els.voiceSelect ? els.voiceSelect.value : null;
    const assist = await postJson('/assist/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transcript,
        intent,
        history: historyForLlm,
        voice: selectedVoice
      })
    });

    const sentiment = detectSentiment(transcript);
    const item = {
      at: Date.now(),
      transcript,
      intent,
      sentiment,
      aiTakeover: assist.ai_takeover,
      responseRaw: assist.response,
      responseHtml: renderMarkdown(assist.response),
      sources: Array.isArray(assist.sources) ? assist.sources : (assist.source ? [assist.source] : []),
      kbScore: assist.kb_score,
      audioUrl: assist.audio_url || null,
      ttsEngine: assist.tts_engine || null,
      voice: selectedVoice,
      handoff: !!assist.handoff,
      ticketId: assist.ticket_id || null
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

checkHealth();
initVoiceVisualizer();
restoreSessionState();

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
    stopVisualizer();
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
  startVisualizer(stream);
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

/* Real-time audio waveform visualizer */

let visualizerAudioCtx = null;
let visualizerAnalyser = null;
let visualizerAnimId = null;

function startVisualizer(stream) {
  const canvas = els.recordVisualizer;
  if (!canvas) return;
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    visualizerAudioCtx = new AudioCtx();
    const source = visualizerAudioCtx.createMediaStreamSource(stream);
    visualizerAnalyser = visualizerAudioCtx.createAnalyser();
    visualizerAnalyser.fftSize = 64;
    visualizerAnalyser.smoothingTimeConstant = 0.75;
    source.connect(visualizerAnalyser);

    const ctx = canvas.getContext('2d');
    const bufferLength = visualizerAnalyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function draw() {
      visualizerAnimId = requestAnimationFrame(draw);
      visualizerAnalyser.getByteFrequencyData(dataArray);

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const barCount = 12;
      const barWidth = 4;
      const gap = 3;
      const totalW = barCount * (barWidth + gap) - gap;
      let x = Math.max(0, (canvas.width - totalW) / 2);

      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

      for (let i = 0; i < barCount; i++) {
        const binIndex = Math.min(bufferLength - 1, Math.floor((i / barCount) * (bufferLength * 0.75)));
        const val = dataArray[binIndex] || 0;
        const norm = val / 255;
        const minH = 3;
        const h = Math.max(minH, Math.round(norm * (canvas.height - 4)));
        const y = Math.round((canvas.height - h) / 2);

        const grad = ctx.createLinearGradient(0, y, 0, y + h);
        if (isDark) {
          grad.addColorStop(0, '#22d3ee');
          grad.addColorStop(1, '#0ea5e9');
        } else {
          grad.addColorStop(0, '#0891b2');
          grad.addColorStop(1, '#0284c7');
        }

        ctx.fillStyle = grad;
        ctx.beginPath();
        if (ctx.roundRect) {
          ctx.roundRect(x, y, barWidth, h, 2);
        } else {
          ctx.rect(x, y, barWidth, h);
        }
        ctx.fill();

        x += barWidth + gap;
      }
    }
    draw();
  } catch (err) {
    // Non-critical; visualizer should never break recording
  }
}

function stopVisualizer() {
  if (visualizerAnimId) {
    cancelAnimationFrame(visualizerAnimId);
    visualizerAnimId = null;
  }
  if (visualizerAudioCtx) {
    try { visualizerAudioCtx.close(); } catch (e) {}
    visualizerAudioCtx = null;
  }
  visualizerAnalyser = null;
  if (els.recordVisualizer) {
    const ctx = els.recordVisualizer.getContext('2d');
    if (ctx) ctx.clearRect(0, 0, els.recordVisualizer.width, els.recordVisualizer.height);
  }
}

/* Audio playback speed controls */

document.querySelectorAll('.speed-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const speed = parseFloat(btn.dataset.speed) || 1;
    if (els.audioPlayer) {
      els.audioPlayer.playbackRate = speed;
    }
    document.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});

/* Voice persona selection persistence */

if (els.voiceSelect) {
  const savedVoice = localStorage.getItem('preferred_voice');
  if (savedVoice) {
    els.voiceSelect.value = savedVoice;
  }
  els.voiceSelect.addEventListener('change', () => {
    localStorage.setItem('preferred_voice', els.voiceSelect.value);
  });
}
