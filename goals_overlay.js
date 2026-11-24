const params=new URLSearchParams(location.search);
const requestedId=params.get('id')||'';
const debug=params.get('debug')==='1';
let activeId=requestedId,lastEvent=0,lastSig='';
const host=document.getElementById('goalHost'),cele=document.getElementById('celeHost');
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function tokens(g,html){const d={title:g.title,current:g.current,target:g.target,remaining:g.remaining,percent:g.percent,platform:g.platform,type:g.type,lastUser:g.lastUser||'',lastAmount:g.lastAmount||0,syncStatus:g.syncStatus||'',syncSource:g.syncSource||''};for(const[k,v]of Object.entries(d))html=html.split('{'+k+'}').join(esc(v));return {html,d}}
function diagnostic(msg){if(!debug)return;host.innerHTML=`<div style="font:700 14px Segoe UI,sans-serif;color:#F2EAD8;background:#120d16ee;border:1px solid #ff6a00;border-radius:12px;padding:12px 14px;max-width:92vw">Brynn Goals · ${esc(msg)}</div>`}
function resolveGoal(goals){
  goals=Array.isArray(goals)?goals:[];
  let g=activeId?goals.find(x=>x.id===activeId):null;
  if(g)return g;
  const enabled=goals.filter(x=>x.enabled!==false);
  // Autocorrección: con una sola meta activa no exigimos ?id=. Evita overlays en blanco por una URL incompleta/antigua.
  if(enabled.length===1){activeId=enabled[0].id;return enabled[0]}
  if(goals.length===1){activeId=goals[0].id;return goals[0]}
  return null;
}
function render(g){
  if(!g){lastSig='';host.innerHTML='';return}
  const sig=JSON.stringify([g.id,g.current,g.target,g.updatedAt,g.stateUpdatedAt,g.html,g.css,g.js,g.accent]);
  if(sig===lastSig)return;lastSig=sig;
  const t=tokens(g,String(g.html||''));
  host.innerHTML=`<style>:root{--goal-accent:${g.accent||'#53E6FF'}}${g.css||''}</style><div id="goalRoot">${t.html}</div>`;
  const root=document.getElementById('goalRoot');
  try{new Function('GOAL_DATA','GOAL_ROOT',String(g.js||''))(t.d,root)}catch(e){console.warn('Goal JS:',e);diagnostic('Error en JavaScript personalizado: '+e.message)}
}
async function load(){
  try{
    const r=await fetch('/api/goals',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);
    const d=await r.json();const g=resolveGoal(d.goals||[]);
    if(g){render(g);document.body.dataset.goalId=g.id;document.body.dataset.goalStatus='ready'}
    else{render(null);document.body.dataset.goalStatus='missing';diagnostic(requestedId?`No encuentro la meta "${requestedId}". Vuelve a copiar la URL desde Metas.`:'Falta el id de la meta. Vuelve a copiar la URL desde Metas.')}
  }catch(e){document.body.dataset.goalStatus='error';diagnostic('No puedo comunicar con Brynn: '+e.message)}
}
function showCelebration(ev){const g=ev.goal;if(!g)return;if(activeId && g.id!==activeId)return;const r=ev.render||{},t=tokens(g,String(r.html||g.celebrationHtml||''));cele.innerHTML=`<style>:root{--goal-accent:${g.accent||'#53E6FF'}}${r.css||g.celebrationCss||''}</style><div id="goalCelebrateRoot">${t.html}</div>`;cele.classList.add('show');const root=document.getElementById('goalCelebrateRoot');try{new Function('GOAL_DATA','GOAL_ROOT',String(r.js||g.celebrationJs||''))(t.d,root)}catch(e){console.warn(e)}setTimeout(()=>{cele.classList.remove('show');cele.innerHTML=''},Number(r.durationMs||g.celebrationDurationMs||6500))}
async function poll(){try{const d=await(await fetch('/api/events?after='+lastEvent,{cache:'no-store'})).json();for(const e of d.events||[]){lastEvent=Math.max(lastEvent,+e.id||0);if(e.type==='goal_reached')showCelebration(e)}}catch(e){}}
async function initEvents(){try{const d=await(await fetch('/api/events?after=0',{cache:'no-store'})).json();lastEvent=Number(d.latestId||0)}catch(e){}setInterval(poll,350)}
load();setInterval(load,1000);initEvents();
