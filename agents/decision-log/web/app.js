// Decision Log: the browser side.
//
// The page never talks to Claude and never sees the API key. It asks web.py
// for state and renders what comes back. Everything the server or a note
// supplies goes in through textContent, never innerHTML: one rule that always
// holds beats a rule you have to think about.
//
// The page is built around one object, the decision. The timeline lists them,
// the panel explains one of them, and everything else (people, projects, the
// raw notes) is supporting material tucked underneath.

const $ = (selector) => document.querySelector(selector);

const app = {
  state: null,
  selected: null,
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

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function sourceLink(source) {
  const button = element('button', 'source-link', source);
  button.title = 'Read the note this came from';
  button.addEventListener('click', () => openReader('raw', source, source));
  return button;
}

// --- the timeline -----------------------------------------------------------

function renderTimeline() {
  const list = $('#timeline');
  const onlyCurrent = $('#only-current').checked;
  list.replaceChildren();

  const rows = app.state.decisions.filter((row) => !onlyCurrent || row.status === 'current');
  rows.forEach((row) => {
    const item = element('li', `card ${row.status}`);
    if (app.selected === row.id) item.classList.add('picked');

    const head = element('div', 'card-head');
    head.append(element('span', 'date', row.date));
    head.append(element('span', `badge ${row.status}`,
      row.status === 'current' ? 'still holds' : 'reversed'));
    if (row.private) head.append(element('span', 'badge private', `${row.private} private`));
    item.append(head);

    const title = element('button', 'card-title', row.title);
    title.addEventListener('click', () => select(row.id));
    item.append(title);

    if (row.why) {
      item.append(element('p', 'card-why', `Why: ${row.why}`));
    } else {
      item.append(element('p', 'card-why missing', 'Why: not recorded in the notes'));
    }

    const foot = element('div', 'card-foot');
    if (row.owner) foot.append(element('span', 'chip', row.owner));
    if (row.project) foot.append(element('span', 'chip', row.project));
    if (row.replaces) foot.append(element('span', 'chip replaces', 'replaced an earlier call'));
    item.append(foot);

    list.append(item);
  });

  if (!rows.length) {
    list.append(element('li', 'hint', onlyCurrent
      ? 'Nothing in the log still holds.'
      : 'No decisions yet. Press “Read the notes”.'));
  }

  const all = app.state.decisions;
  const reversed = all.filter((row) => row.status !== 'current').length;
  const missing = all.filter((row) => !row.why).length;
  const parts = [`${all.length} decisions`];
  if (reversed) parts.push(`${reversed} later reversed`);
  if (missing) parts.push(`${missing} with no recorded reason`);
  if (app.state.report) {
    parts.push(`read from ${app.state.report.notes_read} notes`);
  }
  $('#log-summary').textContent = parts.join(' · ');
}

// --- one decision -----------------------------------------------------------

function factLine(row, label) {
  const item = element('li', 'fact');
  if (label) item.append(element('span', 'fact-label', label));
  item.append(element('span', 'fact-date', row.date));
  item.append(element('span', 'fact-text', row.text));
  if (row.private) item.append(element('span', 'badge private', 'private'));
  item.append(sourceLink(row.source));
  return item;
}

function section(title, hint) {
  const box = element('section', 'detail-block');
  box.append(element('h3', null, title));
  if (hint) box.append(element('p', 'hint', hint));
  return box;
}

function renderDetail(card) {
  const holder = $('#detail');
  holder.replaceChildren();
  holder.hidden = false;
  $('#detail-hint').hidden = true;
  $('#detail-heading').textContent = card.title;

  const head = element('p', 'detail-head');
  head.append(element('span', `badge ${card.status}`,
    card.status === 'current' ? 'still holds' : 'reversed'));
  head.append(element('span', 'meta', `decided ${card.date}`));
  if (card.owner.title) head.append(element('span', 'chip', `owner: ${card.owner.title}`));
  if (card.project.title) head.append(element('span', 'chip', card.project.title));
  holder.append(head);

  const why = section('Why', card.why.length
    ? null
    : 'The notes record this decision but never say why. That gap is worth filling in your next note.');
  const whyList = element('ul', 'list');
  card.why.forEach((row) => whyList.append(factLine(row)));
  why.append(whyList);
  holder.append(why);

  if (card.history.length) {
    const history = section('It replaced', 'What the team used to think, and why.');
    const list = element('ul', 'list');
    card.history.forEach((old) => {
      const item = element('li', 'old');
      const button = element('button', 'link', `${old.title} (${old.date})`);
      button.addEventListener('click', () => select(old.id));
      item.append(button);
      old.why.forEach((row) => {
        item.append(element('p', 'old-why', `Why then: ${row.text}`));
      });
      list.append(item);
    });
    history.append(list);
    holder.append(history);
  }

  if (card.replaced_by) {
    const later = section('Overturned later', null);
    const button = element('button', 'link', card.replaced_by);
    button.addEventListener('click', () => select(card.replaced_by));
    later.append(button);
    holder.append(later);
  }

  if (card.facts.length) {
    const rest = section('On the record', null);
    const list = element('ul', 'list');
    card.facts.forEach((row) => list.append(factLine(row)));
    rest.append(list);
    holder.append(rest);
  }

  if (card.affects.length) {
    const affects = section('It touches', null);
    const row = element('p', 'chips');
    card.affects.forEach((item) => row.append(element('span', 'chip', item.title)));
    affects.append(row);
    holder.append(affects);
  }

  const actions = element('div', 'actions');
  const explain = element('button', 'primary', 'Explain this to the team');
  explain.addEventListener('click', () => explainDecision(card.id));
  actions.append(explain);
  const raw = element('button', null, 'Read the source notes');
  raw.addEventListener('click', () => openReader('raw', card.sources[0], card.sources[0]));
  if (card.sources.length) actions.append(raw);
  holder.append(actions);
}

// --- answers and explanations ----------------------------------------------

function renderAnswer(title, data) {
  const holder = $('#answer');
  holder.replaceChildren();
  holder.hidden = false;
  holder.append(element('h3', null, title));
  holder.append(element('pre', 'answer-text', data.text));

  const trail = element('p', 'hint');
  const bits = [];
  if (data.searches && data.searches.length) bits.push(`searched: ${data.searches.join(', ')}`);
  if (data.opened && data.opened.length) bits.push(`read: ${data.opened.join(', ')}`);
  if (data.cited && data.cited.length) bits.push(`cited: ${data.cited.join(', ')}`);
  if (bits.length) {
    trail.textContent = bits.join(' · ');
    holder.append(trail);
  }

  if (data.used && data.used.length) {
    const box = element('details', 'sources');
    box.append(element('summary', null, `Built from ${data.used.length} facts`));
    const list = element('ul', 'list');
    data.used.forEach((row) => list.append(factLine(row)));
    box.append(list);
    holder.append(box);
  }

  if (data.removed && data.removed.length) {
    const cut = element('div', 'cut');
    cut.append(element('p', null,
      `${data.removed.length} sentence(s) cut for echoing a private fact:`));
    const list = element('ul', 'list');
    data.removed.forEach((row) => list.append(element('li', null, row.sentence)));
    cut.append(list);
    holder.append(cut);
  }

  const cards = data.cards || (data.decision ? [data.decision] : []);
  if (cards.length) renderDetail(cards[0]);
}

async function select(decisionId, fromHash) {
  app.selected = decisionId;
  try {
    renderDetail(await api(`/api/decision?id=${encodeURIComponent(decisionId)}`));
    renderTimeline();
    // A decision gets its own address, so "send me the link to that decision"
    // has an answer. replaceState keeps the page where it is instead of
    // jumping, and keeps the back button useful.
    if (!fromHash) history.replaceState(null, '', `#${decisionId}`);
  } catch (error) {
    notice(error.message, 'bad');
  }
}

function selectFromAddress() {
  const wanted = decodeURIComponent(location.hash.replace(/^#/, '')).trim();
  if (wanted.startsWith('decisions/')) select(wanted, true);
}

async function explainDecision(decisionId) {
  busy(true, mode() === 'live' ? 'Claude is writing it' : 'Putting it together');
  try {
    const data = await api('/api/explain', { target: decisionId, mode: mode() });
    renderAnswer('For the team', data);
    notice('', '');
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
  busy(true, mode() === 'live' ? 'Claude is looking it up' : 'Looking it up');
  try {
    const data = await api('/api/ask', { question, mode: mode() });
    renderAnswer(question, data);
    if (data.cards && data.cards.length) app.selected = data.cards[0].id;
    renderTimeline();
    notice('', '');
  } catch (error) {
    notice(error.message, 'bad');
  } finally {
    busy(false);
  }
}

// --- the sources drawer -----------------------------------------------------

function renderSources() {
  const notes = $('#notes');
  notes.replaceChildren();
  app.state.notes.forEach((note) => {
    const item = element('li', 'row');
    const button = element('button', 'link', note.title);
    button.addEventListener('click', () => openReader('raw', note.source, note.title));
    item.append(button);
    item.append(element('span', 'meta', note.date));
    if (note.private_bullets) {
      item.append(element('span', 'badge private', `${note.private_bullets} private`));
    }
    notes.append(item);
  });

  const cast = $('#cast');
  cast.replaceChildren();
  app.state.cast.forEach((note) => {
    const item = element('li', 'row');
    const button = element('button', 'link', note.title);
    button.addEventListener('click', () => openReader('note', note.id, note.title));
    item.append(button);
    item.append(element('span', 'meta', `${note.kind} · ${note.facts} facts`));
    if (note.private) item.append(element('span', 'badge private', `${note.private} private`));
    cast.append(item);
  });
}

// --- the reader -------------------------------------------------------------

async function openReader(kind, id, title) {
  if (!id) return;
  try {
    const data = await api(`/api/${kind === 'raw' ? 'raw' : 'note'}?id=${encodeURIComponent(id)}`);
    $('#reader-title').textContent = title || id;
    $('#reader-text').textContent = data.text;
    $('#reader').hidden = false;
  } catch (error) {
    notice(error.message, 'bad');
  }
}

const closeReader = () => { $('#reader').hidden = true; };

// --- start ------------------------------------------------------------------

async function refresh() {
  app.state = await api('/api/state');
  renderTimeline();
  renderSources();
  if (!app.selected) selectFromAddress();

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
    app.selected = null;
    $('#detail').hidden = true;
    $('#answer').hidden = true;
    await refresh();
    const skipped = report.skipped_total ? `, ${report.skipped_total} skipped` : '';
    notice(`Read ${report.notes_read} notes and kept ${report.facts_added} facts${skipped}.`,
      'good');
  } catch (error) {
    notice(error.message, 'bad');
  } finally {
    busy(false);
  }
}

$('#rebuild').addEventListener('click', rebuild);
$('#ask-form').addEventListener('submit', ask);
$('#live-mode').addEventListener('change', updateModeLabel);
$('#only-current').addEventListener('change', () => renderTimeline());
$('#reader-close').addEventListener('click', closeReader);
window.addEventListener('hashchange', selectFromAddress);
$('#reader').addEventListener('click', (event) => {
  if (event.target.id === 'reader') closeReader();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeReader();
});

refresh().catch((error) => notice(error.message, 'bad'));
