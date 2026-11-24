let alertLayout={width:720,scale:100,position:"top-center",accent:"#76ff6a",backgroundOpacity:94,radius:16};
let alertLayoutUpdatedAt="";
async function loadAlertLayout(){
  try{
    const r=await fetch('/api/layout-studio',{cache:'no-store'});
    if(!r.ok)return;
    const d=await r.json();
    const l=d.layout||{};
    if(String(l.updatedAt||'')!==alertLayoutUpdatedAt){
      alertLayoutUpdatedAt=String(l.updatedAt||'');
      alertLayout={...alertLayout,...(l.alerts||{})};
    }
  }catch(e){console.warn('[Brynn Alerts] layout studio',e)}
}
loadAlertLayout();setInterval(loadAlertLayout,4000);
const stage=document.getElementById("stage");
function esc(v){return String(v??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function mediaUrl(u){try{return new URL(u,window.location.origin).href}catch{return u}}
function avatar(user){if(user&&user.avatar)return mediaUrl(user.avatar);const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"><rect width="128" height="128" rx="24" fill="#17111c"/><circle cx="64" cy="45" r="23" fill="#8cff3a"/><path d="M25 112c8-25 29-35 39-35s31 10 39 35" fill="#8a2be2"/></svg>`;return"data:image/svg+xml;charset=UTF-8,"+encodeURIComponent(svg)}
function playAudio(url,volume,duration){if(!url)return;const a=document.createElement("audio");a.src=mediaUrl(url);a.autoplay=true;a.volume=Math.max(0,Math.min(1,Number(volume??.8)));a.style.display="none";document.body.appendChild(a);a.play().catch(()=>{});setTimeout(()=>{try{a.pause()}catch{}a.remove()},Math.max(1500,Number(duration||5000)+500))}


let alertEmotes=[];
async function loadAlertEmotes(){
  try{
    const r=await fetch(`/api/emotes?_=${Date.now()}`,{cache:"no-store"});
    if(!r.ok)return;
    const d=await r.json();
    alertEmotes=(d.emotes||[]).filter(e=>e&&e.enabled!==false&&e.visualUrl);
  }catch(error){
    console.warn("[Brynn Alerts] emote catalog",error);
  }
}
loadAlertEmotes();
setInterval(loadAlertEmotes,15000);

function burstOrigin(anchor,position){
  try{
    if(anchor){
      const r=anchor.getBoundingClientRect();
      if(r.width||r.height){
        return{x:r.left+r.width/2,y:r.top+r.height/2};
      }
    }
  }catch{}
  const w=window.innerWidth,h=window.innerHeight;
  const p=String(position||"center");
  if(p.includes("top"))return{x:w/2,y:Math.max(110,h*.16)};
  if(p.includes("bottom"))return{x:w/2,y:Math.min(h-110,h*.82)};
  return{x:w/2,y:h/2};
}

function resolveBurstEmotes(config){
  const active=alertEmotes.filter(e=>e&&e.visualUrl);
  if(!active.length)return[];
  if(String(config.source||"selected")==="all")return active;
  const wanted=new Set((config.emoteIds||[]).map(String));
  const selected=active.filter(e=>wanted.has(String(e.id)));
  return selected.length?selected:active;
}

function spawnEmoteBurst(alertConfig,anchor){
  const cfg=alertConfig?.emoteBurst||{};
  if(cfg.enabled!==true)return;
  const catalog=resolveBurstEmotes(cfg);
  if(!catalog.length)return;

  const count=Math.max(1,Math.min(80,Number(cfg.count||18)));
  const size=Math.max(18,Math.min(180,Number(cfg.size||72)));
  const duration=Math.max(500,Math.min(8000,Number(cfg.durationMs||2200)));
  const spread=Math.max(80,Math.min(1000,Number(cfg.spread||420)));
  const mode=["burst","fountain","spray"].includes(cfg.mode)?cfg.mode:"burst";
  const origin=burstOrigin(anchor,alertConfig.position||alertLayout.position);

  const layer=document.createElement("div");
  layer.className="emote-confetti-layer";
  stage.appendChild(layer);

  for(let i=0;i<count;i++){
    const emote=catalog[Math.floor(Math.random()*catalog.length)];
    const img=document.createElement("img");
    img.className="emote-confetti-particle";
    img.src=mediaUrl(emote.visualUrl);
    img.alt="";
    img.style.width=`${size*(.65+Math.random()*.7)}px`;
    img.style.height=img.style.width;
    img.style.left=`${origin.x}px`;
    img.style.top=`${origin.y}px`;
    layer.appendChild(img);

    const rot=(Math.random()>.5?1:-1)*(240+Math.random()*760);
    const delay=Math.random()*180;
    let frames;

    if(mode==="fountain"){
      const x=(Math.random()-.5)*spread*.85;
      const peak=-(spread*.58+Math.random()*spread*.45);
      const fall=spread*.35+Math.random()*spread*.45;
      frames=[
        {transform:`translate(-50%,-50%) scale(.25) rotate(0deg)`,opacity:0},
        {offset:.10,transform:`translate(-50%,-50%) scale(1) rotate(${rot*.12}deg)`,opacity:1},
        {offset:.56,transform:`translate(calc(-50% + ${x*.65}px),calc(-50% + ${peak}px)) scale(1.05) rotate(${rot*.58}deg)`,opacity:1},
        {transform:`translate(calc(-50% + ${x}px),calc(-50% + ${fall}px)) scale(.72) rotate(${rot}deg)`,opacity:0}
      ];
    }else if(mode==="spray"){
      const direction=(Math.random()-.5)*1.5;
      const distance=spread*(.45+Math.random()*.65);
      const x=Math.sin(direction)*distance;
      const y=-Math.cos(direction)*distance*.58 + (Math.random()-.5)*spread*.18;
      frames=[
        {transform:`translate(-50%,-50%) scale(.2) rotate(0deg)`,opacity:0},
        {offset:.13,transform:`translate(-50%,-50%) scale(1.1) rotate(${rot*.15}deg)`,opacity:1},
        {transform:`translate(calc(-50% + ${x}px),calc(-50% + ${y}px)) scale(.7) rotate(${rot}deg)`,opacity:0}
      ];
    }else{
      const angle=Math.random()*Math.PI*2;
      const distance=spread*(.35+Math.random()*.7);
      const x=Math.cos(angle)*distance;
      const y=Math.sin(angle)*distance;
      frames=[
        {transform:`translate(-50%,-50%) scale(.18) rotate(0deg)`,opacity:0},
        {offset:.12,transform:`translate(-50%,-50%) scale(1.12) rotate(${rot*.12}deg)`,opacity:1},
        {offset:.72,opacity:1},
        {transform:`translate(calc(-50% + ${x}px),calc(-50% + ${y}px)) scale(.68) rotate(${rot}deg)`,opacity:0}
      ];
    }

    const anim=img.animate(frames,{duration:duration*(.82+Math.random()*.34),delay,easing:"cubic-bezier(.15,.75,.2,1)",fill:"forwards"});
    anim.finished.catch(()=>{}).finally(()=>img.remove());
  }

  setTimeout(()=>layer.remove(),duration+700);
}

function scheduleEmoteBurst(alertConfig,anchor){
  const cfg=alertConfig?.emoteBurst||{};
  if(cfg.enabled!==true)return;
  const delay=Math.max(0,Math.min(3000,Number(cfg.delayMs||0)));
  setTimeout(()=>spawnEmoteBurst(alertConfig,anchor),delay);
}

function fillTokens(text,data){
  return String(text||"")
    .replaceAll("{user}", data.user||"")
    .replaceAll("{platform}", String(data.platform||"").toUpperCase())
    .replaceAll("{amount}", data.amount||"")
    .replaceAll("{avatar}", data.avatar||"")
    .replaceAll("{title}", data.title||"")
    .replaceAll("{message}", data.message||"");
}

function buildAdvancedAlertSrcdoc(event){
  const a=event.alert||{};
  const user=event.user||{};
  const origin=window.location.origin;

  const abs=(url)=>{
    if(!url)return"";
    try{return new URL(url,origin).href}catch{return url}
  };

  const fallbackAvatar=avatar(user);
  const visualUrl=abs(a.visualUrl||"");
  const audioUrl=abs(a.audioUrl||"");

  let visual="";

  if(visualUrl){
    visual=a.visualType==="video"
      ? `<video class="alert-uploaded-visual" autoplay playsinline src="${esc(visualUrl)}"></video>`
      : `<img class="alert-uploaded-visual" src="${esc(visualUrl)}" alt="">`;
  }

  const data={
    user:user.username||"Usuario",
    platform:user.platform||"",
    amount:event.amount||"",
    avatar:user.avatar?abs(user.avatar):fallbackAvatar,
    title:a.title||"",
    message:a.message||"",
    visualUrl,
    visualType:a.visualType||"",
    audioUrl
  };

  let html=a.customHtml||`<div class="custom-alert">
    <img class="avatar" src="{avatar}" alt="">
    <div>
      <div class="platform">{platform}</div>
      <div class="title">{title}</div>
      <div class="message">{message}</div>
      <div class="amount">{amount}</div>
    </div>
    <div class="visual-wrap">{visual}</div>
  </div>`;

  const replacements={
    "{user}":esc(data.user),
    "{platform}":esc(String(data.platform).toUpperCase()),
    "{amount}":esc(data.amount),
    "{avatar}":esc(data.avatar),
    "{visual}":visual,
    "{visualUrl}":esc(visualUrl),
    "{visualType}":esc(a.visualType||""),
    "{audio}":esc(audioUrl),
    "{title}":esc(data.title),
    "{message}":esc(data.message)
  };

  if(
    visual &&
    a.autoVisualInAdvanced!==false &&
    !html.includes("{visual}") &&
    !html.includes("{visualUrl}")
  ){
    html += `<div class="brynn-auto-visual">${visual}</div>`;
  }

  for(const [token,value] of Object.entries(replacements)){
    html=html.split(token).join(value);
  }

  const css=a.customCss||`html,body{
    margin:0;width:100%;height:100%;overflow:hidden;background:transparent;
    font-family:Arial,sans-serif;color:white
  }
  body{display:flex;align-items:center;justify-content:center}
  .custom-alert{
    width:min(720px,88vw);padding:18px;display:grid;grid-template-columns:80px 1fr auto;
    gap:16px;align-items:center;background:rgba(20,12,26,.95);border:2px solid #8cff3a
  }
  .avatar{width:72px;height:72px;border-radius:15px;object-fit:cover}
  .platform{color:#8cff3a;font-size:12px;font-weight:bold}
  .title{font-size:26px;font-weight:900}
  .message,.amount{opacity:.75;margin-top:5px}
  .visual-wrap img,.visual-wrap video{max-width:160px;max-height:120px;object-fit:contain}`;

  const customJs=a.customJs||"";

  return `<!doctype html>
<html>
<head><meta charset="utf-8"><style>
.alert-uploaded-visual,.brynn-auto-visual img,.brynn-auto-visual video{max-width:min(40vw,420px);max-height:min(45vh,420px);object-fit:contain}
.brynn-auto-visual{position:fixed;right:4vw;bottom:5vh;z-index:50;pointer-events:none}
${css}</style></head>
<body>
${html}
<script>
window.ALERT_DATA=${JSON.stringify(data).replace(/</g,"\\u003c")};
try{
${customJs}
}catch(error){
  document.body.insertAdjacentHTML(
    "beforeend",
    "<pre style='position:fixed;left:8px;bottom:8px;color:#ff6680;background:#18070c;padding:8px;white-space:pre-wrap;'>JS ERROR: "+String(error)+"</pre>"
  );
}
<\/script>
</body>
</html>`;
}

function showAdvanced(event){
  const a=event.alert||{};
  const root=document.createElement("div");
  root.className="alert-root a-pos-fullscreen";

  const iframe=document.createElement("iframe");
  iframe.className="advanced-alert-frame";
  iframe.style.scale=String(Math.max(.5,Math.min(1.8,Number(alertLayout.scale||100)/100)));
  iframe.style.transformOrigin="center center";
  iframe.setAttribute("sandbox","allow-scripts");
  iframe.setAttribute("allow","autoplay");
  iframe.srcdoc=buildAdvancedAlertSrcdoc(event);

  root.appendChild(iframe);
  stage.appendChild(root);
  scheduleEmoteBurst(a,null);

  playAudio(
    a.audioUrl,
    a.audioVolume,
    a.durationMs
  );

  const duration=Math.max(1000,Number(a.durationMs||5000));

  setTimeout(()=>{
    iframe.style.transition="opacity .45s ease";
    iframe.style.opacity="0";
  },Math.max(250,duration-500));

  setTimeout(()=>root.remove(),duration+150);

  return duration + 200;
}

function show(event){
  const a=event.alert||{},user=event.user||{};

  if(a.advancedEnabled===true){
    return showAdvanced(event);
  }

  const root=document.createElement("div");
  root.className=`alert-root a-pos-${alertLayout.position||a.position||"top-center"}`;

  const exit=document.createElement("div");
  exit.className="exit-wrap";

  const enter=document.createElement("div");
  enter.className=`enter-wrap enter-${a.enterAnimation||"pop"}`;

  const motion=document.createElement("div");
  motion.className=`motion-${a.animation||"none"}`;

  const platformAccent=user.platform==="tiktok"?"#ff4f8a":"#a970ff";
  const accent=/^#[0-9a-f]{6}$/i.test(String(alertLayout.accent||""))?alertLayout.accent:platformAccent;
  motion.style.setProperty("--accent",accent);
  motion.style.scale=String(Math.max(.5,Math.min(1.8,Number(alertLayout.scale||100)/100)));
  motion.style.setProperty("--size",`${Number(a.size||45)}vmin`);

  let visual="";

  if(a.visualUrl){
    if(a.visualType==="video"){
      visual=`<video class="alert-visual" autoplay playsinline src="${esc(mediaUrl(a.visualUrl))}"></video>`;
    }else{
      visual=`<img class="alert-visual" src="${esc(mediaUrl(a.visualUrl))}">`;
    }
  }

  motion.innerHTML=`<article class="alert-card" style="--accent:${accent}">
    <img class="avatar" src="${avatar(user)}">
    <div class="platform">${esc((user.platform||"").toUpperCase())} · ${esc((a.type||"ALERTA").toUpperCase())}</div>
    <div class="title">${esc(a.title||user.username||"")}</div>
    <div class="message">${esc(a.message||"")}</div>
    ${visual}
  </article>`;

  const card=motion.querySelector('.alert-card');
  if(card){
    const width=Math.max(220,Math.min(1600,Number(alertLayout.width||720)));
    const opacity=Math.max(0,Math.min(100,Number(alertLayout.backgroundOpacity||94)))/100;
    const radius=Math.max(0,Math.min(48,Number(alertLayout.radius||16)));
    card.style.width=`min(${width}px,88vw)`;
    card.style.maxWidth=`min(${width}px,88vw)`;
    card.style.borderRadius=radius+'px';
    card.style.background=`linear-gradient(135deg,rgba(11,8,17,${opacity}),rgba(43,21,55,${Math.max(0,opacity-.05)}))`;
  }

  enter.appendChild(motion);
  exit.appendChild(enter);
  root.appendChild(exit);
  stage.appendChild(root);
  scheduleEmoteBurst(a,card);

  playAudio(a.audioUrl,a.audioVolume,a.durationMs);

  const d=Math.max(1000,Number(a.durationMs||5000));

  setTimeout(()=>{
    exit.className=`exit-wrap exit-${a.exitAnimation||"fade"}`;
  },Math.max(250,d-650));

  setTimeout(()=>root.remove(),d+300);

  return d + 350;
}


let last=0;
let busy=false;
let initialized=false;
let serverSession=null;

const alertQueue=[];
let queueRunning=false;

function sleep(ms){
  return new Promise(resolve=>setTimeout(resolve,ms));
}

async function runAlertQueue(){
  if(queueRunning)return;

  queueRunning=true;

  try{
    while(alertQueue.length){
      const event=alertQueue.shift();

      let waitMs=0;

      try{
        waitMs=Number(show(event)||0);
      }catch(error){
        console.warn("[Brynn Alerts] render error",error);
      }

      // Evita que dos alertas se monten una encima de otra y garantiza
      // que una segunda alerta siempre pueda reproducirse después.
      await sleep(
        Math.max(
          250,
          waitMs
        )
      );
    }
  }finally{
    queueRunning=false;

    if(alertQueue.length){
      runAlertQueue();
    }
  }
}

function enqueueAlert(event){
  if(!event)return;

  alertQueue.push(event);
  runAlertQueue();
}


const DEBUG_ALERTS = new URLSearchParams(location.search).get("debug")==="1";
let debugBox=null;

function setDebug(text){
  if(!DEBUG_ALERTS)return;

  if(!debugBox){
    debugBox=document.createElement("div");
    debugBox.style.cssText=[
      "position:fixed",
      "left:8px",
      "bottom:8px",
      "z-index:999999",
      "background:rgba(0,0,0,.82)",
      "color:#8cff3a",
      "font:12px Consolas,monospace",
      "padding:7px 9px",
      "border:1px solid #8cff3a",
      "border-radius:5px",
      "pointer-events:none"
    ].join(";");

    document.body.appendChild(debugBox);
  }

  debugBox.textContent=text;
}

async function poll(){
  if(busy)return;
  busy=true;

  try{
    const r=await fetch(
      `/api/events?after=${last}&_=${Date.now()}`,
      {
        cache:"no-store",
        headers:{
          "Cache-Control":"no-cache"
        }
      }
    );

    if(!r.ok){
      throw new Error(
        `HTTP ${r.status}`
      );
    }

    const d=await r.json();

    setDebug(
      `OBS conectado · session=${String(d.sessionId||"").slice(0,6)} · latest=${Number(d.latestId||0)} · queue=${alertQueue.length}`
    );

    const incomingSession=String(
      d.sessionId||""
    );

    const latestId=Number(
      d.latestId||0
    );

    /*
      Primera carga:
      no reproducimos alertas viejas que sigan en la memoria del servidor.
      Solo empezamos a escuchar desde "ahora".
    */
    if(!initialized){
      initialized=true;
      serverSession=incomingSession;

      const now=Date.now();

      for(const e of(d.events||[])){
        const id=Number(e.id||0);
        if(id>last)last=id;

        const ageMs=Math.abs(
          now-Date.parse(e.time||"")
        );

        if(
          e.type==="stream_alert" &&
          Number.isFinite(ageMs) &&
          ageMs<=8000
        ){
          enqueueAlert(e);
        }
      }

      if(latestId>last)last=latestId;
      return;
    }

    /*
      Si python server.py se reinicia, EVENT_COUNTER vuelve a cero.
      Antes V23 se quedaba esperando IDs mayores que el contador viejo,
      por eso OBS parecía "muerto" hasta refrescar la fuente.
    */
    if(
      incomingSession &&
      serverSession &&
      incomingSession!==serverSession
    ){
      console.info(
        "[Brynn Alerts] server restart detected",
        serverSession,
        "->",
        incomingSession
      );

      serverSession=incomingSession;
      last=0;
      alertQueue.length=0;

      const now=Date.now();

      for(const e of(d.events||[])){
        const id=Number(e.id||0);
        if(id>last)last=id;

        const ageMs=Math.abs(
          now-Date.parse(e.time||"")
        );

        if(
          e.type==="stream_alert" &&
          Number.isFinite(ageMs) &&
          ageMs<=8000
        ){
          enqueueAlert(e);
        }
      }

      if(latestId>last)last=latestId;
      return;
    }

    if(incomingSession){
      serverSession=incomingSession;
    }

    for(const e of(d.events||[])){
      const id=Number(e.id||0);

      if(id>last){
        last=id;
      }

      if(e.type==="stream_alert"){
        enqueueAlert(e);
      }
    }

    if(latestId>last){
      last=latestId;
    }
  }catch(error){
    setDebug(
      "ERROR polling: " + String(error)
    );

    console.warn(
      "[Brynn Alerts] polling error",
      error
    );
  }finally{
    busy=false;
  }
}

poll();
setInterval(poll,350);
