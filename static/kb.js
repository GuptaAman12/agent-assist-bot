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
  themeToggle: document.getElementById('theme-toggle'),
  iconMoon: document.getElementById('icon-moon'),
  iconSun: document.getElementById('icon-sun')
};

let entries = [];
let editingId = null;
let total = 0;
let offset = 0;
const PAGE_SIZE = 10;
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
        entries[idx] = updated;
        editingId = null;
        render();
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
      render();
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
  const visible = entries.filter(e =>
    !filter ||
    e.question.toLowerCase().includes(filter) ||
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
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    const data = await postJson(`/kb?${params}`, {});
    entries = data.entries;
    total = data.count;
    editingId = null;
    render();
  } catch (err) {
    showError(err.message);
  }
}

els.search.addEventListener('input', render);

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
  } catch (err) {
    showError(err.message);
  } finally {
    els.addBtn.disabled = false;
  }
});

syncThemeIcon();
refresh();
