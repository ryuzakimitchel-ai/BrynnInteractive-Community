const $=id=>document.getElementById(id);
let alerts=[],emotes=[],current=null,urls={visualUrl:"",visualType:"",audioUrl:""};
const labels={reward:"Recompensa",follow:"Follow",subscription:"Suscripción",gift:"Regalo",like:"Likes",share:"Share",join:"Viewer Join",bits:"Bits",raid:"Raid",donation:"Donación"};
const platformOrder={twitch:0,tiktok:1,kick:2};
const typeOrder={follow:0,subscription:1,bits:2,raid:3,donation:4,gift:2,like:3,share:4,join:5};
function key(a){return a.platform+":"+a.type}
function status(t){$("status").textContent=t}
function output(){$("volumeOut").textContent=Math.round(Number($("volume").value)*100)+"%"}

function cleanBurst(value){
 const b=value||{};
 return{
  enabled:b.enabled===true,
  source:b.source==="all"?"all":"selected",
  emoteIds:Array.isArray(b.emoteIds)?b.emoteIds.map(String):[],
  mode:["burst","fountain","spray"].includes(b.mode)?b.mode:"burst",
  count:Math.max(1,Math.min(80,Number(b.count||18))),
  size:Math.max(18,Math.min(180,Number(b.size||72))),
  durationMs:Math.max(500,Math.min(8000,Number(b.durationMs||2200))),
  spread:Math.max(80,Math.min(1000,Number(b.spread||420))),
  delayMs:Math.max(0,Math.min(3000,Number(b.delayMs??250)))
 };
}
function selectedBurstIds(){
 return [...document.querySelectorAll('.burst-emote-check:checked')].map(x=>x.value);
}
function syncBurstEnabled(){
 const enabled=$("burstEnabled").checked;
 $("burstOptions").classList.toggle("is-disabled",!enabled);
 $("burstOptions").querySelectorAll("input,select,button").forEach(el=>{
  if(el.id!=="burstEnabled")el.disabled=!enabled;
 });
 if(enabled)syncBurstSource();
}
function syncBurstSource(){
 const selected=$("burstSource").value==="selected";
 document.querySelectorAll('.burst-emote-check').forEach(el=>el.disabled=!selected||!$("burstEnabled").checked);
 $("burstSelectAll").disabled=!selected||!$("burstEnabled").checked;
 $("burstClearAll").disabled=!selected||!$("burstEnabled").checked;
}
function renderBurstEmotes(selectedIds=[]){
 const host=$("burstEmoteList");
 if(!host)return;
 const active=emotes.filter(e=>e&&e.enabled!==false&&e.visualUrl);
 if(!active.length){
  host.innerHTML='<div class="burst-empty">Aún no hay emotes registrados. Créelos primero en la sección Emotes.</div>';
  return;
 }
 const selected=new Set(selectedIds||[]);
 host.innerHTML=active.map(e=>`<label class="burst-emote-item ${selected.has(e.id)?"selected":""}">
   <input class="burst-emote-check" type="checkbox" value="${htmlEscape(e.id)}" ${selected.has(e.id)?"checked":""}>
   <img src="${htmlEscape(e.visualUrl)}" alt="">
   <span title="${htmlEscape(e.name||e.id)}">${htmlEscape(e.name||e.id)}</span>
  </label>`).join('');
 host.querySelectorAll('.burst-emote-check').forEach(input=>input.addEventListener('change',()=>{
  input.closest('.burst-emote-item')?.classList.toggle('selected',input.checked);
 }));
 syncBurstSource();
}
function loadBurstForm(value){
 const b=cleanBurst(value);
 $("burstEnabled").checked=b.enabled;
 $("burstSource").value=b.source;
 $("burstMode").value=b.mode;
 $("burstCount").value=b.count;
 $("burstSize").value=b.size;
 $("burstDuration").value=(b.durationMs/1000).toFixed(1).replace(/\.0$/,'');
 $("burstSpread").value=b.spread;
 $("burstDelay").value=b.delayMs;
 renderBurstEmotes(b.emoteIds);
 syncBurstEnabled();
}
function burstPayload(){
 return{
  enabled:$("burstEnabled").checked,
  source:$("burstSource").value,
  emoteIds:selectedBurstIds(),
  mode:$("burstMode").value,
  count:Number($("burstCount").value||18),
  size:Number($("burstSize").value||72),
  durationMs:Math.round(Number($("burstDuration").value||2.2)*1000),
  spread:Number($("burstSpread").value||420),
  delayMs:Number($("burstDelay").value||250)
 };
}
function renderTabs(){
 alerts.sort((a,b)=>(platformOrder[a.platform]??9)-(platformOrder[b.platform]??9)||(typeOrder[a.type]??99)-(typeOrder[b.type]??99));
 $("tabs").innerHTML=alerts.map(a=>`<button type="button" class="tab ${current&&key(current)===key(a)?"active":""}" data-key="${key(a)}">${a.platform==="twitch"?"🟣 Twitch":a.platform==="kick"?"🟢 Kick":"🎵 TikTok"} · ${labels[a.type]}</button>`).join("");
 document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>load(b.dataset.key))
}
function syncFiles(){$("visualCurrent").textContent=urls.visualUrl||"Sin archivo";$("audioCurrent").textContent=urls.audioUrl||"Sin archivo"}
function load(k){
 const a=alerts.find(x=>key(x)===k);if(!a)return;current=a;urls={visualUrl:a.visualUrl||"",visualType:a.visualType||"",audioUrl:a.audioUrl||""};
 $("titleTemplate").value=a.titleTemplate||"";$("messageTemplate").value=a.messageTemplate||"";$("duration").value=Number(a.durationMs||5000)/1000;$("size").value=a.size||45;$("volume").value=a.audioVolume??.8;$("position").value=a.position||"top-center";$("enterAnimation").value=a.enterAnimation||"pop";$("animation").value=a.animation||"none";$("exitAnimation").value=a.exitAnimation||"fade";$("advancedEnabled").checked=a.advancedEnabled===true;$("autoVisualInAdvanced").checked=a.autoVisualInAdvanced!==false;$("customHtml").value=a.customHtml||"";$("customCss").value=a.customCss||"";$("customJs").value=a.customJs||"";$("enabled").checked=a.enabled!==false;loadBurstForm(a.emoteBurst);syncFiles();output();renderTabs();renderAdvancedPreview();status(`Editando ${a.platform} · ${labels[a.type]}`)
}
async function refresh(){
 const [ar,er]=await Promise.all([
  fetch("/api/alerts-config",{cache:"no-store"}),
  fetch("/api/emotes",{cache:"no-store"})
 ]);
 const d=await ar.json();
 const ed=await er.json();
 alerts=d.alerts||[];
 emotes=ed.emotes||[];
 renderTabs();
 if(!current&&alerts.length)load(key(alerts[0]));
 else if(current)renderBurstEmotes(cleanBurst(current.emoteBurst).emoteIds);
}
async function upload(file,kind){if(!file)return null;const r=await fetch(`/api/upload?kind=${kind}&filename=${encodeURIComponent(file.name)}`,{method:"POST",headers:{"Content-Type":file.type||"application/octet-stream"},body:file});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||"Error subiendo archivo");return d}
$("form").addEventListener("submit",async e=>{e.preventDefault();if(!current)return;try{const visual=await upload($("visualFile").files[0],"visual");if(visual){urls.visualUrl=visual.url;urls.visualType=visual.visualType}const audio=await upload($("audioFile").files[0],"audio");if(audio)urls.audioUrl=audio.url;const alert={...current,titleTemplate:$("titleTemplate").value,messageTemplate:$("messageTemplate").value,durationMs:Math.round(Number($("duration").value||5)*1000),size:Number($("size").value||45),audioVolume:Number($("volume").value||0),position:$("position").value,enterAnimation:$("enterAnimation").value,exitAnimation:$("exitAnimation").value,animation:$("animation").value,advancedEnabled:$("advancedEnabled").checked,autoVisualInAdvanced:$("autoVisualInAdvanced").checked,customHtml:$("customHtml").value,customCss:$("customCss").value,customJs:$("customJs").value,enabled:$("enabled").checked,visualUrl:urls.visualUrl,visualType:urls.visualType,audioUrl:urls.audioUrl,emoteBurst:burstPayload()};const r=await fetch("/api/alerts/save",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({alert})});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||"No se pudo guardar");alerts=d.alerts||[];current=d.alert;$("visualFile").value="";$("audioFile").value="";renderTabs();syncFiles();status("✅ Alerta guardada.")}catch(err){status("❌ "+err.message)}})
$("testBtn").onclick=async()=>{if(!current)return;const r=await fetch("/api/alerts/test",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({platform:current.platform,type:current.type})});const d=await r.json();status(d.ok?"✅ Alerta de prueba enviada.":"❌ "+(d.error||"Error"))}
$("volume").oninput=output;
$("burstEnabled").addEventListener("change",syncBurstEnabled);
$("burstSource").addEventListener("change",syncBurstSource);
$("burstSelectAll").addEventListener("click",()=>{
 document.querySelectorAll('.burst-emote-check').forEach(x=>{x.checked=true;x.closest('.burst-emote-item')?.classList.add('selected')});
});
$("burstClearAll").addEventListener("click",()=>{
 document.querySelectorAll('.burst-emote-check').forEach(x=>{x.checked=false;x.closest('.burst-emote-item')?.classList.remove('selected')});
});
refresh();

const DEFAULT_ADVANCED_HTML = `<div class="custom-alert">
  <img class="avatar" src="{avatar}" alt="">
  <div class="content">
    <div class="platform">{platform}</div>
    <div class="title">{title}</div>
    <div class="message">{message}</div>
    <div class="amount">{amount}</div>
  </div>
  <div class="visual-wrap">
    {visual}
  </div>
</div>`;

const DEFAULT_ADVANCED_CSS = `html,body{
  margin:0;
  width:100%;
  height:100%;
  overflow:hidden;
  background:transparent;
  font-family:Arial,sans-serif;
  color:white;
}
body{
  display:flex;
  align-items:center;
  justify-content:center;
}
.custom-alert{
  width:min(720px,88vw);
  min-height:130px;
  padding:18px 22px;
  display:grid;
  grid-template-columns:84px 1fr auto;
  gap:16px;
  align-items:center;
  background:linear-gradient(135deg,rgba(15,10,20,.96),rgba(55,25,70,.92));
  border:2px solid #8cff3a;
  clip-path:polygon(0 0,calc(100% - 18px) 0,100% 18px,100% 100%,0 100%);
  box-shadow:0 0 28px rgba(140,255,58,.35);
}
.avatar{
  width:76px;
  height:76px;
  border-radius:16px;
  object-fit:cover;
  border:2px solid #8cff3a;
}
.platform{
  color:#8cff3a;
  font-size:12px;
  font-weight:700;
  letter-spacing:1.5px;
}
.title{
  margin-top:4px;
  font-size:25px;
  font-weight:900;
}
.message,.amount{
  margin-top:5px;
  opacity:.78;
}
.visual-wrap img,
.visual-wrap video{
  max-width:160px;
  max-height:120px;
  object-fit:contain;
}`;

const DEFAULT_ADVANCED_JS = `// Datos disponibles:
// ALERT_DATA.user
// ALERT_DATA.platform
// ALERT_DATA.amount
// ALERT_DATA.title
// ALERT_DATA.message
// ALERT_DATA.avatar
// ALERT_DATA.visualUrl
// ALERT_DATA.audioUrl

const root = document.querySelector('.custom-alert');

if (root) {
  root.animate(
    [
      { opacity: 0, transform: 'translateY(-40px) scale(.92)' },
      { opacity: 1, transform: 'translateY(0) scale(1)' }
    ],
    {
      duration: 550,
      easing: 'cubic-bezier(.22,1,.36,1)',
      fill: 'both'
    }
  );
}`;

function htmlEscape(value){
  return String(value ?? '')
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

function previewData(){
  const platform = current?.platform || 'twitch';
  const titleTemplate = $('titleTemplate').value || '{user} activó una alerta';
  const messageTemplate = $('messageTemplate').value || 'Mensaje de prueba';
  const sampleAmounts={gift:'Rose x5 · 5 monedas',like:'100 likes',share:'Compartió el LIVE',join:'Entró al LIVE',bits:'100 Bits',raid:'25 viewers',donation:'$5.00',subscription:'1 mes'};
  const amount = sampleAmounts[current?.type] || '';

  const fill = (text) => String(text || '')
    .replaceAll('{user}','UsuarioDePrueba')
    .replaceAll('{platform}',platform.toUpperCase())
    .replaceAll('{amount}',amount);

  return {
    user:'UsuarioDePrueba',
    platform,
    amount,
    title:fill(titleTemplate),
    message:fill(messageTemplate),
    avatar:'',
    visualUrl:urls.visualUrl || '',
    visualType:urls.visualType || '',
    audioUrl:urls.audioUrl || ''
  };
}

function buildAdvancedSrcdoc(data){
  const origin = window.location.origin;

  const abs = (url) => {
    if (!url) return '';
    try { return new URL(url, origin).href; }
    catch { return url; }
  };

  const avatar = data.avatar
    ? abs(data.avatar)
    : `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(
        `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128">
          <rect width="128" height="128" rx="24" fill="#17111c"/>
          <circle cx="64" cy="45" r="23" fill="#8cff3a"/>
          <path d="M25 112c8-25 29-35 39-35s31 10 39 35" fill="#8a2be2"/>
        </svg>`
      )}`;

  let visual = '';

  if (data.visualUrl) {
    const src = htmlEscape(abs(data.visualUrl));
    visual = data.visualType === 'video'
      ? `<video class="alert-uploaded-visual" autoplay muted loop playsinline src="${src}"></video>`
      : `<img class="alert-uploaded-visual" src="${src}" alt="">`;
  }

  const replacements = {
    '{user}': htmlEscape(data.user),
    '{platform}': htmlEscape(String(data.platform || '').toUpperCase()),
    '{amount}': htmlEscape(data.amount),
    '{avatar}': htmlEscape(avatar),
    '{visual}': visual,
    '{visualUrl}': htmlEscape(abs(data.visualUrl)),
    '{visualType}': htmlEscape(data.visualType || ''),
    '{audio}': htmlEscape(abs(data.audioUrl)),
    '{title}': htmlEscape(data.title),
    '{message}': htmlEscape(data.message)
  };

  let customHtml = $('customHtml').value || DEFAULT_ADVANCED_HTML;

  if (
    visual &&
    $('autoVisualInAdvanced').checked &&
    !customHtml.includes('{visual}') &&
    !customHtml.includes('{visualUrl}')
  ) {
    customHtml += `<div class="brynn-auto-visual">${visual}</div>`;
  }

  for (const [token,value] of Object.entries(replacements)) {
    customHtml = customHtml.split(token).join(value);
  }

  const payload = {
    ...data,
    avatar,
    visualUrl:abs(data.visualUrl),
    audioUrl:abs(data.audioUrl)
  };

  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
.alert-uploaded-visual,.brynn-auto-visual img,.brynn-auto-visual video{max-width:min(40vw,420px);max-height:min(45vh,420px);object-fit:contain}
.brynn-auto-visual{position:fixed;right:4vw;bottom:5vh;z-index:50;pointer-events:none}
${$('customCss').value || DEFAULT_ADVANCED_CSS}</style>
</head>
<body>
${customHtml}
<script>
window.ALERT_DATA=${JSON.stringify(payload).replace(/</g,'\\u003c')};
try{
${$('customJs').value || DEFAULT_ADVANCED_JS}
}catch(error){
  document.body.insertAdjacentHTML(
    'beforeend',
    '<pre style="position:fixed;left:8px;bottom:8px;color:#ff6680;background:#18070c;padding:8px;max-width:90vw;white-space:pre-wrap;">JS ERROR: '+String(error)+'</pre>'
  );
}
<\/script>
</body>
</html>`;
}

function renderAdvancedPreview(){
  if (!$('advancedPreview')) return;
  $('advancedPreview').srcdoc = buildAdvancedSrcdoc(previewData());
}

document.querySelectorAll('.code-tab').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.code-tab').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.code-panel').forEach(x=>x.classList.remove('active'));
    btn.classList.add('active');
    $(btn.dataset.panel).classList.add('active');
  });
});

$('loadTemplateBtn').addEventListener('click',()=>{
  $('customHtml').value=DEFAULT_ADVANCED_HTML;
  $('customCss').value=DEFAULT_ADVANCED_CSS;
  $('customJs').value=DEFAULT_ADVANCED_JS;
  $('advancedEnabled').checked=true;
  renderAdvancedPreview();
  status('Plantilla avanzada cargada.');
});

$('refreshPreviewBtn').addEventListener('click',renderAdvancedPreview);

['customHtml','customCss','customJs','titleTemplate','messageTemplate'].forEach(id=>{
  $(id).addEventListener('input',()=>{
    clearTimeout(window.__advancedPreviewTimer);
    window.__advancedPreviewTimer=setTimeout(renderAdvancedPreview,350);
  });
});

$('autoVisualInAdvanced').addEventListener('change',renderAdvancedPreview);
