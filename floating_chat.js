const $ = (id) => document.getElementById(id);
const log = $('log');
const bridge = $('ssn_bridge');
const menu = $('menu');
const menuUser = $('menuUser');
const composer = $('composer');
const input = $('messageInput');
const sendBtn = $('sendBtn');
const sendStatus = $('sendStatus');

let cfg = {};
let design = {};
let weekly = { winnersByKey: {} };
let last = 0;
let selected = null;
let ws = null;
let statusTimer = null;
let localEchoCounter = 0;

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function platform(v) {
  v = String(v || '').toLowerCase();
  return v.includes('twitch') ? 'twitch' : v.includes('tiktok') ? 'tiktok' : v;
}

function keyOf(raw) {
  return platform(raw.type) + ':' + String(raw.chatname || '')
    .trim().replace(/^@+/, '').toLowerCase();
}

function badges(raw) {
  const b = raw.chatbadges;
  if (!b) return '';
  if (Array.isArray(b)) {
    return b.map((x) => typeof x === 'string'
      ? esc(x)
      : (x?.src ? `<img src="${esc(x.src)}" style="height:1.1em">` : esc(x?.label || ''))
    ).join(' ');
  }
  return typeof b === 'string' ? esc(b) : '';
}

function showStatus(text, kind = '', persist = false) {
  clearTimeout(statusTimer);
  sendStatus.textContent = text || '';
  sendStatus.className = `send-status${text ? ' show' : ''}${kind ? ` ${kind}` : ''}`;
  if (text && !persist) {
    statusTimer = setTimeout(() => showStatus(''), kind === 'error' ? 6500 : 2200);
  }
}

function renderLocalEcho(message, state = 'accepted_by_ssn') {
  const row = {
    id: `local-${Date.now()}-${++localEchoCounter}`,
    time: new Date().toISOString(),
    source: 'floating-local',
    platform: 'brynn',
    username: 'Brynn',
    message,
    avatar: '',
    localEcho: true,
    localState: state,
    raw: {
      chatname: 'Brynn',
      chatmessage: message,
      type: 'brynn',
      textonly: true,
      bot: true,
      admin: true,
      localEcho: true,
      localState: state,
    }
  };
  render(row);
}

function closeMenu() {
  menu.classList.remove('show');
  menu.setAttribute('aria-hidden', 'true');
}

function openMenu(row, x, y) {
  selected = row;
  menuUser.textContent = `${row.username || 'Usuario'} · ${(row.platform || '').toUpperCase()}`;
  menu.querySelector('[data-action="block"]').hidden = row.platform === 'kick';
  menu.querySelector('[data-action="timeout"]').hidden = !['twitch', 'kick'].includes(row.platform);
  menu.querySelector('[data-action="ban"]').hidden = !['twitch', 'kick'].includes(row.platform);
  menu.classList.add('show');
  menu.setAttribute('aria-hidden', 'false');

  // Espera un frame para conocer el tamaño real y no sacarlo de la pantalla.
  requestAnimationFrame(() => {
    const rect = menu.getBoundingClientRect();
    const left = Math.max(6, Math.min(innerWidth - rect.width - 6, x));
    const top = Math.max(6, Math.min(innerHeight - rect.height - 6, y));
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  });
}

function render(row) {
  const raw = row.raw || {};
  const w = weekly.winnersByKey?.[keyOf(raw)] || {};
  const wrap = document.createElement('div');
  if (row.localEcho) wrap.classList.add('local-echo');
  wrap.dataset.user = row.username;
  wrap.dataset.platform = row.platform;
  wrap.tabIndex = -1;

  if (design.enabled && String(design.customHtml || '').trim()) {
    const msg = raw.textonly === true ? esc(row.message) : String(row.message || '');
    const badgeMarkup = String(w.badgeHtml || w.badgeIcon || '✦');
    const roleTag = w?.tier
      ? `<span class="weekly-role-tag weekly-${esc(w.tier)}"><span class="weekly-role-icon">${badgeMarkup}</span><span>${esc(w.badgeLabel || w.title || 'TOP')}</span></span>`
      : '';
    const tokens = {
      '{user}': esc(row.username),
      '{platform}': esc((row.platform || '').toUpperCase()),
      '{avatar}': esc(row.avatar || ''),
      '{platformIcon}': '',
      '{badges}': badges(raw),
      '{message}': msg,
      '{contentImage}': raw.contentimg ? `<img class="content-image" src="${esc(raw.contentimg)}">` : '',
      '{role}': '', '{roleIcon}': '', '{roleTag}': roleTag,
      '{weeklyTitle}': esc(w.title || ''),
      '{weeklyBadge}': esc(w.badgeLabel || ''),
      '{weeklyRank}': esc(w.rank || ''),
      '{weeklyTier}': esc(w.tier || ''),
      '{weeklyTag}': roleTag,
    };

    let html = String(design.customHtml);
    for (const [k, v] of Object.entries(tokens)) html = html.split(k).join(v);

    const shadow = wrap.attachShadow({ mode: 'open' });
    shadow.innerHTML = `<style>
      *{box-sizing:border-box}
      ${String(design.customCss || '')}
      ${String(w.badgeCss || '')}
      #log{position:relative!important;inset:auto!important;width:100%!important;max-width:none!important;padding:0!important;transform:none!important}
      #log>div{margin:0!important}
    </style><div id="log"><div id="msg">${html}</div></div>`;
    const msgEl = shadow.getElementById('msg');
    try {
      new Function('CHAT_DATA', 'CHAT_ELEMENT', String(design.customJs || ''))({
        user: row.username, platform: row.platform, message: row.message,
        avatar: row.avatar, weekly: w, raw
      }, msgEl);
    } catch (e) {}
  } else {
    const localBadge = row.localEcho
      ? `<span class="local-badge">${row.localState === 'accepted_by_ssn' ? 'SALIDA LOCAL · SSN aceptó la orden' : row.localState === 'accepted_by_kick' ? 'SALIDA LOCAL · Kick aceptó la orden' : 'SALIDA LOCAL'}</span>`
      : '';
    wrap.innerHTML = `<div class="floating-fallback${row.localEcho ? ' floating-local-echo' : ''}">
      <div class="floating-meta"><span class="floating-name">${esc(row.username)}</span>${esc((row.platform || '').toUpperCase())}</div>
      <div>${raw.textonly === true ? esc(row.message) : String(row.message || '')}</div>
      ${localBadge}
    </div>`;
  }

  // El menú nativo de Chromium está desactivado desde desktop.py. Este evento
  // es el único menú contextual visible dentro del chat.
  wrap.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    e.stopPropagation();
    openMenu(row, e.clientX, e.clientY);
  });

  log.appendChild(wrap);
  while (log.children.length > Number(cfg.maxMessages || 600)) {
    log.firstElementChild?.remove();
  }
  log.scrollTop = log.scrollHeight;
}

async function loadCfg() {
  try {
    const d = await (await fetch('/api/floating-chat-config', { cache: 'no-store' })).json();
    cfg = d.config || {};
    composer.style.display = cfg.showComposer === false ? 'none' : 'flex';
    $('hud').style.display = cfg.showViewerCounts === false ? 'none' : 'flex';
  } catch (e) {}
}

async function loadDesign() {
  try {
    const d = await (await fetch('/api/chat-design', { cache: 'no-store' })).json();
    design = d.design || {};
  } catch (e) {}
}

async function loadWeekly() {
  try {
    weekly = await (await fetch('/api/weekly-rewards/active', { cache: 'no-store' })).json();
  } catch (e) {}
}

async function poll() {
  try {
    const d = await (await fetch('/api/chat/messages?after=' + last, { cache: 'no-store' })).json();
    for (const row of d.messages || []) {
      last = Math.max(last, +row.id || 0);
      render(row);
    }
  } catch (e) {}
}

async function viewers() {
  try {
    const d = await (await fetch('/api/chat/viewers', { cache: 'no-store' })).json();
    $('twViewers').textContent = d.twitch == null ? 'N/D' : d.twitch;
    $('ttViewers').textContent = d.tiktok == null ? 'N/D' : d.tiktok;
    $('kiViewers').textContent = d.kick == null ? 'N/D' : d.kick;
  } catch (e) {}
}

async function ssnConfig() {
  try {
    return await (await fetch('/api/social-stream-config', { cache: 'no-store' })).json();
  } catch (e) {
    return {};
  }
}

async function ingest(data, source) {
  fetch('/api/chat/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data, source })
  }).catch(() => {});
}

async function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  const c = await ssnConfig();
  const session = c.sessionId;
  if (!session) return;
  const pw = c.password || 'false';
  bridge.src = `https://vdo.socialstream.ninja/?ln&salt=vdo.ninja&password=${encodeURIComponent(pw)}&push&label=dock&vd=0&ad=0&novideo&noaudio&autostart&cleanoutput&room=${encodeURIComponent(session)}`;
  try {
    ws = new WebSocket(`wss://io.socialstream.ninja/join/${encodeURIComponent(session)}/4`);
    ws.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        const x = d?.dataReceived?.overlayNinja || d?.overlayNinja || d;
        if (x?.chatname || x?.chatmessage) ingest(x, 'floating-ws');
      } catch (_) {}
    };
    const connection = ws;
    ws.onclose = () => {
      if (ws === connection) { ws = null; setTimeout(connect, 3000); }
    };
  } catch (e) {}
}

window.addEventListener('message', (e) => {
  const p = e.data;
  const x = p?.dataReceived?.overlayNinja || p?.overlayNinja;
  if (x) ingest(x, 'floating-p2p');
});

composer.addEventListener('submit', async (e) => {
  e.preventDefault();
  const message = input.value.trim();
  if (!message || sendBtn.disabled) return;

  sendBtn.disabled = true;
  const target = $('sendPlatform').value;
  showStatus('Enviando a ' + (target==='kick'?'Kick':'Social Stream Ninja') + '…', '', true);
  try {
    const response = await fetch('/api/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, platform: target })
    });
    let d = {};
    try { d = await response.json(); } catch (_) {}

    if (response.ok && d.ok) {
      renderLocalEcho(message, d.status || 'accepted_by_ssn');
      input.value = '';
      showStatus(target==='kick'?'✅ Kick aceptó tu mensaje.':'Mensaje aceptado por SSN; verifica Twitch/TikTok para confirmar publicación.', 'ok', true);
      input.focus();
    } else {
      const hint = d?.diagnostic?.remoteApiHint ? ` Revisa ${d.diagnostic.remoteApiHint}.` : '';
      showStatus((d.error || `No se pudo enviar (HTTP ${response.status}).`) + hint, 'error', true);
    }
  } catch (err) {
    showStatus(`No se pudo contactar al servidor local: ${err?.message || err}`, 'error', true);
  } finally {
    sendBtn.disabled = false;
  }
});

// Evita que Chromium muestre Back / Forward / Reload / View page source.
document.addEventListener('contextmenu', (e) => e.preventDefault(), true);
document.addEventListener('pointerdown', (e) => {
  if (!menu.contains(e.target)) closeMenu();
}, true);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeMenu();
});

menu.addEventListener('click', async (e) => {
  e.stopPropagation();
  const button = e.target.closest('button[data-action]');
  const act = button?.dataset.action;
  if (!act || !selected) return;

  const u = selected.username;
  const p = selected.platform;
  button.disabled = true;
  try {
    if (act === 'copy') {
      await navigator.clipboard.writeText(u);
      showStatus(`Usuario copiado: ${u}`, 'ok');
    } else if (act === 'block') {
      const r = await fetch('/api/chat/block', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, platform: p })
      });
      const d = await r.json();
      showStatus(d.ok ? `${u} bloqueado en SSN/Brynn.` : (d.error || 'No se pudo bloquear.'), d.ok ? 'ok' : 'error', !d.ok);
    } else if (act === 'timeout' || act === 'ban') {
      const r = await fetch('/api/chat/moderate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, platform: p, action: act, duration: 600 })
      });
      const d = await r.json();
      showStatus(d.ok ? `${act === 'ban' ? 'Ban' : 'Timeout'} aplicado a ${u}.` : (d.error || 'No se pudo moderar.'), d.ok ? 'ok' : 'error', !d.ok);
    }
  } catch (err) {
    showStatus(`Error: ${err?.message || err}`, 'error', true);
  } finally {
    button.disabled = false;
    closeMenu();
  }
});

window.BRYNN_SET_CLICKTHROUGH = (v) => {
  document.body.classList.toggle('click-through', !!v);
  $('mode').textContent = v ? 'CLICK-THROUGH' : 'INTERACTIVO';
  if (v) closeMenu();
};
window.BRYNN_FOCUS_INPUT = () => input.focus();

loadCfg();
loadDesign();
loadWeekly();
connect();
poll();
viewers();
setInterval(poll, 350);
setInterval(loadCfg, 3000);
setInterval(loadDesign, 4000);
setInterval(loadWeekly, 6000);
setInterval(viewers, 8000);
