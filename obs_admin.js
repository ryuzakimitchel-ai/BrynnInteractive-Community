const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

let inventory = { scenes: [], inputs: [], inputDetails: [], sceneItems: {}, filters: {} };
let state = {};
let previousStatus = null;
let sceneView = 'all';
let favoriteScenes = loadFavorites();
let activity = [];
let statusTimer = null;

function loadFavorites() {
  try { return new Set(JSON.parse(localStorage.getItem('brynn.obs.favoriteScenes') || '[]')); }
  catch (_) { return new Set(); }
}
function saveFavorites() {
  localStorage.setItem('brynn.obs.favoriteScenes', JSON.stringify([...favoriteScenes]));
}
function esc(x) {
  return String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
async function api(url, method = 'GET', body) {
  const r = await fetch(url, {
    method,
    headers: {'Content-Type':'application/json'},
    body: body ? JSON.stringify(body) : undefined,
    cache: 'no-store'
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) throw new Error(j.error || j.lastError || `HTTP ${r.status}`);
  return j;
}
function nowTime() {
  return new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}
function addLog(text, type = 'info') {
  if (!text) return;
  activity.unshift({ time: nowTime(), text: String(text), type });
  activity = activity.slice(0, 80);
  renderLog();
}
function renderLog() {
  const el = $('#activityLog');
  if (!activity.length) {
    el.innerHTML = '<div class="log-empty">Las acciones y cambios de estado aparecerán aquí.</div>';
    return;
  }
  el.innerHTML = activity.map(x => `
    <div class="log-item ${esc(x.type)}">
      <span class="log-time">${esc(x.time)}</span><i class="log-dot"></i><span class="log-text">${esc(x.text)}</span>
    </div>`).join('');
}
function toast(text, type = 'success') {
  const box = document.createElement('div');
  box.className = `toast ${type}`;
  box.textContent = text;
  $('#toastStack').appendChild(box);
  setTimeout(() => box.remove(), 3000);
}
function setMessage(text, type = 'info') {
  const el = $('#message');
  el.textContent = text || '';
  el.className = `message-box ${type}`;
}
function formatTimecode(value) {
  if (!value) return '—';
  return String(value).replace(/\.\d+$/, '');
}
function inputPercent(multiplier) {
  const n = Number(multiplier);
  if (!Number.isFinite(n)) return 100;
  return Math.round(Math.max(0, Math.min(2, n)) * 100);
}
function prettyKind(kind) {
  if (!kind) return 'Fuente OBS';
  return String(kind)
    .replace(/_input$/i, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, m => m.toUpperCase());
}

function detectStatusChanges(next) {
  if (!previousStatus) {
    if (next.connected) addLog(`Conectado a OBS · ${next.currentScene || 'sin escena'}`, 'success');
    previousStatus = {...next};
    return;
  }
  if (!!next.connected !== !!previousStatus.connected) {
    addLog(next.connected ? 'Conexión con OBS restablecida.' : 'OBS se desconectó.', next.connected ? 'success' : 'error');
  }
  if (next.connected && previousStatus.currentScene && next.currentScene !== previousStatus.currentScene) {
    addLog(`Escena activa: ${next.currentScene}`, 'info');
  }
  if (!!next.streaming !== !!previousStatus.streaming) {
    addLog(next.streaming ? 'Streaming iniciado.' : 'Streaming detenido.', next.streaming ? 'success' : 'warning');
  }
  if (!!next.recording !== !!previousStatus.recording) {
    addLog(next.recording ? 'Grabación iniciada.' : 'Grabación detenida.', next.recording ? 'success' : 'warning');
  }
  previousStatus = {...next};
}

function renderStatus(s) {
  state = s || {};
  const connected = !!state.connected;
  detectStatusChanges(state);

  const configured = state.configured || {};
  $('#statusPill').className = `status-pill ${connected ? 'on' : 'off'}`;
  $('#statusPill').innerHTML = `<i></i><span>${connected ? 'Conectado' : 'Desconectado'}</span>`;

  $('#endpointLabel').textContent = `${configured.host || '127.0.0.1'}:${configured.port || 4455}`;
  $('#heroObsVersion').textContent = state.obsVersion || '—';
  $('#heroWsVersion').textContent = state.webSocketVersion || '—';
  $('.connection-meta .dot').style.background = connected ? 'var(--obs-good)' : 'var(--muted)';

  $('#currentScene').textContent = state.currentScene || '—';
  const sourceCount = (inventory.sceneItems?.[state.currentScene] || []).length;
  $('#sceneContext').textContent = connected
    ? `${sourceCount} fuente${sourceCount === 1 ? '' : 's'} · ${state.sceneCollection || 'Colección actual'}`
    : 'Sin conexión';

  $('#streamState').textContent = state.streaming ? 'EN DIRECTO' : 'Detenido';
  $('#streamDot').className = `state-dot ${state.streaming ? 'live' : ''}`;
  $('#streamDuration').textContent = state.streaming ? `Duración ${formatTimecode(state.streamDuration)}` : 'Salida detenida';

  $('#recordState').textContent = state.recording ? 'Grabando' : 'Detenida';
  $('#recordDot').className = `state-dot ${state.recording ? 'recording' : ''}`;
  $('#recordDuration').textContent = state.recording ? `Duración ${formatTimecode(state.recordDuration)}` : 'Sin grabación activa';

  $('#profileName').textContent = state.profile || '—';
  $('#collectionName').textContent = state.sceneCollection || '—';

  $('#enabled').checked = !!configured.enabled;
  if (document.activeElement !== $('#host')) $('#host').value = configured.host || '127.0.0.1';
  if (document.activeElement !== $('#port')) $('#port').value = configured.port || 4455;
  $('#passHint').textContent = configured.passwordConfigured ? '(guardada)' : '(no configurada)';

  const streamBtn = $('#toggleStream');
  const recordBtn = $('#toggleRecord');
  streamBtn.classList.toggle('active', !!state.streaming);
  recordBtn.classList.toggle('active', !!state.recording);
  $('#toggleStreamHint').textContent = state.streaming ? 'Detener transmisión' : 'Iniciar transmisión';
  $('#toggleRecordHint').textContent = state.recording ? 'Detener grabación' : 'Iniciar grabación';
  streamBtn.disabled = !connected;
  recordBtn.disabled = !connected;

  if (state.lastError) setMessage(state.lastError, 'error');
  else if (connected) setMessage(`Conectado a OBS ${state.obsVersion || ''}. Inventario listo para usar.`, 'success');
  else if (!configured.enabled) setMessage('La integración con OBS está deshabilitada.', 'info');

  renderScenes();
  renderSources();
}

async function loadStatus({silent = true} = {}) {
  try {
    const s = await api('/api/obs');
    renderStatus(s);
    return s;
  } catch (e) {
    setMessage(e.message, 'error');
    if (!silent) toast(e.message, 'error');
    return null;
  }
}

async function saveConfig(extra = {}) {
  try {
    setMessage('Guardando configuración…', 'info');
    const body = {
      enabled: $('#enabled').checked,
      host: $('#host').value.trim(),
      port: Number($('#port').value || 4455),
      password: $('#password').value,
      ...extra
    };
    const s = await api('/api/obs/config', 'POST', body);
    $('#password').value = '';
    renderStatus(s);
    setMessage('Configuración guardada correctamente.', s.connected ? 'success' : 'info');
    addLog('Configuración de OBS guardada.', 'success');
    toast('Configuración de OBS guardada.');
    if (s.connected) await loadInventory({showMessage:false});
  } catch (e) {
    setMessage(e.message, 'error');
    addLog(e.message, 'error');
    toast(e.message, 'error');
  }
}

async function testConnection() {
  const btn = $('#testBtn');
  const old = btn.textContent;
  try {
    btn.disabled = true;
    btn.textContent = 'Conectando…';
    $('#enabled').checked = true;
    setMessage('Probando conexión con OBS…', 'info');
    const body = {
      enabled: true,
      host: $('#host').value.trim(),
      port: Number($('#port').value || 4455),
      password: $('#password').value
    };
    const s = await api('/api/obs/config', 'POST', body);
    $('#password').value = '';
    renderStatus(s);
    if (!s.connected) throw new Error(s.lastError || 'OBS no respondió.');
    addLog('Prueba de conexión completada correctamente.', 'success');
    toast('OBS conectado correctamente.');
    await loadInventory({showMessage:false});
  } catch (e) {
    setMessage(e.message, 'error');
    addLog(`Error de conexión: ${e.message}`, 'error');
    toast(e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function runAction(a, options = {}) {
  const {successText = '', logText = '', updateInventory = false} = options;
  try {
    const r = await api('/api/obs/action', 'POST', {action:a});
    if (r.status) renderStatus(r.status);
    if (logText) addLog(logText, 'success');
    if (successText) toast(successText);
    if (updateInventory) await loadInventory({showMessage:false});
    return r;
  } catch (e) {
    setMessage(e.message, 'error');
    addLog(e.message, 'error');
    toast(e.message, 'error');
    throw e;
  }
}

function renderScenes() {
  const root = $('#sceneButtons');
  const all = inventory.scenes || [];
  const list = sceneView === 'favorites' ? all.filter(x => favoriteScenes.has(x)) : all;
  if (!state.connected) {
    root.className = 'scene-grid empty-state';
    root.textContent = 'Conecta OBS para cargar tus escenas.';
    return;
  }
  if (!list.length) {
    root.className = 'scene-grid empty-state';
    root.textContent = sceneView === 'favorites' ? 'Aún no tienes escenas favoritas. Marca ★ en una escena.' : 'OBS no devolvió escenas.';
    return;
  }
  root.className = 'scene-grid';
  root.innerHTML = '';
  for (const name of list) {
    const card = document.createElement('div');
    const active = name === state.currentScene;
    card.className = `scene-card ${active ? 'active' : ''}`;
    card.innerHTML = `
      <div class="scene-main" role="button" tabindex="0">
        <strong>${esc(name)}</strong><small>${active ? 'ESCENA ACTIVA' : 'Cambiar a esta escena'}</small>
      </div>
      <button class="scene-star ${favoriteScenes.has(name) ? 'on' : ''}" title="${favoriteScenes.has(name) ? 'Quitar de favoritas' : 'Añadir a favoritas'}">★</button>`;
    const activate = async () => {
      if (name === state.currentScene) return;
      await runAction({type:'obs_scene', scene:name}, {successText:`Escena: ${name}`, logText:`Cambio de escena → ${name}`});
      state.currentScene = name;
      renderScenes();
      renderSources();
    };
    $('.scene-main', card).onclick = activate;
    $('.scene-main', card).onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); } };
    $('.scene-star', card).onclick = e => {
      e.stopPropagation();
      if (favoriteScenes.has(name)) favoriteScenes.delete(name); else favoriteScenes.add(name);
      saveFavorites();
      renderScenes();
    };
    root.appendChild(card);
  }
}

function renderSources() {
  const root = $('#sources');
  const query = ($('#sourceSearch').value || '').trim().toLowerCase();
  const rows = (inventory.sceneItems?.[state.currentScene] || []).filter(x => !query || `${x.name} ${x.kind}`.toLowerCase().includes(query));
  if (!state.connected) {
    root.className = 'control-list empty-state';
    root.textContent = 'Conecta OBS para ver las fuentes de la escena.';
    return;
  }
  if (!rows.length) {
    root.className = 'control-list empty-state';
    root.textContent = query ? 'No hay fuentes que coincidan con la búsqueda.' : 'No hay fuentes en la escena actual.';
    return;
  }
  root.className = 'control-list';
  root.innerHTML = '';
  for (const item of rows) {
    const d = document.createElement('div');
    d.className = 'control-row';
    d.innerHTML = `
      <div class="control-meta"><strong>${esc(item.name)}</strong><small>${esc(prettyKind(item.kind))}<span class="status-chip ${item.enabled ? 'on':'off'}">${item.enabled ? 'VISIBLE':'OCULTA'}</span></small></div>
      <div class="row-controls"><button class="toggle-control ${item.enabled ? 'on' : ''}" title="${item.enabled ? 'Ocultar fuente' : 'Mostrar fuente'}" aria-label="Cambiar visibilidad"></button></div>`;
    $('.toggle-control', d).onclick = async () => {
      const next = !item.enabled;
      await runAction({type:'obs_source', scene:state.currentScene, source:item.name, enabled:next}, {logText:`${next ? 'Fuente visible' : 'Fuente oculta'}: ${item.name}`});
      item.enabled = next;
      renderSources();
    };
    root.appendChild(d);
  }
}

function renderFilters() {
  const root = $('#filters');
  const query = ($('#filterSearch').value || '').trim().toLowerCase();
  const items = [];
  for (const [source, list] of Object.entries(inventory.filters || {})) {
    for (const f of list) {
      if (!query || `${source} ${f.name}`.toLowerCase().includes(query)) items.push({source, ...f});
    }
  }
  if (!state.connected) {
    root.className = 'control-list empty-state';
    root.textContent = 'Conecta OBS para ver los filtros.';
    return;
  }
  if (!items.length) {
    root.className = 'control-list empty-state';
    root.textContent = query ? 'No hay filtros que coincidan con la búsqueda.' : 'No se detectaron filtros en las fuentes de OBS.';
    return;
  }
  root.className = 'control-list';
  root.innerHTML = '';
  for (const f of items) {
    const d = document.createElement('div');
    d.className = 'control-row';
    d.innerHTML = `
      <div class="control-meta"><strong>${esc(f.name)}</strong><small>${esc(f.source)}<span class="status-chip ${f.enabled ? 'on':'off'}">${f.enabled ? 'ACTIVO':'INACTIVO'}</span></small></div>
      <div class="row-controls"><button class="toggle-control ${f.enabled ? 'on':''}" title="${f.enabled ? 'Desactivar filtro' : 'Activar filtro'}"></button></div>`;
    $('.toggle-control', d).onclick = async () => {
      const next = !f.enabled;
      await runAction({type:'obs_filter', source:f.source, filter:f.name, enabled:next}, {logText:`Filtro ${next ? 'activado' : 'desactivado'}: ${f.name}`});
      const original = (inventory.filters[f.source] || []).find(x => x.name === f.name);
      if (original) original.enabled = next;
      renderFilters();
    };
    root.appendChild(d);
  }
}

function renderInputs() {
  const root = $('#inputs');
  const query = ($('#inputSearch').value || '').trim().toLowerCase();
  let details = inventory.inputDetails || [];
  if (!details.length) details = (inventory.inputs || []).map(name => ({name, kind:'', audio:false, muted:false, volume:1, mediaState:''}));
  details = details.filter(x => !query || `${x.name} ${x.kind}`.toLowerCase().includes(query));
  if (!state.connected) {
    root.className = 'control-list empty-state';
    root.textContent = 'Conecta OBS para controlar audio y media.';
    return;
  }
  if (!details.length) {
    root.className = 'control-list empty-state';
    root.textContent = query ? 'No hay inputs que coincidan con la búsqueda.' : 'OBS no devolvió inputs.';
    return;
  }
  root.className = 'control-list';
  root.innerHTML = '';
  for (const item of details) {
    const pct = inputPercent(item.volume);
    const d = document.createElement('div');
    d.className = 'control-row audio-row';
    const typeText = prettyKind(item.kind);
    const mediaText = item.mediaState ? ` · ${item.mediaState.replace('OBS_MEDIA_STATE_', '').toLowerCase()}` : '';
    d.innerHTML = `
      <div class="control-meta"><strong>${esc(item.name)}</strong><small>${esc(typeText + mediaText)}${item.audio ? `<span class="status-chip ${item.muted ? 'off':'on'}">${item.muted ? 'MUTE':'AUDIO'}</span>`:''}</small></div>
      <div class="audio-controls">
        ${item.audio ? `<button class="btn quiet tiny mute-btn ${item.muted ? 'muted':''}" data-role="mute" title="Mute / Unmute">${item.muted ? 'MUTE':'VOL'}</button>
        <input class="volume-slider" data-role="volume" type="range" min="0" max="200" step="1" value="${pct}" title="Volumen">
        <span class="volume-value" data-role="value">${pct}%</span>` : '<span></span><span></span><span></span>'}
        ${item.mediaState ? '<button class="btn quiet tiny media-btn" data-role="restart">↻ Media</button>' : '<span></span>'}
      </div>`;
    if (item.audio) {
      const mute = $('[data-role="mute"]', d);
      mute.onclick = async () => {
        const next = !item.muted;
        await runAction({type:'obs_mute', input:item.name, muted:next}, {logText:`${next ? 'Mute' : 'Audio restaurado'}: ${item.name}`});
        item.muted = next;
        renderInputs();
      };
      const slider = $('[data-role="volume"]', d);
      const value = $('[data-role="value"]', d);
      slider.oninput = () => value.textContent = `${slider.value}%`;
      slider.onchange = async () => {
        const multiplier = Number(slider.value) / 100;
        await runAction({type:'obs_volume', input:item.name, volume:multiplier}, {logText:`Volumen ${item.name}: ${slider.value}%`});
        item.volume = multiplier;
      };
    }
    const restart = $('[data-role="restart"]', d);
    if (restart) restart.onclick = () => runAction({type:'obs_media_restart', input:item.name}, {successText:`Media reiniciada: ${item.name}`, logText:`Media reiniciada: ${item.name}`});
    root.appendChild(d);
  }
}

function renderInventory() {
  renderScenes();
  renderSources();
  renderFilters();
  renderInputs();
  renderStatus(state);
}

async function loadInventory({showMessage = true} = {}) {
  const btn = $('#refreshInventory');
  const old = btn.textContent;
  try {
    btn.disabled = true;
    btn.textContent = 'Actualizando…';
    inventory = await api('/api/obs/inventory');
    const s = await loadStatus();
    if (s) state = s;
    renderInventory();
    if (showMessage) {
      setMessage(`Inventario actualizado: ${inventory.scenes.length} escenas, ${(inventory.inputs || []).length} inputs.`, 'success');
      addLog(`Inventario actualizado · ${inventory.scenes.length} escenas.`, 'success');
      toast('Inventario de OBS actualizado.');
    }
  } catch (e) {
    setMessage(e.message, 'error');
    addLog(`No se pudo actualizar el inventario: ${e.message}`, 'error');
    if (showMessage) toast(e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function copyText(text, successText) {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
    else {
      const ta = document.createElement('textarea'); ta.value = text; ta.style.position='fixed'; ta.style.opacity='0';
      document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
    }
    toast(successText);
    addLog(successText, 'success');
  } catch (e) { toast('No se pudo copiar al portapapeles.', 'error'); }
}

function inventoryText() {
  const lines = [
    'BRYNN INTERACTIVE · OBS INVENTORY',
    `Escena actual: ${state.currentScene || '—'}`,
    `Perfil: ${state.profile || '—'}`,
    `Colección: ${state.sceneCollection || '—'}`,
    '', 'ESCENAS:'
  ];
  for (const scene of inventory.scenes || []) lines.push(`- ${scene}`);
  lines.push('', 'FUENTES POR ESCENA:');
  for (const scene of inventory.scenes || []) {
    lines.push(`[${scene}]`);
    for (const src of inventory.sceneItems?.[scene] || []) lines.push(`  - ${src.name} · ${src.enabled ? 'visible' : 'oculta'} · ${src.kind || 'fuente'}`);
  }
  lines.push('', 'FILTROS:');
  for (const [source, filters] of Object.entries(inventory.filters || {})) {
    for (const f of filters) lines.push(`- ${source} → ${f.name} · ${f.enabled ? 'activo' : 'inactivo'}`);
  }
  lines.push('', 'INPUTS:');
  for (const input of inventory.inputDetails || []) lines.push(`- ${input.name} · ${input.kind || 'input'}${input.audio ? ` · ${input.muted ? 'mute' : 'audio'} · ${inputPercent(input.volume)}%` : ''}`);
  return lines.join('\n');
}

// Events
$('#saveBtn').onclick = () => saveConfig();
$('#clearPassBtn').onclick = () => saveConfig({clearPassword:true, password:''});
$('#testBtn').onclick = testConnection;
$('#refreshInventory').onclick = () => loadInventory({showMessage:true});
$('#toggleStream').onclick = () => runAction({type:'obs_stream', active:!state.streaming}, {successText:state.streaming?'Streaming detenido.':'Streaming iniciado.', logText:state.streaming?'Streaming detenido manualmente.':'Streaming iniciado manualmente.'});
$('#toggleRecord').onclick = () => runAction({type:'obs_record', active:!state.recording}, {successText:state.recording?'Grabación detenida.':'Grabación iniciada.', logText:state.recording?'Grabación detenida manualmente.':'Grabación iniciada manualmente.'});
$('#sourceSearch').oninput = renderSources;
$('#filterSearch').oninput = renderFilters;
$('#inputSearch').oninput = renderInputs;
$('#showAllScenes').onclick = () => {
  sceneView='all'; $('#showAllScenes').classList.add('active'); $('#showFavoriteScenes').classList.remove('active'); renderScenes();
};
$('#showFavoriteScenes').onclick = () => {
  sceneView='favorites'; $('#showFavoriteScenes').classList.add('active'); $('#showAllScenes').classList.remove('active'); renderScenes();
};
$('#toggleConnectionPanel').onclick = () => {
  const p = $('#connectionPanel');
  p.classList.toggle('collapsed');
  const collapsed = p.classList.contains('collapsed');
  $('#toggleConnectionPanel').textContent = collapsed ? '›' : '⌄';
  localStorage.setItem('brynn.obs.connectionCollapsed', collapsed ? '1':'0');
};
$('#clearLog').onclick = () => { activity=[]; renderLog(); };
$('#copyInventory').onclick = () => copyText(inventoryText(), 'Inventario de OBS copiado.');
$('#copyConnection').onclick = () => copyText(`${$('#host').value.trim() || '127.0.0.1'}:${$('#port').value || 4455}`, 'Datos de conexión copiados.');

(async function init(){
  renderLog();
  if (localStorage.getItem('brynn.obs.connectionCollapsed') === '1') {
    $('#connectionPanel').classList.add('collapsed');
    $('#toggleConnectionPanel').textContent = '›';
  }
  const s = await loadStatus({silent:false});
  if (s?.connected) await loadInventory({showMessage:false});
  else renderInventory();
  statusTimer = setInterval(() => loadStatus({silent:true}), 5000);
})();
