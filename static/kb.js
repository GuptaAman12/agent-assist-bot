const els = {
  count: document.getElementById('kb-count'),
  search: document.getElementById('kb-search'),
  reloadBtn: document.getElementById('kb-reload-btn'),
  list: document.getElementById('kb-list'),
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

function adminHeaders() {
  const token = localStorage.getItem('adminToken');
  return token ? { 'X-Admin-Token': token } : {};
}

async function postJson(url, options) {
  const opts = options || {};
  opts.headers = { ...adminHeaders(), ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    const token = prompt('Admin token required to edit the knowledge base:');
    if (token) {
      try { localStorage.setItem('adminToken', token); } catch {}
      return postJson(url, options);
    }
    throw new Error('Authorization required. Set ADMIN_TOKEN in .env and provide it here.');
  }
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
      await postJson(`/kb/${entry.id}`, { method: 'DELETE' });
      entries = entries.filter(e => e.id !== entry.id);
      render();
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
  els.count.textContent = entries.length;
  els.list.innerHTML = '';
  visible.forEach(entry => {
    const li = document.createElement('li');
    li.className = 'kb-item';
    renderItem(li, entry);
    els.list.appendChild(li);
  });
}

async function refresh() {
  clearError();
  try {
    const data = await postJson('/kb', {});
    entries = data.entries;
    editingId = null;
    render();
  } catch (err) {
    showError(err.message);
  }
}

els.search.addEventListener('input', render);

els.reloadBtn.addEventListener('click', async () => {
  clearError();
  try {
    await postJson('/kb/reload', { method: 'POST' });
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
    entries.push(created);
    render();
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