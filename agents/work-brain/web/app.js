// Work Brain: the browser side.
//
// The page never talks to Claude and never sees the API key. It asks web.py
// for state and renders what comes back. Everything the server or a note
// supplies goes in through textContent, never innerHTML: a note is your own
// writing, but a brain built from a downloaded file is not, and one rule that
// always holds beats a rule you have to think about.

const $ = (selector) => document.querySelector(selector);

const app = {
  state: null,
  busy: false,
};

// --- requests ---------------------------------------------------------------

async function api(path, body) {
  const options = body === undefined
    ? {}
    : {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      };
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw new Error('The server is not answering. Is python web.py still running?');
  }
  const data = await response.json().catch(() => ({ error: 'unreadable reply' }));
  if (!response.ok) throw new Error(data.error || `request failed (${response.status})`);
  return data;
}

const mode = () => ($('#live-mode').checked ? 'live' : 'offline');

function busy(isBusy, what) {
  app.busy = isBusy;
  document.querySelectorAll('button, input').forEach((element) => {
    element.disabled = isBusy;
  });
  if (isBusy) notice(`${what}…`, 'working');
}

function notice(text, kind) {
  const box = $('#notice');
  box.textContent = text;
  box.className = `notice ${kind || ''}`;
  box.hidden = !text;
}

// --- rendering --------------------------------------------------------------

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderNotes(notes) {
  const list = $('#notes');
  list.replaceChildren();
  notes.forEach((note) => {
    const item = element('li', 'row');
    const button = element('button', 'link', note.title);
    button.addEventListener('click', () => openReader('raw', note.source, note.title));
    item.append(button);
    item.append(element('span', 'meta', note.date));
    if (note.private_bullets) {
      item.append(element('span', 'tag private', `${note.private_bullets} private`));
    }
    list.append(item);
  });
  if (!notes.length) list.append(element('li', 'hint', 'No notes in that folder.'));
}

function renderBrain(groups) {
  const holder = $('#groups');
  holder.replaceChildren();
  let total = 0;
  let privateTotal = 0;

  groups.forEach((group) => {
    total += group.notes.length;
    const section = element('div', 'group');
    section.append(element('h3', null, `${group.folder} (${group.notes.length})`));
    const list = element('ul', 'list');

    group.notes.forEach((note) => {
      privateTotal += note.private;
      const item = element('li', 'row');
      const button = element('button', 'link', note.title);
      button.addEventListener('click', () => openReader('note', note.id, note.title));
      item.append(button);
      item.append(element('span', 'meta', `${note.facts} facts`));
      if (note.private) item.append(element('span', 'tag private', `${note.private} private`));
      if (note.replaced_by) item.append(element('span', 'tag old', 'replaced'));
      list.append(item);
    });

    if (!group.notes.length) list.append(element('li', 'hint', 'none yet'));
    section.append(list);
    holder.append(section);
  });

  const report = app.state.report;
  const parts = [`${total} notes in the brain`];
  if (privateTotal) parts.push(`${privateTotal} private facts, kept out of anything shared`);
  if (report) {
    parts.push(`last read: ${report.notes_read} notes, ${report.facts_added} facts`);
    if (report.skipped_total) parts.push(`${report.skipped_total} skipped`);
  }
  $('#brain-summary').textContent = parts.join(' · ');
}

function renderSkipped(report) {
  if (!report || !report.skipped.length) return null;
  const box = element('details', 'skipped');
  box.append(element('summary', null, `${report.skipped_total} things it could not place`));
  const list = element('ul', 'list');
  report.skipped.forEach((skip) => {
    const item = element('li', 'row skip');
    item.append(element('span', 'why', skip.why));
    item.append(element('span', 'what', skip.bullet || skip.source));
    list.append(item);
  });
  box.append(list);
  return box;
}

function renderResult(title, data) {
  $('#result').hidden = false;
  $('#result-title').textContent = title;
  $('#result-text').textContent = data.text;

  const meta = $('#result-meta');
  meta.replaceChildren();

  if (data.opened && data.opened.length) {
    meta.append(element('p', 'hint', `Read: ${data.opened.join(', ')}`));
  }
  if (data.cited && data.cited.length) {
    meta.append(element('p', 'hint', `Cited: ${data.cited.join(', ')}`));
  }
  if (data.used && data.used.length) {
    const box = element('details', 'sources');
    box.append(element('summary', null, `Built from ${data.used.length} facts`));
    const list = element('ul', 'list');
    data.used.forEach((row) => {
      list.append(element('li', 'row source', `${row.date} — ${row.fact} [${row.source}]`));
    });
    box.append(list);
    meta.append(box);
  }
  if (data.removed && data.removed.length) {
    const warning = element('div', 'cut');
    warning.append(element('p', null,
      `${data.removed.length} sentence(s) cut for echoing a private fact:`));
    const list = element('ul', 'list');
    data.removed.forEach((row) => list.append(element('li', 'row', row.sentence)));
    warning.append(list);
    meta.append(warning);
  }
}

// --- the reader -------------------------------------------------------------

async function openReader(kind, id, title) {
  try {
    const data = await api(`/api/${kind === 'raw' ? 'raw' : 'note'}?id=${encodeURIComponent(id)}`);
    $('#reader-title').textContent = title;
    $('#reader-text').textContent = data.text;
    $('#reader').hidden = false;
  } catch (error) {
    notice(error.message, 'bad');
  }
}

function closeReader() {
  $('#reader').hidden = true;
}

// --- actions ----------------------------------------------------------------

async function refresh() {
  app.state = await api('/api/state');
  $('#paths').textContent =
    `notes: ${app.state.notes_dir} · brain: ${app.state.brain_dir}`;
  renderNotes(app.state.notes);
  renderBrain(app.state.groups);

  const toggle = $('#live-mode');
  if (!app.state.can_go_live) {
    toggle.checked = false;
    toggle.disabled = true;
    $('#mode-label').textContent = 'Offline mode (no API key set)';
  } else {
    updateModeLabel();
  }
}

function updateModeLabel() {
  if (!app.state || !app.state.can_go_live) return;
  $('#mode-label').textContent = mode() === 'live'
    ? `Live mode (${app.state.model})`
    : 'Offline mode';
}

async function rebuild() {
  busy(true, mode() === 'live' ? 'Claude is reading your notes' : 'Reading your notes');
  try {
    const report = await api('/api/build', { mode: mode() });
    await refresh();
    const skipped = report.skipped_total
      ? `, ${report.skipped_total} skipped`
      : '';
    notice(`Read ${report.notes_read} notes and kept ${report.facts_added} facts${skipped}.`, 'good');
    const detail = renderSkipped(report);
    if (detail) $('#groups').prepend(detail);
  } catch (error) {
    notice(error.message, 'bad');
  } finally {
    busy(false);
  }
}

async function ask(event) {
  event.preventDefault();
  const question = $('#question').value.trim();
  if (!question) return;
  busy(true, 'Looking it up');
  try {
    renderResult(question, await api('/api/ask', { question, mode: mode() }));
    notice('', '');
  } catch (error) {
    notice(error.message, 'bad');
  } finally {
    busy(false);
  }
}

async function share(event) {
  event.preventDefault();
  const topic = $('#topic').value.trim();
  if (!topic) return;
  busy(true, 'Writing an update');
  try {
    renderResult(`Update on ${topic}`, await api('/api/share', { topic, mode: mode() }));
    notice('', '');
  } catch (error) {
    notice(error.message, 'bad');
  } finally {
    busy(false);
  }
}

// --- start ------------------------------------------------------------------

$('#rebuild').addEventListener('click', rebuild);
$('#ask-form').addEventListener('submit', ask);
$('#share-form').addEventListener('submit', share);
$('#live-mode').addEventListener('change', updateModeLabel);
$('#reader-close').addEventListener('click', closeReader);
$('#reader').addEventListener('click', (event) => {
  if (event.target.id === 'reader') closeReader();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeReader();
});

refresh().catch((error) => notice(error.message, 'bad'));
