const els = {
  count: document.getElementById('kb-count'),
  search: document.getElementById('kb-search'),
  reloadBtn: document.getElementById('kb-reload-btn'),
  list: document.getElementById('kb-list'),
  pagination: document.getElementById('kb-pagination'),
  prevBtn: document.getElementById('kb-prev'),
  nextBtn: document.getElementById('kb-next'),
  pageInfo: document.getElementById('kb-page-info'),
  undoBanner: document.getElementById('kb-undo'),
  undoText: document.getElementById('kb-undo-text'),
  undoBtn: document.getElementById('kb-undo-btn'),
  addForm: document.getElementById('kb-add-form'),
  question: document.getElementById('kb-question'),
  response: document.getElementById('kb-response'),
  addBtn: document.getElementById('kb-add-btn'),
  error: document.getElementById('kb-error'),
  exportBtn: document.getElementById('kb-export-btn'),
  importFile: document.getElementById('kb-import-file'),
  statTotal: document.getElementById('stat-total'),
  statTakeover: document.getElementById('stat-takeover'),
  statHandoff: document.getElementById('stat-handoff'),
  statUnmatched: document.getElementById('stat-unmatched'),
  statKbCount: document.getElementById('stat-kb-count'),
  unmatchedCount: document.getElementById('unmatched-count'),
  unmatchedList: document.getElementById('unmatched-list'),
  unmatchedRefreshBtn: document.getElementById('unmatched-refresh-btn'),
  queueCount: document.getElementById('queue-count'),
  queueList: document.getElementById('queue-list'),
  queueRefreshBtn: document.getElementById('queue-refresh-btn'),
  queueReplayAllBtn: document.getElementById('queue-replay-all-btn'),
  apiStatus: document.getElementById('api-status'),
  statusSummaryBadge: document.getElementById('status-summary-badge'),
  serviceList: document.getElementById('service-list')
};

let entries = [];
let editingId = null;
let total = 0;
let offset = 0;
const PAGE_SIZE = 5;
const SEARCH_LIMIT = 100; // GET /kb caps limit at 100; search refetches up to that
let searchCache = null; // full-list snapshot while a filter is active, else null
let searchTimer = null;
let lastDeleted = null;
let undoTimer = null;

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

function makeInput(className, value, placeholder) {
  const input = document.createElement('input');
  input.className = className;
  input.type = 'text';
  input.value = value;
  input.placeholder = placeholder;
  input.autocomplete = 'off';
  return input;
}

function makeTextArea(className, value, placeholder) {
  const area = document.createElement('textarea');
  area.className = className;
  area.rows = 3;
  area.value = value;
  area.placeholder = placeholder;
  return area;
}

function makeButton(className, text, title) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = className;
  btn.textContent = text;
  btn.title = title;
  return btn;
}

function showUndo(entry) {
  lastDeleted = entry;
  els.undoText.textContent = `Deleted "${(entry.question || entry.response).slice(0, 40)}"`;
  els.undoBanner.hidden = false;
  if (undoTimer) clearTimeout(undoTimer);
  undoTimer = setTimeout(() => { els.undoBanner.hidden = true; lastDeleted = null; }, 10000);
}

els.undoBtn.addEventListener('click', async () => {
  if (!lastDeleted) return;
  clearError();
  try {
    await postJson(`/kb/${lastDeleted.id}/restore`, { method: 'POST' });
    lastDeleted = null;
    els.undoBanner.hidden = true;
    if (undoTimer) clearTimeout(undoTimer);
    await refresh();
  } catch (err) {
    showError(err.message);
  }
});

function renderItem(li, entry) {
  li.innerHTML = '';

  if (editingId === entry.id) {
    li.classList.add('editing');
    const form = document.createElement('div');
    form.className = 'kb-edit-form';

    const q = makeInput('kb-edit-input', entry.question, 'Question (optional)');
    const a = makeTextArea('kb-edit-textarea', entry.response, 'Answer text');

    const actions = document.createElement('div');
    actions.className = 'kb-actions';
    const save = makeButton('btn-primary btn-small', 'Save', 'Save changes to this entry');
    const cancel = makeButton('btn-ghost btn-small', 'Cancel', 'Discard changes');

    save.addEventListener('click', async () => {
      clearError();
      const newResponse = a.value.trim();
      if (!newResponse) {
        showError('Answer text is required.');
        return;
      }
      save.disabled = true;
      try {
        const updated = await postJson(`/kb/${entry.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: q.value.trim(), response: newResponse })
        });
        const idx = entries.findIndex(e => e.id === entry.id);
        if (searchCache) {
          await refresh(); // re-fetch the full-list snapshot
        } else {
          entries[idx] = updated;
          editingId = null;
          render();
        }
      } catch (err) {
        showError(err.message);
        save.disabled = false;
      }
    });

    cancel.addEventListener('click', () => {
      editingId = null;
      clearError();
      render();
    });

    actions.append(save, cancel);
    form.append(q, a, actions);
    li.appendChild(form);
    return;
  }

  li.classList.remove('editing');
  const text = document.createElement('div');
  text.className = 'kb-text';
  const q = document.createElement('span');
  q.className = 'kb-q';
  q.textContent = entry.question || '(no question)';
  const a = document.createElement('span');
  a.className = 'kb-a';
  a.textContent = entry.response;
  text.append(q, a);

  const actions = document.createElement('div');
  actions.className = 'kb-actions';

  const edit = makeButton('btn-ghost btn-small', 'Edit', 'Edit this entry');
  edit.addEventListener('click', () => {
    editingId = entry.id;
    clearError();
    render();
    li.querySelector('.kb-edit-input')?.focus();
  });

  const del = makeButton('kb-del', '\u00d7', 'Delete this entry');
  del.setAttribute('aria-label', 'Delete entry');
  del.addEventListener('click', async () => {
    clearError();
    try {
      const res = await postJson(`/kb/${entry.id}`, { method: 'DELETE' });
      const removed = entries.find(e => e.id === entry.id);
      entries = entries.filter(e => e.id !== entry.id);
      // Adjust offset if page becomes empty
      if (entries.length === 0 && offset > 0) {
        offset = Math.max(0, offset - PAGE_SIZE);
        await refresh();
        if (removed) showUndo(removed);
        return;
      }
      total = res.count;
      if (searchCache) {
        await refresh(); // re-fetch the full-list snapshot
      } else {
        render();
      }
      if (removed) showUndo(removed);
    } catch (err) {
      showError(err.message);
    }
  });

  actions.append(edit, del);
  li.append(text, actions);
}

function render() {
  const filter = els.search.value.trim().toLowerCase();
  // entries holds only the current server page; while filtering, search the
  // full-list snapshot instead so matches on other pages are not missed.
  const source = searchCache || entries;
  const visible = source.filter(e =>
    !filter ||
    (e.question || '').toLowerCase().includes(filter) ||
    e.response.toLowerCase().includes(filter)
  );
  els.count.textContent = total;
  els.list.innerHTML = '';
  // When filtering, show all filtered; otherwise show paginated slice (already paginated from server)
  // If filter active, paginate client-side filtered results
  let toShow = visible;
  if (filter) {
    // Client-side search already filtered; pagination hidden during search
    els.pagination.hidden = true;
  } else {
    els.pagination.hidden = total <= PAGE_SIZE;
    if (!els.pagination.hidden) {
      const start = offset + 1;
      const end = Math.min(offset + entries.length, total);
      els.pageInfo.textContent = `${start}-${end} of ${total}`;
      els.prevBtn.disabled = offset === 0;
      els.nextBtn.disabled = offset + entries.length >= total;
    }
  }
  toShow.forEach(entry => {
    const li = document.createElement('li');
    li.className = 'kb-item';
    renderItem(li, entry);
    els.list.appendChild(li);
  });
}

async function refresh() {
  clearError();
  try {
    if (els.search.value.trim()) {
      // Filter active: fetch the full list (not just the current page) so
      // search spans every entry. Debounced by the input handler below.
      const data = await postJson(`/kb?limit=${SEARCH_LIMIT}&offset=0`, {});
      searchCache = data.entries;
      total = data.count;
    } else {
      searchCache = null;
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      const data = await postJson(`/kb?${params}`, {});
      entries = data.entries;
      total = data.count;
    }
    editingId = null;
    render();
  } catch (err) {
    showError(err.message);
  }
}

els.search.addEventListener('input', () => {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(refresh, 250);
});

els.prevBtn.addEventListener('click', async () => {
  if (offset === 0) return;
  offset = Math.max(0, offset - PAGE_SIZE);
  await refresh();
});

els.nextBtn.addEventListener('click', async () => {
  if (offset + entries.length >= total) return;
  offset += PAGE_SIZE;
  await refresh();
});

els.reloadBtn.addEventListener('click', async () => {
  clearError();
  try {
    await postJson('/kb/reload', { method: 'POST' });
    offset = 0;
    await refresh();
    await Promise.all([loadStats(), loadUnmatched()]);
  } catch (err) {
    showError(err.message);
  }
});

els.addForm.addEventListener('submit', async e => {
  e.preventDefault();
  clearError();
  const response = els.response.value.trim();
  if (!response) {
    showError('Answer text is required.');
    return;
  }
  els.addBtn.disabled = true;
  try {
    const created = await postJson('/kb', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: els.question.value.trim(), response })
    });
    // After add, go to last page where new entry appears
    // Simplest: refresh current page; if not visible due to pagination, jump to last page
    await refresh();
    // If new entry not on current page, jump to last page
    if (!entries.find(en => en.id === created.id) && total > offset + entries.length) {
      offset = Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE;
      await refresh();
    }
    els.question.value = '';
    els.response.value = '';
    await Promise.all([loadStats(), loadUnmatched()]);
  } catch (err) {
    showError(err.message);
  } finally {
    els.addBtn.disabled = false;
  }
});

els.exportBtn.addEventListener('click', async () => {
  clearError();
  try {
    const res = await fetch('/kb/export');
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Export failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'knowledge_base.json';
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    showError(err.message);
  }
});

els.importFile.addEventListener('change', async () => {
  const file = els.importFile.files[0];
  if (!file) return;
  clearError();
  const formData = new FormData();
  formData.append('file', file);
  try {
    await postJson('/kb/import', { method: 'POST', body: formData });
    offset = 0;
    await refresh();
    await Promise.all([loadStats(), loadUnmatched()]);
  } catch (err) {
    showError(err.message);
  } finally {
    els.importFile.value = '';
  }
});

async function loadStats() {
  try {
    const res = await fetch('/stats');
    if (!res.ok) return;
    const data = await res.json();
    const c = data.counters || {};
    const llmCalls = c.llm_calls || 0;
    const transcribeCalls = c.transcribe_requests || 0;
    const totalInquiries = Math.max(llmCalls, transcribeCalls);
    const takeovers = (c['tts:groq-orpheus'] || 0) + (c['tts:gtts-fallback'] || 0);
    const takeoverPct = llmCalls > 0 ? Math.round((takeovers / llmCalls) * 100) : 0;
    const handoffs = (c['handoff:no_match'] || 0) + (c['handoff:speak_to_agent'] || 0);
    const noMatch = c.no_match || 0;

    if (els.statTotal) els.statTotal.textContent = totalInquiries.toLocaleString();
    if (els.statTakeover) els.statTakeover.textContent = `${takeoverPct}%`;
    if (els.statHandoff) els.statHandoff.textContent = handoffs.toLocaleString();
    if (els.statUnmatched) els.statUnmatched.textContent = noMatch.toLocaleString();
    if (els.statKbCount) els.statKbCount.textContent = (data.kb_count || 0).toLocaleString();
  } catch (e) {
    // Stats are non-critical
  }
}

async function loadUnmatched() {
  if (!els.unmatchedList) return;
  try {
    const res = await fetch('/kb/unmatched?limit=25');
    if (!res.ok) return;
    const data = await res.json();
    const items = data.unmatched || [];
    if (els.unmatchedCount) els.unmatchedCount.textContent = data.count || 0;
    els.unmatchedList.innerHTML = '';
    if (!items.length) {
      const li = document.createElement('li');
      li.className = 'kb-unmatched-empty';
      li.textContent = 'No unmatched queries recorded yet.';
      els.unmatchedList.appendChild(li);
      return;
    }
    items.forEach(item => {
      const li = document.createElement('li');
      li.className = 'kb-unmatched-item';

      const text = document.createElement('span');
      text.className = 'kb-unmatched-text';
      text.textContent = item.transcript;
      text.title = item.transcript;

      const meta = document.createElement('div');
      meta.className = 'kb-unmatched-meta';

      if (item.count > 1) {
        const cnt = document.createElement('span');
        cnt.className = 'kb-unmatched-badge';
        cnt.textContent = `${item.count}×`;
        meta.appendChild(cnt);
      }
      if (item.handoff) {
        const ho = document.createElement('span');
        ho.className = 'kb-unmatched-badge handoff';
        ho.textContent = 'Handoff';
        meta.appendChild(ho);
      }
      if (item.in_kb) {
        const inKb = document.createElement('span');
        inKb.className = 'kb-unmatched-badge in-kb';
        inKb.textContent = 'In KB';
        meta.appendChild(inKb);
      } else {
        const useBtn = document.createElement('button');
        useBtn.type = 'button';
        useBtn.className = 'btn-ghost btn-small';
        useBtn.textContent = '+ Use';
        useBtn.title = 'Copy query into question field';
        useBtn.addEventListener('click', () => {
          els.question.value = item.transcript;
          els.response.focus();
          els.addForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
        meta.appendChild(useBtn);
      }

      li.append(text, meta);
      els.unmatchedList.appendChild(li);
    });
  } catch (e) {
    // Unmatched list is non-critical
  }
}

if (els.unmatchedRefreshBtn) {
  els.unmatchedRefreshBtn.addEventListener('click', () => loadUnmatched());
}

function escapeHtml(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function loadQueue() {
  if (!els.queueList) return;
  try {
    const res = await fetch('/handoff/queue?limit=25');
    if (!res.ok) return;
    const data = await res.json();
    const items = data.tickets || [];
    if (els.queueCount) els.queueCount.textContent = data.count || 0;
    if (!items.length) {
      els.queueList.innerHTML = '<li class="kb-unmatched-empty">Queue is empty. No pending handoffs.</li>';
      return;
    }
    els.queueList.innerHTML = items.map(t => {
      const id = escapeHtml(t.ticket_id || 'unknown');
      const text = escapeHtml(t.transcript || t.assistant_response || '');
      return `<li class="kb-unmatched-item" data-id="${id}">
        <div class="kb-unmatched-text">
          <strong style="display:block;font-size:12px;">Ticket ${id} (${escapeHtml(t.reason || 'handoff')})</strong>
          <span title="${text}">${text}</span>
        </div>
        <div class="kb-unmatched-meta">
          <button type="button" class="btn-ghost btn-small" data-action="replay" title="Retry sending ticket">Replay</button>
          <button type="button" class="btn-ghost btn-small" data-action="dismiss" title="Remove ticket from queue">Dismiss</button>
        </div>
      </li>`;
    }).join('');
  } catch (e) {}
}

if (els.queueList) {
  els.queueList.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const id = btn.closest('[data-id]')?.dataset?.id;
    if (!id) return;
    clearError();
    btn.disabled = true;
    try {
      const isReplay = btn.dataset.action === 'replay';
      const url = isReplay ? `/handoff/queue/replay?ticket_id=${encodeURIComponent(id)}` : `/handoff/queue/${encodeURIComponent(id)}`;
      await postJson(url, { method: isReplay ? 'POST' : 'DELETE' });
      await loadQueue();
    } catch (err) {
      showError(`${btn.textContent} failed: ${err.message}`);
      btn.disabled = false;
    }
  });
}

if (els.queueRefreshBtn) els.queueRefreshBtn.addEventListener('click', () => loadQueue());

if (els.queueReplayAllBtn) {
  els.queueReplayAllBtn.addEventListener('click', async () => {
    clearError();
    els.queueReplayAllBtn.disabled = true;
    try {
      const res = await postJson('/handoff/queue/replay', { method: 'POST' });
      await loadQueue();
      if (res.replayed > 0 || res.failed > 0) {
        showError(`Replayed: ${res.replayed}, Failed: ${res.failed}, Remaining: ${res.remaining}`);
        setTimeout(() => clearError(), 6000);
      }
    } catch (err) {
      showError(`Replay all failed: ${err.message}`);
    } finally {
      els.queueReplayAllBtn.disabled = false;
    }
  });
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

refresh();
loadStats();
loadUnmatched();
loadQueue();
checkHealth();
/* Test KB Logic */
let kbTestTimeout = null;
const testInput = document.getElementById('kb-test-input');
const testResults = document.getElementById('kb-test-results');

if (testInput && testResults) {
  testInput.addEventListener('input', () => {
    clearTimeout(kbTestTimeout);
    const q = testInput.value.trim();
    if (!q) {
      testResults.hidden = true;
      testResults.innerHTML = '';
      return;
    }
    kbTestTimeout = setTimeout(async () => {
      try {
        const res = await fetch(`/kb/search?q=${encodeURIComponent(q)}`, { headers: getAuthHeaders() });
        if (!res.ok) throw new Error('Search failed');
        const data = await res.json();
        testResults.innerHTML = '';
        if (!data.matches || data.matches.length === 0) {
          testResults.innerHTML = '<li style="padding:12px;color:var(--muted);text-align:center;">No matches found</li>';
        } else {
          data.matches.forEach(m => {
            const li = document.createElement('li');
            li.style.padding = '8px 12px';
            li.style.fontSize = '13px';
            li.style.borderBottom = '1px solid var(--border)';
            const scoreClass = m.score >= 0.45 ? 'status-ok' : 'status-down';
            li.innerHTML = `<div style="display:flex;justify-content:space-between;margin-bottom:4px;">
              <strong>Match Score</strong>
              <span class="status-pill ${scoreClass}">${(m.score * 100).toFixed(1)}%</span>
            </div>
            <div style="color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${m.text.replace(/"/g, '&quot;')}">${m.text}</div>`;
            testResults.appendChild(li);
          });
        }
        testResults.hidden = false;
      } catch (err) {
        console.error(err);
      }
    }, 300);
  });
}

/* Sidebar Tool Tabs (Test Match / Needs Answer / Queue) */
const tabButtons = document.querySelectorAll('.kb-side-tab-btn');
const tabPanes = {
  test: document.getElementById('pane-test'),
  unmatched: document.getElementById('pane-unmatched'),
  queue: document.getElementById('pane-queue'),
};

if (tabButtons.length) {
  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      tabButtons.forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
      });
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');

      const target = btn.dataset.tab;
      Object.entries(tabPanes).forEach(([name, pane]) => {
        if (pane) {
          pane.hidden = name !== target;
          pane.classList.toggle('active', name === target);
        }
      });

      if (target === 'unmatched') loadUnmatched();
      if (target === 'queue') loadQueue();
      if (target === 'test') {
        const testIn = document.getElementById('kb-test-input');
        if (testIn) testIn.focus();
      }
    });
  });
}
