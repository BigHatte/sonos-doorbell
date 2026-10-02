'use strict';

/* ------------------------------------------------------------------ helpers */

const $ = (sel, root = document) => root.querySelector(sel);

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const ICON = {
  bell: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5z"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
};

const TABS = [
  ['profile', 'Profile'],
  ['boxen', 'Boxen'],
  ['gongs', 'Gongs'],
  ['historie', 'Historie'],
  ['einstellungen', 'Einstellungen'],
];

const MAX_UPLOAD = 20 * 1024 * 1024;

const state = {
  view: 'loading',          // loading | setup | login | app
  tab: 'profile',
  boxes: null,
  sounds: null,
  profiles: null,
  history: null,
  settings: null,
  editProfile: null,        // null | {id|null, name, sound, cooldown, members:{boxId:volume}}
  editBox: null,
  editSound: null,
  discover: null,           // null | array
  discovering: false,
  playing: null,            // url currently playing
  uploading: false,
  authError: '',
};

/* ---------------------------------------------------------------------- api */

class ApiError extends Error {
  constructor(status, detail) { super(detail); this.status = status; }
}

const AUTH_PATHS = ['/api/login', '/api/setup', '/api/session'];

async function api(path, { method = 'GET', json, form } = {}) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (json !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(json);
  } else if (form) {
    opts.body = form;
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new ApiError(0, 'Server nicht erreichbar');
  }
  if (res.status === 204) return null;
  let data = null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    try { data = await res.json(); } catch (e) { data = null; }
  }
  if (!res.ok) {
    let detail = data && data.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
    if (!detail) detail = `Fehler ${res.status}`;
    if (res.status === 401 && !AUTH_PATHS.includes(path) && state.view === 'app') {
      state.view = 'login';
      state.authError = 'Sitzung abgelaufen, bitte erneut anmelden.';
      render();
    }
    throw new ApiError(res.status, detail);
  }
  return data;
}

/* -------------------------------------------------------------------- toasts */

function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), kind === 'error' ? 6000 : 3200);
}
const toastError = (e) => { if (!(e instanceof ApiError && e.status === 401 && state.view !== 'app')) toast(e.message || String(e), 'error'); };

/* busy-state wrapper for buttons */
async function busy(btn, fn) {
  if (btn) {
    btn.classList.add('busy');
    btn.setAttribute('aria-busy', 'true');
    btn.dataset.label = btn.innerHTML;
    btn.insertAdjacentHTML('afterbegin', '<span class="spinner"></span>');
  }
  try {
    return await fn();
  } catch (e) {
    toastError(e);
  } finally {
    if (btn && btn.isConnected) {
      btn.classList.remove('busy');
      btn.removeAttribute('aria-busy');
      btn.innerHTML = btn.dataset.label;
    }
  }
}

/* ------------------------------------------------------------------- audio */

const audio = new Audio();
audio.preload = 'none';
audio.addEventListener('ended', () => setPlaying(null));
audio.addEventListener('error', () => { if (state.playing) { setPlaying(null); toast('Gong konnte nicht abgespielt werden', 'error'); } });

function setPlaying(url) {
  state.playing = url;
  document.querySelectorAll('[data-action="preview"], [data-action="preview-select"]').forEach((b) => {
    const u = b.dataset.action === 'preview-select' ? selectedSoundUrl(b) : b.dataset.url;
    const on = !!url && u === url;
    b.classList.toggle('playing', on);
    b.innerHTML = on ? ICON.stop : ICON.play;
    b.setAttribute('aria-label', on ? 'Vorschau stoppen' : 'Vorschau abspielen');
  });
}

function selectedSoundUrl(btn) {
  const sel = btn.parentElement.querySelector('select');
  const opt = sel && sel.selectedOptions[0];
  return opt ? opt.dataset.url : '';
}

function togglePreview(url) {
  if (!url) return;
  if (state.playing === url) {
    audio.pause();
    setPlaying(null);
    return;
  }
  audio.pause();
  audio.src = url;
  setPlaying(url);
  audio.play().catch(() => { setPlaying(null); toast('Gong konnte nicht abgespielt werden', 'error'); });
}

function stopAudio() { audio.pause(); state.playing = null; }

/* --------------------------------------------------------------- clipboard */

async function copyText(text, srcEl) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      toast('Kopiert', 'ok');
      return;
    }
  } catch (e) { /* fall through */ }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, text.length);
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  ta.remove();
  if (ok) {
    toast('Kopiert', 'ok');
  } else {
    const code = srcEl && srcEl.closest('.copyline') && $('code', srcEl.closest('.copyline'));
    if (code) {
      const r = document.createRange();
      r.selectNodeContents(code);
      const s = getSelection();
      s.removeAllRanges();
      s.addRange(r);
    }
    toast('Automatisches Kopieren nicht möglich – Text ist markiert, bitte mit Strg+C kopieren', 'error');
  }
}

/* ------------------------------------------------------------- formatting */

function fmtTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso || '';
  return d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function fmtDur(s) {
  if (s == null) return '–';
  return `${Number(s).toLocaleString('de-DE', { maximumFractionDigits: 1 })} s`;
}
const chips = (items) => items.length
  ? `<div class="chips">${items.map((i) => `<span class="chip">${i}</span>`).join('')}</div>`
  : '<span class="muted">–</span>';

/* -------------------------------------------------------------------- data */

const loaders = {
  boxes: async () => { state.boxes = await api('/api/boxes'); },
  sounds: async () => { state.sounds = await api('/api/sounds'); },
  profiles: async () => { state.profiles = await api('/api/profiles'); },
  history: async () => { state.history = await api('/api/history'); },
  settings: async () => { state.settings = await api('/api/settings'); },
};

const tabData = {
  profile: ['profiles', 'boxes', 'sounds'],
  boxen: ['boxes'],
  gongs: ['sounds'],
  historie: ['history'],
  einstellungen: ['settings'],
};

async function load(...names) {
  await Promise.all(names.map((n) => loaders[n]()));
}

async function refreshTab(showSpinner = false) {
  const tab = state.tab;
  const names = new Set([...tabData[tab], 'boxes']);
  if (showSpinner) { state.loadingTab = true; renderView(); }
  try {
    await load(...names);
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 401)) toastError(e);
  }
  state.loadingTab = false;
  if (state.view === 'app' && state.tab === tab) { renderHeaderStatus(); renderView(); }
}

/* ------------------------------------------------------------------ render */

function render() {
  const root = $('#root');
  stopAudio();
  if (state.view === 'loading') {
    root.innerHTML = '<div class="auth"><div class="loading"><span class="spinner"></span> Lade …</div></div>';
  } else if (state.view === 'setup' || state.view === 'login') {
    root.innerHTML = renderAuth();
    const f = $('input', root);
    if (f) f.focus();
  } else {
    root.innerHTML = `
      <header class="topbar"><div class="topbar-inner">
        <div class="topbar-row">
          <div class="brand">${ICON.bell}<span>Sonos-Türgong</span></div>
          <div class="top-actions">
            <span class="conn" id="conn"></span>
            <button class="btn small" data-action="logout">Abmelden</button>
          </div>
        </div>
        <nav class="tabs" role="tablist" aria-label="Bereiche">
          ${TABS.map(([id, label]) => `<button class="tab" role="tab" id="tab-${id}" data-action="tab" data-tab="${id}" aria-selected="${state.tab === id}">${label}</button>`).join('')}
        </nav>
      </div></header>
      <main id="view" role="tabpanel"></main>`;
    renderHeaderStatus();
    renderView();
  }
}

function renderAuth() {
  const setup = state.view === 'setup';
  return `
    <div class="auth"><form class="card" data-form="${setup ? 'setup' : 'login'}" autocomplete="on">
      <div class="brand">${ICON.bell}<span>Sonos-Türgong</span></div>
      <h2 style="margin-bottom:.4rem">${setup ? 'Passwort festlegen' : 'Anmelden'}</h2>
      ${setup ? '<p class="muted small">Willkommen! Lege ein Passwort für die Verwaltung fest (mindestens 8 Zeichen).</p>' : ''}
      <div class="field"><label for="pw">Passwort</label>
        <input id="pw" name="password" type="password" required autocomplete="${setup ? 'new-password' : 'current-password'}" ${setup ? 'minlength="8"' : ''}></div>
      ${setup ? `<div class="field"><label for="pw2">Passwort wiederholen</label>
        <input id="pw2" name="password2" type="password" required autocomplete="new-password" minlength="8"></div>` : ''}
      <div class="err" role="alert">${esc(state.authError)}</div>
      <button class="btn primary" type="submit" style="width:100%">${setup ? 'Passwort speichern' : 'Anmelden'}</button>
    </form></div>`;
}

function renderHeaderStatus() {
  const el = $('#conn');
  if (!el) return;
  const boxes = state.boxes;
  if (!boxes) { el.innerHTML = ''; return; }
  const total = boxes.length;
  const ok = boxes.filter((b) => b.connected).length;
  let cls = 'ok';
  if (!total) cls = '';
  else if (ok === 0) cls = 'bad';
  else if (ok < total) cls = 'warn';
  const txt = total ? `${ok}/${total} Boxen` : 'Keine Boxen';
  el.title = total ? `${ok} von ${total} Boxen verbunden` : 'Noch keine Boxen angelegt';
  el.innerHTML = `<span class="dot ${cls}"></span><span>${txt}</span>`;
}

function renderView() {
  const view = $('#view');
  if (!view) return;
  if (state.loadingTab) { view.innerHTML = '<div class="loading"><span class="spinner"></span> Lade …</div>'; return; }
  const needed = tabData[state.tab];
  if (needed.some((n) => state[n] == null)) {
    view.innerHTML = '<div class="loading"><span class="spinner"></span> Lade …</div>';
    return;
  }
  const fn = { profile: viewProfiles, boxen: viewBoxes, gongs: viewSounds, historie: viewHistory, einstellungen: viewSettings }[state.tab];
  view.innerHTML = fn();
}

/* ---------------------------------------------------------------- Profile */

function soundOptions(selected) {
  return (state.sounds || []).map((s) =>
    `<option value="${esc(s.id)}" data-url="${esc(s.url)}" ${s.id === selected ? 'selected' : ''}>${esc(s.name)}</option>`).join('');
}

function soundName(id) {
  const s = (state.sounds || []).find((x) => x.id === id);
  return s ? s.name : id;
}

function copyLine(label, text) {
  return `<div class="copyline"><span class="lbl">${label}</span><code>${esc(text)}</code>
    <button class="btn small" type="button" data-action="copy" data-text="${esc(text)}" aria-label="${label} kopieren">${ICON.copy} Kopieren</button></div>`;
}

function viewProfiles() {
  if (state.editProfile) return profileForm();
  const list = state.profiles;
  const head = `<div class="section-head"><h2>Profile</h2>
    <button class="btn primary" data-action="profile-new">Neues Profil</button></div>`;
  if (!list.length) {
    return head + `<div class="empty"><strong>Noch keine Profile</strong>
      Ein Profil legt fest, welcher Gong auf welchen Boxen mit welcher Lautstärke läuft. Lege ein Profil an, z. B. „Haustür“.
      ${state.boxes.length ? '' : '<br>Zuerst im Tab „Boxen“ mindestens eine Box hinzufügen.'}</div>`;
  }
  const boxById = Object.fromEntries(state.boxes.map((b) => [b.id, b]));
  return head + `<div class="stack">${list.map((p) => `
    <article class="card">
      <div class="card-head">
        <div><h3>${esc(p.name)}</h3>
          <div class="muted small">Gong: ${esc(soundName(p.sound))} · Sperrzeit: ${esc(p.cooldown_s)} s</div></div>
      </div>
      ${chips(p.members.map((m) => {
        const b = boxById[m.box];
        return `${esc(b ? b.name : 'unbekannte Box')} <strong>${esc(m.volume)}</strong>`;
      }))}
      <div class="loxone">
        <h4>Loxone</h4>
        ${copyLine('Adresse', p.loxone.address)}
        ${copyLine('Befehl', p.loxone.command)}
        <div class="muted small">Virtueller Ausgang: Adresse und Befehl für HTTP-Aufruf (GET) eintragen.</div>
      </div>
      <div class="card-actions">
        <button class="btn" data-action="profile-test" data-id="${esc(p.id)}">Testen</button>
        <button class="btn" data-action="profile-edit" data-id="${esc(p.id)}">Bearbeiten</button>
        <button class="btn" data-action="profile-token" data-id="${esc(p.id)}">Token neu erzeugen</button>
        <button class="btn danger" data-action="profile-delete" data-id="${esc(p.id)}">Löschen</button>
      </div>
    </article>`).join('')}</div>`;
}

function profileForm() {
  const f = state.editProfile;
  const boxes = state.boxes;
  const sounds = state.sounds;
  const members = boxes.length ? boxes.map((b) => {
    const on = b.id in f.members;
    const vol = on ? f.members[b.id] : 30;
    return `<div class="member ${on ? '' : 'off'}" data-box="${esc(b.id)}">
      <label><input type="checkbox" name="m-${esc(b.id)}" ${on ? 'checked' : ''}> ${esc(b.name)}</label>
      <input type="range" min="0" max="100" step="1" value="${vol}" ${on ? '' : 'disabled'} aria-label="Lautstärke ${esc(b.name)}">
      <output>${vol}</output></div>`;
  }).join('') : '<div class="empty">Noch keine Boxen – im Tab „Boxen“ im Netzwerk suchen oder manuell anlegen.</div>';
  return `
    <div class="section-head"><h2>${f.id ? 'Profil bearbeiten' : 'Neues Profil'}</h2></div>
    <form class="card" data-form="profile" novalidate>
      <div class="inline-fields">
        <div class="field"><label for="pf-name">Name</label>
          <input id="pf-name" name="name" type="text" value="${esc(f.name)}" required maxlength="60" placeholder="z. B. Haustür"></div>
        <div class="field"><label for="pf-cd">Sperrzeit (Sekunden)</label>
          <input id="pf-cd" name="cooldown" type="number" min="0" max="600" step="0.5" value="${esc(f.cooldown)}" required>
          <span class="hint">Wiederholte Klingeln innerhalb dieser Zeit werden ignoriert.</span></div>
      </div>
      <div class="field"><label for="pf-sound">Gong</label>
        <div class="with-btn"><select id="pf-sound" name="sound">${soundOptions(f.sound)}</select>
          <button class="btn" type="button" data-action="preview-select" aria-label="Vorschau abspielen">${ICON.play}</button></div>
        ${sounds.length ? '' : '<span class="hint">Keine Gongs vorhanden.</span>'}</div>
      <div class="field"><label>Boxen und Lautstärke</label>
        <div class="members">${members}</div></div>
      <div class="row">
        <button class="btn primary" type="submit">Speichern</button>
        <button class="btn" type="button" data-action="profile-cancel">Abbrechen</button>
      </div>
    </form>`;
}

function openProfileForm(p) {
  const defaultSound = (state.sounds.find((s) => s.id === 'ding-dong') || state.sounds[0] || {}).id || '';
  state.editProfile = p
    ? { id: p.id, name: p.name, sound: p.sound, cooldown: p.cooldown_s, members: Object.fromEntries(p.members.map((m) => [m.box, m.volume])) }
    : { id: null, name: '', sound: defaultSound, cooldown: 3, members: {} };
  stopAudio();
  renderView();
  const n = $('#pf-name'); if (n) n.focus();
}

async function saveProfile(form, btn) {
  const f = state.editProfile;
  const fd = new FormData(form);
  const name = String(fd.get('name') || '').trim();
  if (!name) { toast('Bitte einen Namen eingeben', 'error'); return; }
  const members = [];
  form.querySelectorAll('.member').forEach((row) => {
    if ($('input[type=checkbox]', row).checked) {
      members.push({ box: row.dataset.box, volume: parseInt($('input[type=range]', row).value, 10) });
    }
  });
  const body = {
    name, sound: String(fd.get('sound') || ''),
    cooldown_s: parseFloat(fd.get('cooldown')),
    members,
  };
  if (!Number.isFinite(body.cooldown_s) || body.cooldown_s < 0 || body.cooldown_s > 600) {
    toast('Sperrzeit muss zwischen 0 und 600 Sekunden liegen', 'error'); return;
  }
  if (!members.length && !confirm('Es ist keine Box ausgewählt – dieses Profil kann nicht klingeln. Trotzdem speichern?')) return;
  await busy(btn, async () => {
    await api(f.id ? `/api/profiles/${encodeURIComponent(f.id)}` : '/api/profiles',
      { method: f.id ? 'PUT' : 'POST', json: body });
    toast('Profil gespeichert', 'ok');
    state.editProfile = null;
    await refreshTab();
  });
}

function reportRing(res, okMsg) {
  const rs = res && Array.isArray(res.results) ? res.results : null;
  if (rs && rs.some((r) => r.ok === false)) {
    toast(rs.filter((r) => r.ok === false).map((r) => `${r.box}: ${r.error || 'Fehler'}`).join(' · '), 'error');
  } else {
    toast(okMsg, 'ok');
  }
}

/* ------------------------------------------------------------------ Boxen */

function viewBoxes() {
  const boxes = state.boxes;
  const manual = `
    <form class="card" data-form="box-add" novalidate>
      <h3 style="margin-bottom:.7rem">Box manuell hinzufügen</h3>
      <div class="inline-fields">
        <div class="field"><label for="ba-ip">IP-Adresse</label>
          <input id="ba-ip" name="ip" type="text" inputmode="decimal" required placeholder="IP-Adresse der Box" autocomplete="off"></div>
        <div class="field"><label for="ba-name">Name (optional)</label>
          <input id="ba-name" name="name" type="text" maxlength="60" placeholder="leer = Name aus Sonos" autocomplete="off"></div>
      </div>
      <button class="btn primary" type="submit">Hinzufügen</button>
    </form>`;
  const disc = `
    <div class="card">
      <div class="card-head"><div><h3>Im Netzwerk suchen</h3>
        <div class="muted small">Sucht per Multicast nach Sonos-Boxen (dauert einige Sekunden).</div></div>
        <button class="btn" data-action="discover" ${state.discovering ? 'disabled' : ''}>${state.discovering ? '<span class="spinner"></span> Suche läuft …' : 'Im Netzwerk suchen'}</button></div>
      ${state.discover ? (state.discover.length ? `<div class="discover-list">${state.discover.map((d, i) => `
        <div class="item"><div class="info"><div class="title">${esc(d.name)}</div>
          <div class="muted small"><span class="mono">${esc(d.ip)}</span>${d.model ? ' · ' + esc(d.model) : ''}</div></div>
          ${d.added ? '<span class="badge neutral">bereits angelegt</span>'
            : `<button class="btn small primary" data-action="discover-add" data-idx="${i}">Hinzufügen</button>`}</div>`).join('')}</div>`
        : '<p class="muted" style="margin-top:.8rem">Keine Boxen gefunden. Bei Docker muss der Container im selben Netzwerk laufen (Host-Netzwerk); alternativ die Box manuell per IP anlegen.</p>') : ''}
    </div>`;
  let list;
  if (!boxes.length) {
    list = '<div class="empty"><strong>Noch keine Boxen</strong>Noch keine Boxen – im Netzwerk suchen oder manuell anlegen.</div>';
  } else {
    list = `<div class="list">${boxes.map((b) => state.editBox === b.id ? boxEditForm(b) : `
      <div class="card item">
        <div class="info">
          <div class="title row" style="gap:.5rem"><span class="dot ${b.connected ? 'ok' : 'bad'}" title="${b.connected ? 'verbunden' : 'nicht verbunden'}"></span>${esc(b.name)}
            <span class="muted small">${b.connected ? 'verbunden' : 'nicht verbunden'}</span></div>
          <div class="muted small mono">${esc(b.ip)}</div>
          <div style="margin-top:.35rem">${chips(b.profiles.map(esc))}</div>
        </div>
        <div class="actions">
          <button class="btn small" data-action="box-test" data-id="${esc(b.id)}">Testgong</button>
          <button class="btn small" data-action="box-edit" data-id="${esc(b.id)}">Bearbeiten</button>
          <button class="btn small danger" data-action="box-delete" data-id="${esc(b.id)}">Löschen</button>
        </div>
      </div>`).join('')}</div>`;
  }
  return `<div class="section-head"><h2>Boxen</h2></div><div class="stack">${list}${disc}${manual}</div>`;
}

function boxEditForm(b) {
  return `<form class="card" data-form="box-edit" data-id="${esc(b.id)}" novalidate>
    <div class="inline-fields">
      <div class="field"><label for="be-name">Name</label>
        <input id="be-name" name="name" type="text" value="${esc(b.name)}" required maxlength="60"></div>
      <div class="field"><label for="be-ip">IP-Adresse</label>
        <input id="be-ip" name="ip" type="text" value="${esc(b.ip)}" required autocomplete="off"></div>
    </div>
    <div class="row"><button class="btn primary" type="submit">Speichern</button>
      <button class="btn" type="button" data-action="box-edit-cancel">Abbrechen</button></div>
  </form>`;
}

/* ----------------------------------------------------------------- Gongs */

function viewSounds() {
  const sounds = state.sounds;
  const list = sounds.map((s) => state.editSound === s.id ? `
    <form class="card" data-form="sound-edit" data-id="${esc(s.id)}" novalidate>
      <div class="field"><label for="se-name">Name</label>
        <input id="se-name" name="name" type="text" value="${esc(s.name)}" required maxlength="60"></div>
      <div class="row"><button class="btn primary" type="submit">Speichern</button>
        <button class="btn" type="button" data-action="sound-edit-cancel">Abbrechen</button></div>
    </form>` : `
    <div class="card item">
      <button class="btn" data-action="preview" data-url="${esc(s.url)}" aria-label="Vorschau abspielen">${ICON.play}</button>
      <div class="info">
        <div class="title">${esc(s.name)} <span class="badge ${s.builtin ? 'neutral' : ''}">${s.builtin ? 'fest' : 'eigener'}</span></div>
        <div class="muted small">Dauer: ${fmtDur(s.duration)}</div>
        <div style="margin-top:.35rem">${chips(s.profiles.map(esc))}</div>
      </div>
      ${s.builtin ? '' : `<div class="actions">
        <button class="btn small" data-action="sound-edit" data-id="${esc(s.id)}">Umbenennen</button>
        <button class="btn small danger" data-action="sound-delete" data-id="${esc(s.id)}">Löschen</button></div>`}
    </div>`).join('');
  const upload = `
    <form class="card" data-form="sound-upload" novalidate>
      <h3 style="margin-bottom:.4rem">Eigenen Gong hochladen</h3>
      <p class="muted small">Jedes gängige Audioformat ist möglich (max. 20 MB). Die Datei wird umgewandelt (MP3), Stille am Anfang wird entfernt,
        die Lautstärke angeglichen und der Gong auf höchstens 10 Sekunden gekürzt.</p>
      <div class="inline-fields">
        <div class="field"><label for="su-file">Datei</label>
          <input id="su-file" name="file" type="file" accept="audio/*,.mp3,.wav,.m4a,.ogg,.flac,.aac" required></div>
        <div class="field"><label for="su-name">Name</label>
          <input id="su-name" name="name" type="text" required maxlength="60" placeholder="z. B. Klingel Opa"></div>
      </div>
      <button class="btn primary" type="submit" ${state.uploading ? 'disabled' : ''}>${state.uploading ? '<span class="spinner"></span> wird verarbeitet …' : 'Hochladen'}</button>
      ${state.uploading ? '<span class="muted small" style="margin-left:.6rem">Das kann einige Sekunden dauern.</span>' : ''}
    </form>`;
  return `<div class="section-head"><h2>Gongs</h2></div><div class="stack"><div class="list">${list}</div>${upload}</div>`;
}

/* --------------------------------------------------------------- Historie */

function viewHistory() {
  const h = state.history;
  const head = `<div class="section-head"><h2>Historie</h2>
    <button class="btn" data-action="history-refresh">Aktualisieren</button></div>`;
  if (!h.length) {
    return head + '<div class="empty"><strong>Noch keine Einträge</strong>Hier erscheinen die Klingel-Ereignisse der letzten 30 Tage.</div>';
  }
  return head + `<div class="card table-wrap"><table>
    <thead><tr><th>Zeit</th><th>Profil</th><th>Gong</th><th>Ergebnis je Box</th></tr></thead>
    <tbody>${h.map((e) => `<tr>
      <td class="nowrap">${esc(fmtTime(e.time))}</td>
      <td>${e.source === 'test' ? `Test${e.profile ? ' · ' + esc(e.profile) : ''}` : esc(e.profile || '–')}</td>
      <td>${esc(e.sound)}</td>
      <td><div class="res">${(e.results || []).map((r) => r.ok
        ? `<span class="ok">✓ ${esc(r.box)}${r.ms != null ? ` (${esc(r.ms)} ms)` : ''}</span>`
        : `<span class="fail">✗ ${esc(r.box)}${r.error ? ': ' + esc(r.error) : ''}</span>`).join('') || '<span class="muted">–</span>'}</div></td>
    </tr>`).join('')}</tbody></table></div>`;
}

/* ---------------------------------------------------------- Einstellungen */

function viewSettings() {
  const s = state.settings;
  return `<div class="section-head"><h2>Einstellungen</h2></div><div class="stack">
    <form class="card" data-form="settings" novalidate>
      <h3 style="margin-bottom:.7rem">Netzwerk</h3>
      <div class="field"><label for="st-host">Adresse dieses Servers (für die Boxen)</label>
        <input id="st-host" name="advertise_host" type="text" value="${esc(s.advertise_host)}" placeholder="${esc(s.advertise_host_detected)}" autocomplete="off">
        <span class="hint">leer = automatisch (erkannt: <span class="mono">${esc(s.advertise_host_detected)}</span>). Unter dieser Adresse laden die Sonos-Boxen die Gongs (Port ${esc(s.port)}).</span></div>
      <button class="btn primary" type="submit">Speichern</button>
    </form>

    <form class="card" data-form="password" novalidate>
      <h3 style="margin-bottom:.7rem">Passwort ändern</h3>
      <div class="inline-fields">
        <div class="field"><label for="pw-cur">Aktuelles Passwort</label>
          <input id="pw-cur" name="current" type="password" autocomplete="current-password" required></div>
        <div class="field"><label for="pw-new">Neues Passwort</label>
          <input id="pw-new" name="new" type="password" autocomplete="new-password" minlength="8" required>
          <span class="hint">Mindestens 8 Zeichen. Andere Sitzungen werden abgemeldet.</span></div>
      </div>
      <button class="btn primary" type="submit">Passwort ändern</button>
      <p class="muted small" style="margin-top:.8rem">Passwort vergessen? Datei <span class="mono">/data/auth.json</span> im Container löschen
        (z. B. über die Portainer-Konsole) und den Container neu starten. Danach kann ein neues Passwort festgelegt werden.</p>
    </form>

    <div class="card">
      <h3 style="margin-bottom:.4rem">Backup</h3>
      <p class="muted small">Enthält Boxen, Profile (inkl. Tokens), Einstellungen und eigene Gongs – nicht das Passwort.</p>
      <a class="btn" href="/api/backup" download>Backup herunterladen</a>
      <hr>
      <form data-form="restore" novalidate>
        <div class="field"><label for="rs-file">Backup wiederherstellen</label>
          <input id="rs-file" name="file" type="file" accept=".zip,application/zip" required>
          <span class="hint">Ersetzt alle Einstellungen, Boxen, Profile und eigenen Gongs.</span></div>
        <button class="btn danger" type="submit">Wiederherstellen</button>
      </form>
    </div>
  </div>`;
}

/* ----------------------------------------------------------------- events */

async function switchTab(tab) {
  if (tab === state.tab && !state.editProfile) { /* still refresh below */ }
  stopAudio();
  state.tab = tab;
  state.editProfile = null; state.editBox = null; state.editSound = null;
  document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.tab === tab)));
  const need = tabData[tab].some((n) => state[n] == null);
  if (need) { state.loadingTab = true; renderView(); }
  await refreshTab();
}

const actions = {
  tab: (el) => switchTab(el.dataset.tab),

  async logout(el) {
    await busy(el, async () => { await api('/api/logout', { method: 'POST' }); });
    resetData();
    state.view = 'login'; state.authError = '';
    render();
  },

  copy: (el) => copyText(el.dataset.text, el),
  preview: (el) => togglePreview(el.dataset.url),
  'preview-select': (el) => togglePreview(selectedSoundUrl(el)),

  /* profiles */
  'profile-new': () => openProfileForm(null),
  'profile-edit': (el) => openProfileForm(state.profiles.find((p) => p.id === el.dataset.id)),
  'profile-cancel': () => { stopAudio(); state.editProfile = null; renderView(); },
  'profile-test': (el) => busy(el, async () => {
    const r = await api(`/api/profiles/${encodeURIComponent(el.dataset.id)}/test`, { method: 'POST' });
    reportRing(r, 'Testgong gesendet');
  }),
  'profile-token': (el) => {
    if (!confirm('Token neu erzeugen? Der alte Token wird ungültig – Loxone muss angepasst werden.')) return;
    return busy(el, async () => {
      await api(`/api/profiles/${encodeURIComponent(el.dataset.id)}/token`, { method: 'POST' });
      toast('Neuer Token erzeugt – Loxone anpassen', 'ok');
      await refreshTab();
    });
  },
  'profile-delete': (el) => {
    const p = state.profiles.find((x) => x.id === el.dataset.id);
    if (!confirm(`Profil „${p ? p.name : el.dataset.id}“ wirklich löschen? Loxone-Aufrufe mit diesem Profil funktionieren danach nicht mehr.`)) return;
    return busy(el, async () => {
      await api(`/api/profiles/${encodeURIComponent(el.dataset.id)}`, { method: 'DELETE' });
      toast('Profil gelöscht', 'ok');
      await refreshTab();
    });
  },

  /* boxes */
  'box-test': (el) => busy(el, async () => {
    const r = await api(`/api/boxes/${encodeURIComponent(el.dataset.id)}/test`, { method: 'POST', json: {} });
    reportRing(r, 'Testgong gesendet');
  }),
  'box-edit': (el) => { state.editBox = el.dataset.id; renderView(); const n = $('#be-name'); if (n) n.focus(); },
  'box-edit-cancel': () => { state.editBox = null; renderView(); },
  'box-delete': (el) => {
    const b = state.boxes.find((x) => x.id === el.dataset.id);
    if (!b) return;
    const used = b.profiles.length ? `\n\nDie Box wird in diesen Profilen verwendet und dort entfernt: ${b.profiles.join(', ')}.` : '';
    if (!confirm(`Box „${b.name}“ wirklich löschen?${used}`)) return;
    return busy(el, async () => {
      await api(`/api/boxes/${encodeURIComponent(b.id)}`, { method: 'DELETE' });
      toast('Box gelöscht', 'ok');
      await refreshTab();
    });
  },
  async discover() {
    state.discovering = true; state.discover = null; renderView();
    try {
      state.discover = await api('/api/discover', { method: 'POST' });
    } catch (e) { toastError(e); }
    state.discovering = false;
    renderView();
  },
  'discover-add': (el) => {
    const d = state.discover[parseInt(el.dataset.idx, 10)];
    return busy(el, async () => {
      await api('/api/boxes', { method: 'POST', json: { ip: d.ip, name: d.name } });
      d.added = true;
      toast(`„${d.name}“ hinzugefügt`, 'ok');
      await load('boxes');
      renderHeaderStatus(); renderView();
    });
  },

  /* sounds */
  'sound-edit': (el) => { state.editSound = el.dataset.id; renderView(); const n = $('#se-name'); if (n) n.focus(); },
  'sound-edit-cancel': () => { state.editSound = null; renderView(); },
  'sound-delete': (el) => {
    const s = state.sounds.find((x) => x.id === el.dataset.id);
    if (!s) return;
    if (!confirm(`Gong „${s.name}“ wirklich löschen?`)) return;
    return busy(el, async () => {
      await api(`/api/sounds/${encodeURIComponent(s.id)}`, { method: 'DELETE' });
      toast('Gong gelöscht', 'ok');
      await refreshTab();
    });
  },

  'history-refresh': (el) => busy(el, async () => { await load('history'); renderView(); }),
};

document.addEventListener('click', (ev) => {
  const el = ev.target.closest('[data-action]');
  if (!el || el.classList.contains('busy') || el.disabled) return;
  const fn = actions[el.dataset.action];
  if (fn) { ev.preventDefault(); fn(el); }
});

const forms = {
  async setup(form, btn) {
    const fd = new FormData(form);
    const pw = fd.get('password');
    if (pw !== fd.get('password2')) { setAuthError('Die Passwörter stimmen nicht überein.'); return; }
    if (String(pw).length < 8) { setAuthError('Das Passwort muss mindestens 8 Zeichen lang sein.'); return; }
    await authCall('/api/setup', pw, btn);
  },
  login: (form, btn) => authCall('/api/login', new FormData(form).get('password'), btn),

  profile: (form, btn) => saveProfile(form, btn),

  'box-add': (form, btn) => {
    const fd = new FormData(form);
    const ip = String(fd.get('ip') || '').trim();
    if (!ip) { toast('Bitte eine IP-Adresse eingeben', 'error'); return; }
    const body = { ip };
    const name = String(fd.get('name') || '').trim();
    if (name) body.name = name;
    return busy(btn, async () => {
      await api('/api/boxes', { method: 'POST', json: body });
      toast('Box hinzugefügt', 'ok');
      await refreshTab();
    });
  },
  'box-edit': (form, btn) => {
    const fd = new FormData(form);
    const body = { name: String(fd.get('name') || '').trim(), ip: String(fd.get('ip') || '').trim() };
    if (!body.name || !body.ip) { toast('Name und IP-Adresse werden benötigt', 'error'); return; }
    return busy(btn, async () => {
      await api(`/api/boxes/${encodeURIComponent(form.dataset.id)}`, { method: 'PUT', json: body });
      toast('Box gespeichert', 'ok');
      state.editBox = null;
      await refreshTab();
    });
  },

  'sound-edit': (form, btn) => {
    const name = String(new FormData(form).get('name') || '').trim();
    if (!name) { toast('Bitte einen Namen eingeben', 'error'); return; }
    return busy(btn, async () => {
      await api(`/api/sounds/${encodeURIComponent(form.dataset.id)}`, { method: 'PUT', json: { name } });
      toast('Gong umbenannt', 'ok');
      state.editSound = null;
      await refreshTab();
    });
  },
  async 'sound-upload'(form) {
    const fd = new FormData(form);
    const file = fd.get('file');
    const name = String(fd.get('name') || '').trim();
    if (!file || !file.size) { toast('Bitte eine Audiodatei auswählen', 'error'); return; }
    if (file.size > MAX_UPLOAD) { toast('Die Datei ist größer als 20 MB und kann nicht hochgeladen werden.', 'error'); return; }
    if (!name) { toast('Bitte einen Namen eingeben', 'error'); return; }
    const body = new FormData();
    body.append('file', file);
    body.append('name', name);
    state.uploading = true; renderView();
    try {
      await api('/api/sounds', { method: 'POST', form: body });
      toast('Gong hochgeladen', 'ok');
      state.uploading = false;
      await refreshTab();
    } catch (e) {
      state.uploading = false;
      toastError(e);
      renderView();
      // keep the chosen name for another attempt
      const n = $('#su-name'); if (n) n.value = name;
    }
  },

  settings: (form, btn) => busy(btn, async () => {
    state.settings = await api('/api/settings', { method: 'PUT', json: { advertise_host: String(new FormData(form).get('advertise_host') || '').trim() } });
    toast('Einstellungen gespeichert', 'ok');
    renderView();
  }),
  password: (form, btn) => {
    const fd = new FormData(form);
    const body = { current: fd.get('current'), new: fd.get('new') };
    if (String(body.new).length < 8) { toast('Das neue Passwort muss mindestens 8 Zeichen lang sein', 'error'); return; }
    return busy(btn, async () => {
      await api('/api/password', { method: 'PUT', json: body });
      toast('Passwort geändert', 'ok');
      form.reset();
    });
  },
  restore: (form, btn) => {
    const file = new FormData(form).get('file');
    if (!file || !file.size) { toast('Bitte eine Backup-Datei (.zip) auswählen', 'error'); return; }
    if (!confirm('Backup wiederherstellen? Dies ersetzt alle Einstellungen, Boxen, Profile und eigenen Gongs.')) return;
    const body = new FormData();
    body.append('file', file);
    return busy(btn, async () => {
      await api('/api/restore', { method: 'POST', form: body });
      toast('Backup wiederhergestellt', 'ok');
      resetData();
      form.reset();
      await refreshTab(true);
    });
  },
};

document.addEventListener('submit', (ev) => {
  const form = ev.target.closest('[data-form]');
  if (!form) return;
  ev.preventDefault();
  const fn = forms[form.dataset.form];
  const btn = $('button[type=submit]', form);
  if (fn) fn(form, btn);
});

/* member rows: checkbox toggles slider, slider updates the shown value */
document.addEventListener('change', (ev) => {
  const t = ev.target;
  if (t.matches('.member input[type=checkbox]')) {
    const row = t.closest('.member');
    $('input[type=range]', row).disabled = !t.checked;
    row.classList.toggle('off', !t.checked);
  } else if (t.matches('#pf-sound')) {
    if (state.playing) { audio.pause(); setPlaying(null); }
  }
});
document.addEventListener('input', (ev) => {
  const t = ev.target;
  if (t.matches('.member input[type=range]')) $('output', t.closest('.member')).textContent = t.value;
});

/* ------------------------------------------------------------------- auth */

function setAuthError(msg) {
  state.authError = msg;
  const el = $('.err');
  if (el) el.textContent = msg;
}

async function authCall(path, password, btn) {
  state.authError = '';
  setAuthError('');
  await busy(btn, async () => {
    try {
      await api(path, { method: 'POST', json: { password } });
    } catch (e) {
      setAuthError(e.status === 401 ? 'Falsches Passwort.' : e.message);
      return;
    }
    await enterApp();
  });
}

function resetData() {
  state.boxes = state.sounds = state.profiles = state.history = state.settings = null;
  state.editProfile = state.editBox = state.editSound = state.discover = null;
  state.discovering = state.uploading = false;
}

async function enterApp() {
  resetData();
  state.view = 'app';
  state.tab = 'profile';
  state.authError = '';
  state.loadingTab = true;
  render();
  await refreshTab();
}

async function init() {
  render();
  try {
    const s = await api('/api/session');
    if (s.setup_required) state.view = 'setup';
    else if (!s.logged_in) state.view = 'login';
    else { await enterApp(); return; }
  } catch (e) {
    state.view = 'login';
    state.authError = e.message;
  }
  render();
}

init();
