const els = {
  count: document.getElementById('kb-count'),
  search: document.getElementById('kb-search'),
  reloadBtn: document.getElementById('kb-reload-btn'),
  list: document.getElementById('kb-list'),
  addForm: document.getElementById('kb-add-form'),
  question: document.getElementById('kb-question'),
  response: document.getElementById('kb-response'),
  addBtn: document.getElementById('kb-add-btn'),
  error: document.getElementById('kb-error')
};

let entries = [];

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
      clearError();
      try {
        await postJson(`/kb/${entry.id}`, { method: 'DELETE' });
        entries = entries.filter(e => e.id !== entry.id);
        render();
      } catch (err) {
        showError(err.message);
      }
    });
    li.append(text, del);
    els.list.appendChild(li);
  });
}

async function refresh() {
  clearError();
  try {
    const data = await postJson('/kb', {});
    entries = data.entries;
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

refresh();
