// Analytics & Cost Dashboard Client
(function () {
  const els = {
    refreshBtn: document.getElementById('analytics-refresh-btn'),
    lastUpdated: document.getElementById('last-updated'),
    filterInput: document.getElementById('activity-filter'),

    // Top KPIs
    kpiCost: document.getElementById('kpi-cost'),
    kpiCostBreakdown: document.getElementById('kpi-cost-breakdown'),
    kpiTokens: document.getElementById('kpi-tokens'),
    kpiTokensSub: document.getElementById('kpi-tokens-sub'),
    kpiRequests: document.getElementById('kpi-requests'),
    kpiRequestsSub: document.getElementById('kpi-requests-sub'),
    kpiMatchRate: document.getElementById('kpi-match-rate'),
    kpiMatchRateBadge: document.getElementById('kpi-match-rate-badge'),
    kpiMatchSub: document.getElementById('kpi-match-sub'),
    kpiEscalations: document.getElementById('kpi-escalations'),
    kpiEscalationBadge: document.getElementById('kpi-escalation-badge'),
    kpiEscalationSub: document.getElementById('kpi-escalation-sub'),

    // LLM
    llmModelPill: document.getElementById('llm-model-pill'),
    llmCostTag: document.getElementById('llm-cost-tag'),
    tokenRatioText: document.getElementById('token-ratio-text'),
    tokenMeterPrompt: document.getElementById('token-meter-prompt'),
    tokenMeterCompletion: document.getElementById('token-meter-completion'),
    llmPromptTokens: document.getElementById('llm-prompt-tokens'),
    llmCompletionTokens: document.getElementById('llm-completion-tokens'),
    llmTotalTokens: document.getElementById('llm-total-tokens'),
    llmAvgTokens: document.getElementById('llm-avg-tokens'),
    llmRates: document.getElementById('llm-rates'),

    // STT
    sttCostTag: document.getElementById('stt-cost-tag'),
    sttCalls: document.getElementById('stt-calls'),
    sttDuration: document.getElementById('stt-duration'),
    sttVolume: document.getElementById('stt-volume'),
    sttRate: document.getElementById('stt-rate'),

    // TTS
    ttsCostTag: document.getElementById('tts-cost-tag'),
    ttsGroqCalls: document.getElementById('tts-groq-calls'),
    ttsGttsCalls: document.getElementById('tts-gtts-calls'),
    ttsChars: document.getElementById('tts-chars'),
    ttsRate: document.getElementById('tts-rate'),

    // RAG
    ragQueries: document.getElementById('rag-queries'),
    ragMatches: document.getElementById('rag-matches'),
    ragNoMatches: document.getElementById('rag-no-matches'),
    topIntentsList: document.getElementById('top-intents-list'),

    // Table
    activityTbody: document.getElementById('activity-tbody'),

    // Status popover
    apiStatus: document.getElementById('api-status'),
    statusSummaryBadge: document.getElementById('status-summary-badge'),
    serviceList: document.getElementById('service-list')
  };

  let allActivities = [];

  function fmtCost(usd) {
    if (usd === undefined || usd === null) return '$0.0000';
    if (usd === 0) return '$0.0000';
    if (usd < 0.0001) return '< $0.0001';
    return '$' + usd.toFixed(4);
  }

  function fmtNum(n) {
    return (n || 0).toLocaleString();
  }

  function fmtBytes(bytes) {
    if (!bytes) return '0 KB';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  }

  function fmtDuration(seconds) {
    if (!seconds) return '0.0s';
    if (seconds < 60) return seconds.toFixed(1) + 's';
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return m + 'm ' + s + 's';
  }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function formatTime(iso) {
    if (!iso) return '-';
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
             ' (' + d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ')';
    } catch (e) {
      return iso.slice(11, 19) || iso;
    }
  }

  async function loadAnalytics() {
    try {
      const res = await fetch('/analytics/summary');
      if (!res.ok) {
        if (res.status === 401) {
          window.location.reload();
          return;
        }
        throw new Error('Failed to load analytics: ' + res.status);
      }
      const data = await res.json();
      renderAnalytics(data);
      els.lastUpdated.textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch (err) {
      els.lastUpdated.textContent = 'Failed to update';
      console.error('Analytics load error:', err);
    }
  }

  function renderAnalytics(data) {
    const totals = data.totals || {};
    const llm = data.llm || {};
    const stt = data.transcription || {};
    const tts = data.tts || {};
    const rag = data.rag || {};
    const handoff = data.handoff || {};

    // 1. Top KPIs
    els.kpiCost.textContent = fmtCost(totals.total_cost_usd);
    els.kpiCostBreakdown.textContent = `LLM: ${fmtCost(llm.cost_usd)} | STT: ${fmtCost(stt.cost_usd)} | TTS: ${fmtCost(tts.cost_usd)}`;

    els.kpiTokens.textContent = fmtNum(llm.total_tokens);
    els.kpiTokensSub.textContent = `${fmtNum(llm.prompt_tokens)} in / ${fmtNum(llm.completion_tokens)} out`;

    els.kpiRequests.textContent = fmtNum(totals.total_requests);
    els.kpiRequestsSub.textContent = `${fmtNum(rag.total_queries)} assist, ${fmtNum(stt.calls)} audio`;

    const matchRate = rag.match_rate_pct || 0;
    els.kpiMatchRate.textContent = matchRate.toFixed(1) + '%';
    els.kpiMatchRateBadge.textContent = matchRate >= 80 ? 'Optimal' : (matchRate >= 50 ? 'Moderate' : 'Low');
    els.kpiMatchRateBadge.className = 'kpi-badge ' + (matchRate >= 70 ? 'success-badge' : 'warning-badge');
    els.kpiMatchSub.textContent = `Avg similarity: ${(rag.avg_similarity || 0).toFixed(3)} (min ${rag.threshold || 0.45})`;

    const escalations = handoff.total_escalations || 0;
    els.kpiEscalations.textContent = fmtNum(escalations);
    els.kpiEscalationBadge.textContent = escalations > 0 ? `${escalations} tickets` : '0 tickets';
    els.kpiEscalationSub.textContent = `${(handoff.escalation_rate_pct || 0).toFixed(1)}% escalation rate`;

    // 2. LLM Card
    els.llmModelPill.textContent = llm.model || 'Groq';
    els.llmCostTag.textContent = fmtCost(llm.cost_usd);
    els.llmPromptTokens.textContent = fmtNum(llm.prompt_tokens);
    els.llmCompletionTokens.textContent = fmtNum(llm.completion_tokens);
    els.llmTotalTokens.textContent = fmtNum(llm.total_tokens);
    els.llmAvgTokens.textContent = (llm.avg_tokens_per_call || 0).toFixed(1);

    const totalTok = (llm.prompt_tokens + llm.completion_tokens) || 1;
    const promptPct = Math.round((llm.prompt_tokens / totalTok) * 100);
    const complPct = 100 - promptPct;
    els.tokenMeterPrompt.style.width = promptPct + '%';
    els.tokenMeterCompletion.style.width = complPct + '%';
    els.tokenRatioText.textContent = `${promptPct}% prompt / ${complPct}% completion`;
    if (llm.rates) {
      els.llmRates.textContent = `$${llm.rates.input_per_1m.toFixed(2)} / $${llm.rates.output_per_1m.toFixed(2)} per 1M`;
    }

    // 3. STT Card
    els.sttCostTag.textContent = fmtCost(stt.cost_usd);
    els.sttCalls.textContent = fmtNum(stt.calls);
    els.sttDuration.textContent = fmtDuration(stt.est_audio_seconds || 0);
    els.sttVolume.textContent = fmtBytes(stt.total_bytes || 0);
    if (stt.rate_per_hour) {
      els.sttRate.textContent = `$${stt.rate_per_hour.toFixed(2)} / hour audio`;
    }

    // 4. TTS Card
    els.ttsCostTag.textContent = fmtCost(tts.cost_usd);
    els.ttsGroqCalls.textContent = fmtNum(tts.groq_calls);
    els.ttsGttsCalls.textContent = fmtNum(tts.gtts_calls);
    els.ttsChars.textContent = fmtNum(tts.total_chars);
    if (tts.rate_per_1m_chars) {
      els.ttsRate.textContent = `$${tts.rate_per_1m_chars.toFixed(2)} / 1M chars (gTTS free)`;
    }

    // 5. RAG Card
    els.ragQueries.textContent = fmtNum(rag.total_queries);
    els.ragMatches.textContent = fmtNum(rag.matched_queries);
    els.ragNoMatches.textContent = fmtNum(rag.no_match_queries);

    const topIntents = data.top_intents || [];
    if (topIntents.length) {
      els.topIntentsList.innerHTML = topIntents.map(item => `
        <span class="intent-chip">
          <span class="intent-chip-name">${escapeHtml(item.intent.replace(/_/g, ' '))}</span>
          <span class="intent-chip-count">${item.count}</span>
        </span>
      `).join('');
    } else {
      els.topIntentsList.innerHTML = '<span class="no-data-hint">No topic data logged yet</span>';
    }

    // 6. Activity Table
    allActivities = data.recent_activity || [];
    renderActivityTable();
  }

  function renderActivityTable() {
    const filter = (els.filterInput.value || '').trim().toLowerCase();
    const rows = allActivities.filter(item => {
      if (!filter) return true;
      const idMatch = (item.request_id || '').toLowerCase().includes(filter);
      const eventMatch = (item.event || '').toLowerCase().includes(filter);
      const intentMatch = (item.intents || []).some(i => i.toLowerCase().includes(filter));
      const engineMatch = (item.tts_engine || '').toLowerCase().includes(filter);
      return idMatch || eventMatch || intentMatch || engineMatch;
    });

    if (!rows.length) {
      els.activityTbody.innerHTML = `<tr><td colspan="8" class="empty-table-cell">No matching requests found</td></tr>`;
      return;
    }

    els.activityTbody.innerHTML = rows.map(r => {
      const isAssist = r.event === 'assist';
      const eventPillCls = isAssist ? 'pill-assist' : 'pill-transcribe';
      const eventLabel = isAssist ? 'Assist / LLM' : 'Audio STT';

      const intentsHtml = (r.intents && r.intents.length)
        ? r.intents.map(i => `<span class="badge-intent">${escapeHtml(i.replace(/_/g, ' '))}</span>`).join(' ')
        : '<span class="text-muted">-</span>';

      const tokensHtml = isAssist
        ? `<span class="tokens-metric" title="Prompt + Completion">${fmtNum(r.prompt_tokens)} <span class="text-muted">/</span> ${fmtNum(r.completion_tokens)}</span>`
        : '<span class="text-muted">-</span>';

      const ttsPill = r.tts_engine
        ? `<span class="engine-pill ${r.tts_engine === 'groq-orpheus' ? 'groq' : 'gtts'}">${escapeHtml(r.tts_engine)}</span>`
        : '<span class="text-muted">none</span>';

      const handoffPill = r.handoff
        ? `<span class="handoff-tag active" title="Ticket: ${escapeHtml(r.ticket_id || 'unassigned')}">Escalated</span>`
        : '<span class="handoff-tag none">No</span>';

      return `<tr>
        <td class="cell-time">${escapeHtml(formatTime(r.ts))}</td>
        <td class="cell-id"><code>${escapeHtml(r.request_id || '-')}</code></td>
        <td><span class="event-pill ${eventPillCls}">${eventLabel}</span></td>
        <td><div class="intent-badges-wrap">${intentsHtml}</div></td>
        <td>${tokensHtml}</td>
        <td>${ttsPill}</td>
        <td>${handoffPill}</td>
        <td style="text-align:right; font-weight:600; font-family:monospace;">${fmtCost(r.cost_usd)}</td>
      </tr>`;
    }).join('');
  }

  // System status check & popover
  async function checkHealth() {
    try {
      const res = await fetch('/health');
      const data = await res.json().catch(() => ({}));
      const services = data.services || {};
      const keys = Object.keys(services);
      const onlineCount = keys.filter(k => services[k].status === 'online').length;
      const totalCount = keys.length;

      if (onlineCount === totalCount && totalCount > 0) {
        els.apiStatus.textContent = 'All systems online';
        els.apiStatus.className = 'status-pill status-up';
        els.apiStatus.title = 'All services online and operational';
        if (els.statusSummaryBadge) {
          els.statusSummaryBadge.textContent = 'Operational';
          els.statusSummaryBadge.className = 'status-summary-badge';
        }
      } else {
        els.apiStatus.textContent = `${onlineCount}/${totalCount} systems online`;
        els.apiStatus.className = 'status-pill status-degraded';
        els.apiStatus.title = `${totalCount - onlineCount} service(s) offline or unconfigured`;
        if (els.statusSummaryBadge) {
          els.statusSummaryBadge.textContent = 'Degraded';
          els.statusSummaryBadge.className = 'status-summary-badge has-offline';
        }
      }

      if (els.serviceList) {
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
      if (els.statusSummaryBadge) {
        els.statusSummaryBadge.textContent = 'Offline';
        els.statusSummaryBadge.className = 'status-summary-badge has-offline';
      }
    }
  }

  // Event handlers
  els.refreshBtn.addEventListener('click', () => {
    loadAnalytics();
    checkHealth();
  });

  els.filterInput.addEventListener('input', () => {
    renderActivityTable();
  });

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

  // Initial load + periodic polling (every 30 seconds)
  loadAnalytics();
  checkHealth();
  setInterval(loadAnalytics, 30000);
  setInterval(checkHealth, 30000);
})();
