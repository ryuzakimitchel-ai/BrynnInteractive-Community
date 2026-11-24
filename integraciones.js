/* Brynn Interactive V30 - Streamlabs UI persistence fix */
const $=id=>document.getElementById(id);

let streamlabsFormDirty=false;
let streamlabsSaving=false;

function markStreamlabsDirty(){
  streamlabsFormDirty=true;
}

function setGlobal(text){
  $("status").textContent=text;
}

function stateClass(state){
  if(state==="connected")return"connected";
  if(state==="connecting")return"connecting";
  if(state==="error"||state==="missing_token"||state==="dependency_error")return"error";
  return"";
}

function renderService(prefix,data){
  const state=data.state||"unknown";
  const el=$(prefix+"State");
  el.className="state "+stateClass(state);

  let label=state;

  if(data.connected)label="🟢 Conectado";
  else if(state==="disabled")label="⚪ Deshabilitado";
  else if(state==="connecting")label="🟡 Conectando...";
  else if(state==="missing_token")label="🔴 Falta token";
  else if(state==="waiting_bridge")label="🟡 Esperando Bridge";
  else if(state==="local_server_error")label="🔴 Servidor local";
  else if(state==="socketio_library_error")label="🔴 Socket.IO no cargó";
  else if(state==="disconnected")label="🟠 Desconectado";
  else if(state==="error")label="🔴 Error";
  else label="⚪ "+state;

  if(prefix==="streamlabs" && data.connected && Number(data.activeBridges||0)>0){
    label += ` · ${data.activeBridges} bridge`;
  }

  el.textContent=label;

  const last=$(prefix+"Last");

  if(data.lastEvent){
    last.textContent=JSON.stringify(data.lastEvent,null,2);
  }else if(data.lastError){
    last.textContent="ERROR:\n"+data.lastError;
  }else{
    last.textContent="Sin eventos todavía.";
  }
}

async function refresh(){
  try{
    const r=await fetch("/api/integrations",{cache:"no-store"});
    const d=await r.json();

    /*
      No sobrescribir el formulario mientras el usuario está pegando
      el token o acaba de cambiar "Habilitar". Antes el refresco de
      2.5 s volvía a desmarcar la casilla con el estado viejo del servidor.
    */
    if(!streamlabsFormDirty && !streamlabsSaving){
      $("streamlabsEnabled").checked=Boolean(d.streamlabs?.enabled);
    }

    $("tikfinityEnabled").checked=Boolean(d.tikfinity?.enabled);

    if($("tikfinityMode")){
      $("tikfinityMode").value=d.tikfinity?.mode||"webhook";
    }

    if($("tikfinityPublicBaseUrl") && document.activeElement!==$("tikfinityPublicBaseUrl")){
      $("tikfinityPublicBaseUrl").value=d.tikfinity?.publicBaseUrl||"";
    }

    $("tokenInfo").textContent=d.streamlabs?.tokenPresent
      ? (
          "✅ Guardado de forma persistente: "+
          (d.streamlabs.tokenMasked||"••••")+
          " · "+
          (d.streamlabs.tokenLength||0)+
          " caracteres"
        )
      : "❌ No hay token persistente guardado";

    renderService("streamlabs",d.streamlabs||{});
    renderService("tikfinity",d.tikfinity||{});

    if(d.websocketClientAvailable===false){
      setGlobal("❌ El módulo WebSocket no está disponible.");
    }
  }catch(err){
    setGlobal("❌ No se pudo consultar el servidor.");
  }
}

async function saveStreamlabs(clear=false){
  streamlabsSaving=true;

  setGlobal(
    clear
      ? "Borrando token de Streamlabs..."
      : "Guardando Socket API Token..."
  );

  if(clear){
    const r=await fetch(
      "/api/integrations/streamlabs-token/clear",
      {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:"{}"
      }
    );

    const d=await r.json();

    if(!r.ok||!d.ok){
      throw new Error(
        d.error||"No se pudo borrar el token"
      );
    }

    $("streamlabsToken").value="";
    streamlabsFormDirty=false;
    streamlabsSaving=false;

    setGlobal(
      "✅ Token de Streamlabs eliminado de esta PC."
    );

    await refresh();
    return;
  }

  const token=$("streamlabsToken").value.trim();

  if(!token){
    streamlabsSaving=false;
    setGlobal(
      "⚠ Pega primero el Socket API Token de Streamlabs."
    );
    $("streamlabsToken").focus();
    return;
  }

  const r=await fetch(
    "/api/integrations/streamlabs-token/save",
    {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        socketToken:token,
        enabled:$("streamlabsEnabled").checked
      })
    }
  );

  const d=await r.json();

  if(!r.ok||!d.ok||!d.tokenPresent){
    throw new Error(
      d.error||
      "El servidor no confirmó que el token quedó guardado."
    );
  }

  // Solo borramos el campo DESPUÉS de que server.py confirme
  // que leyó el mismo token desde disco.
  $("streamlabsToken").value="";

  $("streamlabsEnabled").checked=Boolean(
    d.streamlabs?.enabled ?? d.enabled
  );

  $("tokenInfo").textContent=
    "✅ Guardado de forma persistente: "+
    (d.streamlabs?.tokenMasked||d.tokenMasked||"••••")+
    " · "+
    (d.streamlabs?.tokenLength||d.tokenLength||0)+
    " caracteres";

  streamlabsFormDirty=false;
  streamlabsSaving=false;

  setGlobal(
    `✅ Token guardado y verificado (${d.tokenLength||0} caracteres). `+
    `Espera unos segundos a que el Bridge conecte.`
  );

  setTimeout(refresh,400);
}

async function saveTikfinity(extra={}){
  const payload={
    tikfinityEnabled:$("tikfinityEnabled").checked,
    tikfinityMode:$("tikfinityMode").value,
    tikfinityPublicBaseUrl:$("tikfinityPublicBaseUrl").value.trim(),
    ...extra
  };

  const r=await fetch("/api/integrations/save",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(payload)
  });

  const d=await r.json();

  if(!r.ok||!d.ok){
    throw new Error(d.error||"No se pudo guardar");
  }

  setGlobal("✅ Configuración TikFinity guardada.");
  await refresh();
  await refreshWebhookUrls();
}

async function testEvent(service,type){
  setGlobal(`Enviando prueba ${service} / ${type}...`);

  const r=await fetch("/api/integrations/test",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({service,type})
  });

  const d=await r.json();

  if(!r.ok||!d.ok){
    throw new Error(d.error||"No se pudo probar");
  }

  setGlobal("✅ Evento de prueba enviado. Mira Brynn_Alerts en OBS.");
  setTimeout(refresh,500);
}


function buildWebhookUrl(base,secret,type,extra=""){
  if(!base||!secret)return"";

  /*
    TikFinity Actions & Events usa placeholders con llaves:
    {username}, {nickname}, {giftname}, {coins}, etc.
  */
  const common =
    `type=${type}`+
    `&username={username}`+
    `&nickname={nickname}`;

  return `${base}/t/${encodeURIComponent(secret)}?${common}${extra}`;
}

async function refreshWebhookUrls(){
  try{
    const r=await fetch(
      "/api/integrations/tikfinity-webhook-config",
      {cache:"no-store"}
    );
    const d=await r.json();

    const base=String(d.publicBaseUrl||"").replace(/\/$/,"");
    const secret=String(d.webhookSecret||"");

    $("urlFollow").value=buildWebhookUrl(
      base,secret,"follow"
    );

    $("urlSub").value=buildWebhookUrl(
      base,secret,"subscription",
      "&months={submonth}"
    );

    $("urlGift").value=buildWebhookUrl(
      base,secret,"gift",
      "&gift={giftname}&coins={coins}&repeat={repeatcount}"
    );

    $("urlLike").value=buildWebhookUrl(
      base,secret,"like",
      "&likes={likecount}&totalLikes={totallikecount}"
    );

    $("urlShare").value=buildWebhookUrl(
      base,secret,"share"
    );

    $("urlJoin").value=buildWebhookUrl(
      base,secret,"join"
    );

    const setup=$("webhookSetup");

    if(setup){
      setup.style.opacity=(
        d.mode==="webhook"
        ? "1"
        : ".45"
      );
    }
  }catch(error){
    console.warn(error);
  }
}

async function copyWebhook(id){
  const value=$(id).value;

  if(!value){
    setGlobal(
      "⚠ Primero pega tu URL pública https://... y guarda TikFinity."
    );
    return;
  }

  await navigator.clipboard.writeText(value);
  setGlobal("✅ URL copiada.");
}

document.querySelectorAll(".copy-webhook").forEach(btn=>{
  btn.onclick=()=>copyWebhook(btn.dataset.target);
});

$("regenTikfinitySecret").onclick=()=>{
  if(confirm(
    "Esto invalida las URLs WebHook anteriores. Tendrás que actualizarlas en TikFinity. ¿Continuar?"
  )){
    saveTikfinity({
      regenerateTikfinitySecret:true
    }).catch(e=>setGlobal("❌ "+e.message));
  }
};

$("tikfinityMode").onchange=()=>{
  refreshWebhookUrls();
};

$("streamlabsEnabled").addEventListener(
  "change",
  markStreamlabsDirty
);

$("streamlabsToken").addEventListener(
  "input",
  markStreamlabsDirty
);

$("streamlabsToken").addEventListener(
  "focus",
  markStreamlabsDirty
);

$("saveStreamlabs").onclick=()=>saveStreamlabs(false).catch(e=>{streamlabsSaving=false;setGlobal("❌ "+e.message);});
$("clearStreamlabs").onclick=()=>{
  if(confirm("¿Borrar el Socket API Token guardado en esta PC?")){
    saveStreamlabs(true).catch(e=>setGlobal("❌ "+e.message));
  }
};
$("saveTikfinity").onclick=()=>saveTikfinity().catch(e=>setGlobal("❌ "+e.message));

document.querySelectorAll("[data-service]").forEach(btn=>{
  btn.onclick=()=>testEvent(
    btn.dataset.service,
    btn.dataset.type
  ).catch(e=>setGlobal("❌ "+e.message));
});

async function kickPost(route, payload = {}) {
  const r = await fetch(route, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await r.json();
  if (!r.ok || data.ok === false) throw new Error(data.error || 'Error de Kick');
  return data;
}
async function refreshKick() {
  try {
    const d = await (await fetch('/api/kick',{cache:'no-store'})).json();
    const state = $('kickState');
    state.textContent = d.connected ? `🟢 Autorizado: ${d.username || d.userId}` :
      d.clientConfigured ? '🟡 Credenciales guardadas · Falta OAuth' : '⚪ Sin configurar';
    state.className = 'state '+(d.connected ? 'connected' : '');
    $('kickAccountInfo').textContent = d.connected
      ? `Cuenta: ${d.username || 'Sin nombre'} · ID: ${d.userId} · último webhook: ${d.lastDeliveryAt || 'todavía ninguno'}`
      : d.clientConfigured ? 'Credenciales guardadas en AppData. Ahora autoriza Kick.' : 'Introduce Client ID y Client Secret.';
    $('kickLast').textContent = d.lastEvent ? JSON.stringify(d.lastEvent,null,2) :
      (d.lastError ? 'ERROR: '+d.lastError : 'Aún no se ha recibido un evento oficial de Kick.');
  }catch(e){$('kickState').textContent='🔴 Servidor no disponible';}
}
$('kickSave').onclick=async()=>{
  try {
    await kickPost('/api/kick/credentials',{
      clientId:$('kickClientId').value.trim(), clientSecret:$('kickClientSecret').value.trim(), enabled:true
    });
    $('kickClientSecret').value='';setGlobal('✅ Credenciales Kick guardadas en AppData.');await refreshKick();
  }catch(e){setGlobal('❌ '+e.message)}
};
$('kickConnect').onclick=async()=>{
  // Qt WebEngine no crea ventanas emergentes sin implementar createWindow.
  // La navegación del frame principal sí pasa por DesktopWebPage, que abre
  // páginas externas en el navegador predeterminado de Windows.
  const btn=$('kickConnect');
  btn.disabled=true;
  setGlobal('⏳ Preparando la autorización oficial de Kick…');
  try {
    const d=await kickPost('/api/kick/oauth/start');
    if(typeof d.url!=='string' || !d.url.startsWith('https://id.kick.com/oauth/authorize?')){
      throw new Error('El servidor no devolvió una URL de autorización válida.');
    }
    setGlobal('✅ Abriendo Kick en tu navegador. Autoriza y regresa a Brynn.');
    window.location.assign(d.url);
  }catch(e){
    setGlobal('❌ No se pudo abrir la autorización de Kick: '+e.message);
  }finally{
    btn.disabled=false;
  }
};
$('kickSubscribe').onclick=async()=>{
  try {const d=await kickPost('/api/kick/subscriptions');setGlobal('✅ Solicitud de suscripción enviada a Kick. Revisa resultados: '+JSON.stringify(d.result||d.message||d.requested).slice(0,250));await refreshKick()}
  catch(e){setGlobal('❌ '+e.message)}
};
$('kickDisconnect').onclick=async()=>{
  if(!confirm('Borrar los tokens locales de Kick? Las suscripciones remotas NO se eliminan.'))return;
  try{await kickPost('/api/kick/disconnect');setGlobal('✅ Tokens locales Kick eliminados.');await refreshKick()}
  catch(e){setGlobal('❌ '+e.message)}
};
$('kickCopyUrl').onclick=async()=>{
  const value=$('kickWebhookUrl').value.trim();
  if(!/^https:\/\/[^\s/]+\/kick\/webhook$/.test(value)){
    setGlobal('⚠ Introduce URL HTTPS pública que termine en /kick/webhook.');return;
  }
  try{await navigator.clipboard.writeText(value);setGlobal('✅ URL Kick copiada para Kick Developer.');}
  catch(e){setGlobal('⚠ Copia la URL manualmente.');}
};
refresh();refreshKick();
setInterval(refresh,2500);
setInterval(refreshKick,4000);


function webhookExportText(){
  const rows=[
    ["FOLLOW",$("urlFollow")?.value||""],
    ["SUBSCRIBE",$("urlSub")?.value||""],
    ["GIFT",$("urlGift")?.value||""],
    ["LIKE",$("urlLike")?.value||""],
    ["SHARE",$("urlShare")?.value||""],
    ["JOIN",$("urlJoin")?.value||""]
  ];

  return [
    "TIKFINITY WEBHOOKS",
    "================================",
    "",
    ...rows.flatMap(([name,url])=>[
      `[${name}]`,
      `Destino en TikFinity: Action / Trigger WebHook -> ${name}`,
      `URL: ${url || "[SIN URL - guarda primero la URL pública]"}`,
      "",
      "--------------------------------",
      ""
    ])
  ].join("\n");
}

const copyAllBtn=$("copyAllWebhooks");
if(copyAllBtn){
  copyAllBtn.onclick=async()=>{
    const text=webhookExportText();

    if(!$("urlFollow")?.value){
      setGlobal("⚠ Primero guarda la URL pública del túnel.");
      return;
    }

    try{
      await navigator.clipboard.writeText(text);
      setGlobal("✅ Copiados todos los WebHooks con nombre. Ya puedes pegarlos en Bloc de notas.");
    }catch(error){
      const area=document.createElement("textarea");
      area.value=text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      setGlobal("✅ WebHooks copiados.");
    }
  };
}

refreshWebhookUrls();
setInterval(refreshWebhookUrls,10000);
