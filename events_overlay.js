const cardZone = document.getElementById("event-card-zone");
const stage = document.getElementById("effect-stage");
let lastEventId = 0;
let polling = false;

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function placeholderAvatar() {
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"><defs><linearGradient id="g" x1="0" x2="1"><stop stop-color="#8CFF3A"/><stop offset="1" stop-color="#8A2BE2"/></linearGradient></defs><rect width="128" height="128" rx="24" fill="#17111c"/><circle cx="64" cy="45" r="23" fill="url(#g)"/><path d="M25 112c8-25 29-35 39-35s31 10 39 35" fill="url(#g)"/></svg>`;
  return "data:image/svg+xml;charset=UTF-8,"+encodeURIComponent(svg);
}
function avatar(user){return user&&user.avatar?user.avatar:placeholderAvatar();}
function platform(user){if(!user)return"";if(user.platform==="twitch")return"TWITCH";if(user.platform==="tiktok")return"TIKTOK";return String(user.platform||"").toUpperCase();}
function itemMark(item){
  if(item&&item.badgeUrl) return `<img class="inline-badge" src="${esc(item.badgeUrl)}" alt="">`;
  return esc((item&&item.icon)||"✦");
}
function currencyInfo(event){
  return event&&event.currency?event.currency:{singular:'Gumpita',plural:'Gumpitas',symbol:'💀',imageUrl:''};
}
function currencyName(currency,amount){
  const n=Number(amount);return n===1?(currency.singular||'Gumpita'):(currency.plural||'Gumpitas');
}
function currencyText(event,amount){
  const c=currencyInfo(event);return `${amount} ${c.symbol||''} ${currencyName(c,amount)}`.trim();
}
function currencyVisualHtml(currency){
  if(currency&&currency.imageUrl){return `<img class="currency-image" src="${esc(resolveMediaUrl(currency.imageUrl))}" alt="${esc(currency.plural||'Moneda')}">`;}
  return `<span class="currency-symbol">${esc((currency&&currency.symbol)||'💀')}</span>`;
}
function redeemReplace(source,event){
  const c=currencyInfo(event),item=event.item||event.emote||{},user=event.user||{};
  const tokens={
    '{user}':esc(user.username||'Usuario'),'{platform}':esc(platform(user)),
    '{reward}':esc(item.name||item.id||'Canje'),'{cost}':esc(item.cost??0),
    '{currencyName}':esc(currencyName(c,item.cost??0)),'{currencySingular}':esc(c.singular||'Moneda'),
    '{currencyPlural}':esc(c.plural||'Monedas'),'{currencySymbol}':esc(c.symbol||''),
    '{currencyImage}':esc(c.imageUrl||''),'{currencyVisual}':currencyVisualHtml(c),
    '{balanceBefore}':esc(event.balanceBefore??''),'{balanceAfter}':esc(event.balance??''),
    '{message}':esc(event.message||'')
  };
  let out=String(source||'');for(const [k,v] of Object.entries(tokens))out=out.split(k).join(v);return out;
}
function redeemAnchorCss(render){
  const pos=String(render.position||'center');const x=Number(render.offsetX||0),y=Number(render.offsetY||0),scale=Math.max(.25,Math.min(2.5,Number(render.scale||100)/100));
  const map={
    'top-left':['left:18px;top:18px;','translate(0,0)','top left'],'top-center':['left:50%;top:18px;','translate(-50%,0)','top center'],'top-right':['right:18px;top:18px;','translate(0,0)','top right'],
    'center-left':['left:18px;top:50%;','translate(0,-50%)','center left'],'center':['left:50%;top:50%;','translate(-50%,-50%)','center center'],'center-right':['right:18px;top:50%;','translate(0,-50%)','center right'],
    'bottom-left':['left:18px;bottom:18px;','translate(0,0)','bottom left'],'bottom-center':['left:50%;bottom:18px;','translate(-50%,0)','bottom center'],'bottom-right':['right:18px;bottom:18px;','translate(0,0)','bottom right']
  };
  const [edge,base,origin]=map[pos]||map.center;
  return `#brynn-redeem-anchor{position:absolute;${edge}width:max-content;max-width:calc(100% - 36px);transform:${base} translate(${x}px,${y}px) scale(${scale});transform-origin:${origin};}`;
}
function showRedeemPresentation(event){
  const render=event.presentation||{};if(render.enabled===false)return false;
  const duration=Math.max(800,Math.min(30000,Number(render.durationMs||4600)));
  const host=document.createElement('div');host.className='weekly-entrance-host redeem-custom-host';
  const frame=document.createElement('iframe');frame.className='weekly-entrance-frame';frame.setAttribute('sandbox','allow-scripts');frame.setAttribute('title','Presentación de canje');
  const html=redeemReplace(render.html||'',event);const css=redeemReplace(render.css||'',event);const customJs=String(render.js||'');
  const data=JSON.stringify({user:event.user||{},item:event.item||event.emote||{},currency:currencyInfo(event),balanceBefore:event.balanceBefore,balanceAfter:event.balance,testUser:Boolean(event.testUser),ownerOverride:Boolean(event.ownerOverride)});
  frame.srcdoc=`<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}${css}${redeemAnchorCss(render)}</style></head><body><div id="brynn-redeem-anchor">${html}</div><script>window.REDEEM_DATA=${data};window.REDEEM_ROOT=document.getElementById('brynn-redeem-anchor');try{const code=${JSON.stringify(customJs)};if(code.trim())new Function('REDEEM_DATA','REDEEM_ROOT',code)(window.REDEEM_DATA,window.REDEEM_ROOT);}catch(e){console.warn('[Brynn redeem JS]',e)}<\/script></body></html>`;
  host.appendChild(frame);stage.appendChild(host);requestAnimationFrame(()=>host.classList.add('show'));setTimeout(()=>host.classList.add('out'),Math.max(300,duration-450));setTimeout(()=>host.remove(),duration+120);return true;
}
function showCard({user,kicker,title,body,html,accent="#8CFF3A",duration=5200,redeem=false}){
  const card=document.createElement("article");
  card.className="event-card"+(redeem?" redeem-flash":"");card.style.setProperty("--accent",accent);
  card.innerHTML=`<img class="event-avatar" src="${avatar(user)}" alt=""><div class="event-kicker">${esc(kicker||platform(user))}</div><div class="event-title">${title||""}</div>${body?`<div class="event-body">${esc(body)}</div>`:""}${html||""}`;
  cardZone.appendChild(card);setTimeout(()=>{card.classList.add("out");setTimeout(()=>card.remove(),380);},duration);
}
function storeHtml(items,event){const c=currencyInfo(event);return `<div class="store-grid">${(items||[]).slice(0,8).map(item=>`<div class="store-item">${itemMark(item)} <strong>!${esc(item.id)}</strong> · ${esc(item.cost)} ${esc(c.symbol||"")} ${esc(currencyName(c,item.cost))}</div>`).join("")}</div>`;}
function topHtml(rows,scoreField="balance"){const icons=["👑","🥈","🥉"];return `<div class="top-lines">${(rows||[]).slice(0,3).map((row,index)=>`<div class="top-line"><span>${icons[index]||"✦"} ${esc(row.username)}</span><b>${esc(row[scoreField]??row.score??0)}</b></div>`).join("")}</div>`;}

function resolveMediaUrl(url){
  if(!url) return "";
  try{return new URL(url,window.location.origin).href;}catch{return String(url);}
}
function mediaDebug(kind,url,error){console.warn(`[Brynn ${kind}]`,url,error||"");}
function playAudio(url, volume=.8, cutoffMs=0, fadeOutMs=600, cutAtDuration=true, trimStartMs=0, trimEndMs=0){
  if(!url) return null;
  const resolved=resolveMediaUrl(url);
  const audio=document.createElement("audio");
  audio.className="command-audio";audio.src=resolved;audio.preload="auto";audio.autoplay=false;audio.controls=false;
  const targetVolume=Math.max(0,Math.min(1,Number(volume)||0));audio.volume=targetVolume;audio.style.display="none";document.body.appendChild(audio);
  let stopped=false,fadeRaf=0,fadeTimer=0,stopTimer=0,safetyTimer=0;
  const cleanup=()=>{if(stopped)return;stopped=true;if(fadeRaf)cancelAnimationFrame(fadeRaf);clearTimeout(fadeTimer);clearTimeout(stopTimer);clearTimeout(safetyTimer);try{audio.pause();}catch{} audio.remove();};
  const start=Math.max(0,Number(trimStartMs)||0);
  const requestedEnd=Math.max(0,Number(trimEndMs)||0);
  const fadeStop=(fadeDuration)=>{
    const fade=Math.max(0,Number(fadeDuration)||0);
    if(fade<=0){cleanup();return;}
    const started=performance.now();
    const tick=now=>{if(stopped||audio.ended)return;const t=Math.min(1,(now-started)/fade);audio.volume=targetVolume*(1-t);if(t<1)fadeRaf=requestAnimationFrame(tick);else cleanup();};
    fadeRaf=requestAnimationFrame(tick);
  };
  const startPlayback=()=>{
    if(stopped)return;
    const naturalEnd=requestedEnd>start?Math.min(requestedEnd,Number.isFinite(audio.duration)?audio.duration*1000:requestedEnd):(Number.isFinite(audio.duration)?audio.duration*1000:0);
    const trimmedDuration=naturalEnd>start?naturalEnd-start:0;
    let effectiveCutoff=trimmedDuration;
    const commandCutoff=Math.max(0,Number(cutoffMs)||0);
    if(cutAtDuration&&commandCutoff>0)effectiveCutoff=trimmedDuration>0?Math.min(trimmedDuration,commandCutoff):commandCutoff;
    else if(!cutAtDuration&&trimmedDuration<=0)effectiveCutoff=0;
    try{audio.currentTime=Math.min(Number.isFinite(audio.duration)?Math.max(0,audio.duration-.01):start/1000,start/1000);}catch{}
    const promise=audio.play();if(promise&&promise.catch)promise.catch(err=>mediaDebug("audio PLAY bloqueado",resolved,err));
    const fade=Math.max(0,Math.min(Number(fadeOutMs)||0,effectiveCutoff));
    if(effectiveCutoff>0){if(fade>0)fadeTimer=setTimeout(()=>fadeStop(fade),Math.max(0,effectiveCutoff-fade));else stopTimer=setTimeout(cleanup,effectiveCutoff)}
    safetyTimer=setTimeout(cleanup,Math.max(300000,effectiveCutoff+10000));
  };
  audio.addEventListener("ended",cleanup,{once:true});audio.addEventListener("error",()=>{mediaDebug("audio ERROR",resolved,audio.error);cleanup();},{once:true});
  if(audio.readyState>=1)startPlayback();else audio.addEventListener("loadedmetadata",startPlayback,{once:true});
  audio.load();
  return audio;
}

function randomBetween(min,max){return min+Math.random()*(max-min);}
function stickerPoint(pattern,index,total){
  const p=String(pattern||'scatter');
  if(p==='center')return{x:50+randomBetween(-5,5),y:50+randomBetween(-5,5),dx:randomBetween(-80,80),dy:randomBetween(-70,70)};
  if(p==='burst'){const a=(Math.PI*2*(index/Math.max(1,total)))+randomBetween(-.2,.2);const r=randomBetween(130,390);return{x:50,y:50,dx:Math.cos(a)*r,dy:Math.sin(a)*r};}
  if(p==='fountain'){return{x:50+randomBetween(-5,5),y:92,dx:randomBetween(-260,260),dy:randomBetween(-520,-260)};}
  if(p==='rain'){return{x:randomBetween(4,96),y:-8-randomBetween(0,18),dx:randomBetween(-45,45),dy:window.innerHeight*1.3};}
  if(p==='edges'){
    const side=index%4;if(side===0)return{x:-6,y:randomBetween(10,90),dx:window.innerWidth*.58,dy:randomBetween(-100,100)};
    if(side===1)return{x:106,y:randomBetween(10,90),dx:-window.innerWidth*.58,dy:randomBetween(-100,100)};
    if(side===2)return{x:randomBetween(10,90),y:-8,dx:randomBetween(-120,120),dy:window.innerHeight*.58};
    return{x:randomBetween(10,90),y:108,dx:randomBetween(-120,120),dy:-window.innerHeight*.58};
  }
  if(p==='wave'){return{x:8+(84*(index/Math.max(1,total-1))),y:50+Math.sin(index*.9)*18,dx:randomBetween(-35,35),dy:randomBetween(-40,40)};}
  if(p==='orbit'){const a=Math.PI*2*(index/Math.max(1,total));return{x:50+Math.cos(a)*22,y:50+Math.sin(a)*22,dx:0,dy:0};}
  return{x:randomBetween(8,92),y:randomBetween(12,88),dx:randomBetween(-70,70),dy:randomBetween(-70,70)};
}
function spawnSticker(item,options={}){
  if(!item||!item.visualUrl)return null;
  const duration=Math.max(250,Number(options.durationMs||item.durationMs||1800));
  const point=stickerPoint(options.pattern||'scatter',Number(options.index||0),Number(options.total||1));
  const outer=document.createElement('div');outer.className=`timeline-sticker path-${options.pattern||'scatter'}`;
  outer.style.left=`${point.x}%`;outer.style.top=`${point.y}%`;outer.style.setProperty('--sticker-size',`${Math.max(6,Math.min(100,Number(options.size||item.size||24)))}vmin`);outer.style.setProperty('--sticker-duration',`${duration}ms`);outer.style.setProperty('--path-dx',`${point.dx}px`);outer.style.setProperty('--path-dy',`${point.dy}px`);outer.style.setProperty('--path-rot',`${randomBetween(-55,55)}deg`);
  const path=document.createElement('div');path.className='sticker-path';
  const exit=document.createElement('div');exit.className='sticker-exit';
  const enter=document.createElement('div');enter.className=`sticker-enter enter-${options.enterAnimation||item.enterAnimation||'pop'}`;
  const motion=document.createElement('div');motion.className=`sticker-motion motion-${options.animation||item.animation||'float'}`;
  const media=item.visualType==='video'?document.createElement('video'):document.createElement('img');media.className='timeline-sticker-media';media.src=resolveMediaUrl(item.visualUrl);
  if(media.tagName==='VIDEO'){media.autoplay=true;media.playsInline=true;media.loop=true;media.muted=true;const pr=media.play();if(pr&&pr.catch)pr.catch(()=>{});}
  path.appendChild(exit);exit.appendChild(enter);enter.appendChild(motion);motion.appendChild(media);outer.appendChild(path);stage.appendChild(outer);
  const exitAt=Math.max(80,duration-520);setTimeout(()=>{exit.className=`sticker-exit exit-${options.exitAnimation||item.exitAnimation||'fade'}`;},exitAt);
  setTimeout(()=>{try{if(media.pause)media.pause()}catch{}outer.remove();},duration+180);return outer;
}
function playStickerTimeline(item){
  if(item.stickerTimelineEnabled!==true||!Array.isArray(item.stickerTimeline))return;
  for(const cue of item.stickerTimeline){
    if(!cue||!cue.emote||!cue.emote.visualUrl)continue;
    const start=Math.max(0,Number(cue.atMs||0));const qty=Math.max(1,Math.min(60,Number(cue.quantity||1)));const stagger=Math.max(0,Number(cue.staggerMs||0));
    for(let i=0;i<qty;i++)setTimeout(()=>spawnSticker(cue.emote,{durationMs:cue.durationMs,animation:cue.animation,enterAnimation:cue.enterAnimation,exitAnimation:cue.exitAnimation,size:cue.size,pattern:cue.pattern,index:i,total:qty}),start+i*stagger);
  }
}
function effectGlitch(duration=1800){const el=document.createElement("div");el.className="fx-glitch";el.style.animationDuration=`${duration}ms`;stage.appendChild(el);setTimeout(()=>el.remove(),duration+250);}
function effectFog(duration=5200){for(let i=0;i<5;i++){const el=document.createElement("div");el.className="fx-fog";el.style.animationDuration=`${duration}ms`;el.style.animationDelay=`${i*.22}s`;el.style.bottom=`${-18+i*9}vh`;stage.appendChild(el);setTimeout(()=>el.remove(),duration+1800);}const flash=document.createElement("div");flash.className="fx-glitch";flash.style.animationDuration=".55s";stage.appendChild(flash);setTimeout(()=>flash.remove(),800);}
function effectBats(duration=4600){for(let i=0;i<14;i++){const el=document.createElement("div");el.className="fx-bat";el.textContent="🦇";el.style.left=`${-15-Math.random()*25}vw`;el.style.top=`${10+Math.random()*75}vh`;el.style.animationDuration=`${Math.max(1800,duration*(.78+Math.random()*.3))}ms`;el.style.animationDelay=`${i*.12}s`;stage.appendChild(el);setTimeout(()=>el.remove(),duration+1800);}}
function effectPumpkins(duration=4700){for(let i=0;i<14;i++){const el=document.createElement("div");el.className="fx-pumpkin";el.textContent="🎃";el.style.left=`${4+Math.random()*90}vw`;el.style.animationDuration=`${duration}ms`;el.style.animationDelay=`${Math.random()*1.1}s`;el.style.fontSize=`${28+Math.random()*36}px`;stage.appendChild(el);setTimeout(()=>el.remove(),duration+1600);}}
function effectBonk(duration=1300){const el=document.createElement("div");el.className="fx-bonk";el.textContent="BONK!";el.style.animationDuration=`${duration}ms`;stage.appendChild(el);setTimeout(()=>el.remove(),duration+150);}
function effectScare(duration=2450){
  const el=document.createElement("div");el.className="fx-scare";el.style.animationDuration=`${duration}ms`;
  el.innerHTML=`<div class="terror-face"><div class="terror-eye left"></div><div class="terror-eye right"></div><div class="terror-nose"></div><div class="terror-mouth"><i></i><i></i><i></i><i></i><i></i><i></i></div></div>`;
  stage.appendChild(el);setTimeout(()=>el.remove(),duration+120);
}
function playBuiltIn(item){const effect=String(item.effect||"media");const d=Number(item.durationMs||3000);if(effect==="glitch")effectGlitch(d);else if(effect==="fog")effectFog(d);else if(effect==="bats")effectBats(d);else if(effect==="pumpkins")effectPumpkins(d);else if(effect==="bonk")effectBonk(d);else if(effect==="scare")effectScare(d);}
function playCustomVisual(item){
  if(!item.visualUrl) return null;

  const resolved=resolveMediaUrl(item.visualUrl);
  const outer=document.createElement("div");
  outer.className=`custom-media-position pos-${item.position||"center"}`;
  outer.style.setProperty("--media-size",`${Number(item.size||62)}vmin`);
  outer.style.setProperty("--media-duration",`${Number(item.durationMs||3000)}ms`);

  const exitWrap=document.createElement("div");
  exitWrap.className="media-exit-wrap";

  const enterWrap=document.createElement("div");
  enterWrap.className=`media-enter-wrap enter-${item.enterAnimation||"pop"}`;

  const animator=document.createElement("div");
  animator.className=`custom-media-animator motion-${item.animation||"none"}`;

  outer.appendChild(exitWrap);
  exitWrap.appendChild(enterWrap);
  enterWrap.appendChild(animator);

  let media;

  if(item.visualType==="video"){
    media=document.createElement("video");
    media.src=resolved;
    media.autoplay=true;
    media.playsInline=true;
    media.preload="auto";
    media.loop=false;
    media.controls=false;
    media.volume=Math.max(0,Math.min(1,Number(item.audioVolume||.8)));
    media.addEventListener("error",()=>mediaDebug("video ERROR",resolved,media.error),{once:true});
  }else{
    media=document.createElement("img");
    media.src=resolved;
    media.alt="";
    media.decoding="async";
    media.addEventListener("error",()=>mediaDebug("imagen ERROR",resolved),{once:true});
  }

  media.className="custom-media-content";
  animator.appendChild(media);
  stage.appendChild(outer);

  if(media.tagName==="VIDEO"){
    media.load();
    const promise=media.play();
    if(promise&&promise.catch){
      promise.catch(err=>mediaDebug("video PLAY bloqueado",resolved,err));
    }
  }

  const duration=Math.max(700,Number(item.durationMs||3000));
  const exitAt=Math.max(250,duration-650);

  setTimeout(()=>{
    exitWrap.className=`media-exit-wrap exit-${item.exitAnimation||"fade"}`;
  },exitAt);

  setTimeout(()=>{
    try{if(media.pause)media.pause();}catch{}
    outer.remove();
  },duration+250);

  return media;
}
function playCommand(item){
  console.log("[Brynn command]",item);
  playBuiltIn(item);
  playCustomVisual(item);
  playStickerTimeline(item);
  playAudio(item.audioUrl,item.audioVolume,Number(item.durationMs||0),Number(item.audioFadeOutMs??600),item.cutAudioAtDuration!==false,Number(item.audioTrimStartMs||0),Number(item.audioTrimEndMs||0));
}


const commandQueues=new Map();
const commandBusy=new Set();
const activeEmoteSlots=new Set();

function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms));}

function emoteSlots(){
  const slots=[];
  const xs=[12,31,50,69,88];
  const ys=[18,50,82];
  for(const y of ys){for(const x of xs){slots.push({x,y});}}
  return slots;
}

function pickEmoteSlot(){
  const slots=emoteSlots();
  const free=slots.map((slot,index)=>({slot,index})).filter(x=>!activeEmoteSlots.has(x.index));
  const chosen=(free.length?free:slots.map((slot,index)=>({slot,index})))[Math.floor(Math.random()*(free.length||slots.length))];
  activeEmoteSlots.add(chosen.index);
  return chosen;
}

function playScatteredEmote(item){
  if(!item||!item.visualUrl)return;
  const chosen=pickEmoteSlot();
  const patternItem={...item};
  const el=spawnSticker(patternItem,{durationMs:item.durationMs,animation:item.animation,enterAnimation:item.enterAnimation,exitAnimation:item.exitAnimation,size:Math.max(8,Math.min(38,Number(item.size||22))),pattern:'scatter',index:chosen.index,total:15});
  const duration=Math.max(900,Number(item.durationMs||3200));
  setTimeout(()=>activeEmoteSlots.delete(chosen.index),duration+160);
  return el;
}

async function runCommandQueue(commandId){
  if(commandBusy.has(commandId))return;
  commandBusy.add(commandId);

  try{
    const queue=commandQueues.get(commandId)||[];

    while(queue.length){
      const event=queue.shift();
      const user=event.user||{};
      const item=event.item||{};

      const customShown=showRedeemPresentation(event);
      if(item.showCard!==false && !(customShown && event.presentation&&event.presentation.hideDefaultCard)){
        showCard({
          user,
          kicker:`${platform(user)} · CANJE`,
          title:`${esc(user.username||"Usuario")} usó ${itemMark(item)} ${esc(item.name||item.id||"")}`,
          body:`Costo: ${currencyText(event,item.cost||0)} · Saldo: ${currencyText(event,event.balance||0)}`,
          accent:'#FF6A00',
          redeem:true,
          duration:Math.min(6500,Math.max(3000,Number(item.durationMs||5200)))
        });
      }

      playCommand(item);
      await sleep(Math.max(800,Number(item.playbackDurationMs||item.durationMs||3000)+250));
    }
  }finally{
    commandBusy.delete(commandId);
    const queue=commandQueues.get(commandId)||[];
    if(!queue.length)commandQueues.delete(commandId);
    else runCommandQueue(commandId);
  }
}

function enqueueRedeem(event){
  const id=String(event?.item?.id||event?.item?.name||'command').toLowerCase();
  const queue=commandQueues.get(id)||[];
  queue.push(event);
  commandQueues.set(id,queue);
  runCommandQueue(id);
}

function weeklyReplaceTokens(source,event){
  const reward=event.reward||{};
  const user=event.user||{};
  const tokens={
    '{user}':esc(user.username||reward.username||'Usuario'),
    '{platform}':esc(String(user.platform||reward.platform||'').toUpperCase()),
    '{rank}':esc(reward.rank||''),
    '{score}':esc(reward.score||0),
    '{title}':esc(reward.title||''),
    '{badge}':esc(reward.badgeLabel||''),
    '{badgeIcon}':esc(reward.badgeIcon||'✦'),
    '{badgeHtml}':String(reward.badgeHtml||''),
    '{tier}':esc(reward.tier||''),
    '{accent}':esc(reward.accent||'#53E6FF'),
    '{avatar}':esc(user.avatar||reward.avatar||'')
  };
  let output=String(source||'');
  for(const [token,value] of Object.entries(tokens)) output=output.split(token).join(value);
  return output;
}

function showWeeklyEntrance(event){
  const render=event.render||{};
  const reward=event.reward||{};
  const duration=Math.max(800,Math.min(30000,Number(render.durationMs||5200)));
  const host=document.createElement('div');
  host.className='weekly-entrance-host';
  host.style.setProperty('--weekly-accent',reward.accent||'#53E6FF');

  const frame=document.createElement('iframe');
  frame.className='weekly-entrance-frame';
  frame.setAttribute('sandbox','allow-scripts');
  frame.setAttribute('title','Entrada semanal');

  let html=weeklyReplaceTokens(render.html||'',event);
  if(!html){
    html=`<div class="weekly-entry"><div class="weekly-badge">${esc(reward.badgeLabel||'TOP')}</div><h1>${esc(reward.title||'GANADOR SEMANAL')}</h1><h2>${esc(event?.user?.username||'Usuario')}</h2></div>`;
  }
  const css=weeklyReplaceTokens((reward.badgeCss||'')+'\n'+(render.css||''),event);
  const customJs=String(render.js||'');
  const data=JSON.stringify({user:event.user||{},reward});
  const jsLiteral=JSON.stringify(customJs);

  frame.srcdoc=`<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}
    ${css}
  </style></head><body>${html}<script>
    window.WEEKLY_DATA=${data};
    window.WEEKLY_ROOT=document.body;
    try{const code=${jsLiteral};if(code.trim())new Function('WEEKLY_DATA','WEEKLY_ROOT',code)(window.WEEKLY_DATA,window.WEEKLY_ROOT);}catch(e){console.warn('[Brynn weekly JS]',e);}
  <\/script></body></html>`;

  host.appendChild(frame);
  stage.appendChild(host);
  requestAnimationFrame(()=>host.classList.add('show'));
  setTimeout(()=>host.classList.add('out'),Math.max(300,duration-450));
  setTimeout(()=>host.remove(),duration+120);
}

function handleEvent(event){
  if(event.type==="automation_audio"){playAudio(event.audioUrl,event.volume,Number(event.durationMs||0),Number(event.fadeOutMs||600),Number(event.durationMs||0)>0);return;}
  if(event.type==="automation_notice"){showCard({user:event.user||{},kicker:"AUTOMATION",title:esc(event.title||"Automatización"),body:event.message||"",accent:event.accent||"#8CFF3A",duration:Number(event.durationMs||4200)});return;}
  const user=event.user||{};
  if(event.type==="weekly_entrance"){showWeeklyEntrance(event);return;}
  if(event.type==="redeem_preview"){showRedeemPresentation(event);return;}
  if(event.type==="daily_bonus"){
    showCard({
      user,
      kicker:`${platform(user)} · BONO DIARIO`,
      title:`${esc(user.username||"Usuario")} recibió ${currencyText(event,event.amount)}`,
      body:`Saldo actual: ${currencyText(event,event.balance)}`,
      accent:"#FFD34E",
      duration:5200
    });
    return;
  }
  if(event.type==="balance"){const c=currencyInfo(event);showCard({user,kicker:`${platform(user)} · ${String(c.plural||'MONEDA').toUpperCase()}`,title:esc(user.username||"Usuario"),body:`Tienes ${currencyText(event,event.balance||0)}.`,accent:"#8CFF3A"});return;}
  if(event.type==="store"){showCard({user,kicker:`TIENDA · SALDO ${currencyText(event,event.balance||0)}`,title:"Tienda",body:event.message||"Usa un comando de la tienda",html:storeHtml(event.items,event),accent:"#FF6A00",duration:8500});return;}
  if(event.type==="top_wallets"){showCard({user,kicker:"TOP GUMPITAS",title:"Los más ricos del cementerio",html:topHtml(event.top,"balance"),accent:"#FFD34E",duration:7000});return;}
  if(event.type==="weekly_ranking"){showCard({user,kicker:"RANKING SEMANAL",title:"Top de interacción",html:topHtml(event.top,"score"),accent:"#B76CFF",duration:7000});return;}
  if(event.type==="help"){showCard({user,kicker:"COMANDOS",title:"Interacción del chat",body:(event.commands||[]).join(" · "),accent:"#8CFF3A",duration:8500});return;}
  if(event.type==="error"){showCard({user,kicker:"NO SE PUDO",title:esc(user.username||"Usuario"),body:event.message||"Algo salió mal.",accent:"#B3122A"});return;}
  if(event.type==="emote_redeem"){
    const item=event.emote||{};

    const customShown=showRedeemPresentation(event);
    if(item.showCard===true && !(customShown && event.presentation&&event.presentation.hideDefaultCard)){
      showCard({
        user,
        kicker:`${platform(user)} · EMOTE`,
        title:`${esc(user.username||"Usuario")} lanzó ${esc(item.name||item.id||"un emote")}`,
        body:`Costo: ${currencyText(event,item.cost||0)} · Saldo: ${currencyText(event,event.balance||0)}`,
        accent:"#8CFF3A",
        duration:Math.min(5200,Math.max(2500,Number(item.durationMs||3200)))
      });
    }

    playScatteredEmote(item);
    playAudio(
      item.audioUrl,
      item.audioVolume,
      Number(item.durationMs||0)
    );
    return;
  }

  if(event.type==="redeem"){
    enqueueRedeem(event);
    return;
  }
}
async function poll(){if(polling)return;polling=true;try{const response=await fetch(`/api/events?after=${lastEventId}`,{cache:"no-store"});if(!response.ok)throw new Error("HTTP "+response.status);const data=await response.json();for(const event of (Array.isArray(data.events)?data.events:[])){lastEventId=Math.max(lastEventId,Number(event.id||0));handleEvent(event);}}catch(error){console.warn("Eventos:",error);}finally{polling=false;}}
poll();setInterval(poll,420);
