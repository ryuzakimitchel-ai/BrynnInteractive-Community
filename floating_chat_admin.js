const $ = (id) => document.getElementById(id);
let cfg = {};

async function load() {
  const r = await fetch('/api/floating-chat-config', { cache: 'no-store' });
  const d = await r.json();
  cfg = d.config || {};
  for (const k of ['width','height','windowOpacity','zoom','maxMessages']) $(k).value = cfg[k] ?? '';
  for (const k of ['alwaysOnTop','startClickThrough','showViewerCounts','showComposer']) $(k).checked = !!cfg[k];
  for (const [k,v] of Object.entries(cfg.hotkeys || {})) if ($(k)) $(k).value = v;

  const tr = await fetch('/api/twitch-control', { cache: 'no-store' });
  const tw = await tr.json();
  $('twitchEnabled').checked = !!tw.enabled;
  $('clientId').value = tw.clientId || '';
  $('broadcasterId').value = tw.broadcasterId || '';
  $('moderatorId').value = tw.moderatorId || '';
  $('tokenState').textContent = tw.tokenPresent ? 'Token guardado.' : 'Sin token.';
}

function read() {
  for (const k of ['width','height','windowOpacity','zoom','maxMessages']) cfg[k] = +$(k).value;
  for (const k of ['alwaysOnTop','startClickThrough','showViewerCounts','showComposer']) cfg[k] = $(k).checked;
  cfg.hotkeys = {};
  for (const k of ['toggleClickThrough','toggleVisible','opacityUp','opacityDown','focusComposer']) cfg.hotkeys[k] = $(k).value.trim();
  return cfg;
}

$('saveBtn').onclick = async () => {
  const r = await fetch('/api/floating-chat-config/save', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config: read() })
  });
  const d = await r.json();
  $('status').textContent = d.ok ? 'Guardado. La ventana lo aplicará automáticamente.' : d.error;
};

$('saveTwitch').onclick = async () => {
  const body = {
    enabled: $('twitchEnabled').checked,
    clientId: $('clientId').value,
    broadcasterId: $('broadcasterId').value,
    moderatorId: $('moderatorId').value
  };
  if ($('accessToken').value.trim()) body.accessToken = $('accessToken').value.trim();
  const r = await fetch('/api/twitch-control/save', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config: body })
  });
  const d = await r.json();
  $('tokenState').textContent = d.tokenPresent ? 'Token guardado.' : 'Sin token.';
  $('accessToken').value = '';
};

$('testSendBtn').onclick = async () => {
  const btn = $('testSendBtn');
  const status = $('sendTestStatus');
  const message = $('testMessage').value.trim();
  if (!message) { status.textContent = 'Escribe un mensaje de prueba.'; status.className = 'inline-status error'; return; }
  btn.disabled = true;
  status.textContent = 'Enviando…'; status.className = 'inline-status';
  try {
    const r = await fetch('/api/chat/send', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
    });
    const d = await r.json();
    if (r.ok && d.ok) {
      status.textContent = 'Orden aceptada por SSN. En el chat flotante el mensaje aparecerá como salida local; verifica Twitch/TikTok para confirmar publicación real.';
      status.className = 'inline-status ok';
    } else {
      const hint = d?.diagnostic?.remoteApiHint ? ` Revisa ${d.diagnostic.remoteApiHint}.` : '';
      status.textContent = (d.error || `Error HTTP ${r.status}`) + hint;
      status.className = 'inline-status error';
    }
  } catch (e) {
    status.textContent = `No se pudo contactar al backend: ${e?.message || e}`;
    status.className = 'inline-status error';
  } finally {
    btn.disabled = false;
  }
};

$('openBtn').onclick = () => location.href = 'brynn://floating-chat/open';
$('toggleBtn').onclick = () => location.href = 'brynn://floating-chat/toggle-click';
load();
