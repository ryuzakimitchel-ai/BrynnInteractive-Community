const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let autos = [], selected = null, dirty = false;
let inventory = {scenes:[],transitions:[],inputs:[],inputDetails:[],sceneItems:{},filters:{}};
let commands = [], emotes = [], runtimeState = {};

const EVENTS = {
  manual:[['test','Prueba manual']],
  twitch:[['follow','Nuevo follow'],['subscription','Suscripción / resub'],['donation','Donación'],['bits','Bits'],['raid','Raid']],
  tiktok:[['follow','Nuevo follow'],['subscription','Suscripción'],['gift','Regalo'],['like','Likes'],['share','Compartió el LIVE'],['join','Entró al LIVE']],
  kick:[['follow','Nuevo follow'],['subscription','Suscripción / renovación'],['gift','Subs regaladas / KICKs'],['reward','Recompensa canjeada']],
  chat:[['message','Nuevo mensaje']],
  brynn:[['redeem','Comando / canje'],['emote_redeem','Emote ejecutado'],['goal_reached','Meta alcanzada'],['weekly_entrance','Entrada semanal'],['daily_bonus','Bono diario']]
};
const FIELD_OPTIONS = [
  ['username','Usuario'],['message','Mensaje del chat'],['giftName','Nombre del regalo'],['quantity','Cantidad'],['giftCoins','Monedas del regalo'],
  ['donationUsd','Donación USD'],['amount','Texto/cantidad mostrada'],['command','Comando'],['event','Evento'],['platform','Plataforma'],['source','Origen técnico'],['__custom__','Otro campo…']
];
const OP_OPTIONS = [
  ['equals','es igual a'],['not_equals','no es igual a'],['contains','contiene'],['not_contains','no contiene'],['gte','es ≥'],['lte','es ≤'],['gt','es >'],['lt','es <'],['exists','existe / tiene valor']
];

async function api(url, method='GET', body){
  const r = await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,cache:'no-store'});
  const j = await r.json().catch(()=>({}));
  if(!r.ok || j.ok===false) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}
function uid(){return 'auto-'+Math.random().toString(36).slice(2,10)}
function deep(x){return JSON.parse(JSON.stringify(x))}
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function markDirty(v=true){dirty=v;const el=$('#saveState');el.textContent=v?'Cambios sin guardar':'Todo guardado';el.className='save-state '+(v?'dirty':'saved')}
function message(t,type=''){const el=$('#message');el.textContent=t||'';el.className='message '+type}
function optionHtml(rows,value=''){return rows.map(([v,l])=>`<option value="${esc(v)}" ${String(v)===String(value)?'selected':''}>${esc(l)}</option>`).join('')}
function plainOptions(list,value=''){return (list||[]).map(x=>`<option value="${esc(x)}" ${String(x)===String(value)?'selected':''}>${esc(x)}</option>`).join('')}
function field(label,html){return `<label class="field-wrap"><span>${esc(label)}</span>${html}</label>`}

function originFor(a){
  const t=a?.trigger||{};
  if(t.type==='manual') return 'manual';
  if(t.type==='chat_message') return 'chat';
  if(t.type==='brynn_event') return 'brynn';
  if(t.type==='platform_event' && ['twitch','tiktok','kick'].includes(t.platform)) return t.platform;
  return 'custom';
}
function triggerText(a){
  const t=a?.trigger||{}, o=originFor(a); const labels={manual:'Manual',twitch:'Twitch',tiktok:'TikTok',kick:'Kick',chat:'Chat',brynn:'Brynn',custom:'Personalizado'};
  let e = (EVENTS[o]||[]).find(x=>x[0]===t.event)?.[1] || t.event || (o==='manual'?'Prueba':'Cualquier evento');
  if(o==='chat' && t.platform && t.platform!=='any') e += ` · ${t.platform}`;
  if(t.command) e += ` · !${t.command}`;
  return `${labels[o]} · ${e}`;
}
function actionLabel(t){return ({
  wait:'Esperar',chance:'Probabilidad',stop:'Finalizar flujo',obs_scene:'OBS · Cambiar escena',obs_transition:'OBS · Transición',obs_source:'OBS · Fuente',obs_filter:'OBS · Filtro',obs_mute:'OBS · Mute',obs_volume:'OBS · Volumen',obs_media:'OBS · Multimedia',obs_media_restart:'OBS · Reiniciar media',obs_stream:'OBS · Stream',obs_record:'OBS · Grabación',obs_replay:'OBS · Replay Buffer',command:'Brynn · Comando',emote:'Brynn · Emote',economy_adjust:'Brynn · Puntos',overlay_message:'Overlay · Mensaje',audio:'Overlay · Audio'
})[t]||t}
function actionDescription(t){return ({
  wait:'Pausa antes de seguir.',chance:'Continúa solo con cierta probabilidad.',stop:'Termina aquí la automatización.',obs_scene:'Cambia la escena de programa.',obs_transition:'Selecciona transición y duración.',obs_source:'Muestra u oculta una fuente.',obs_filter:'Activa o desactiva un filtro.',obs_mute:'Controla el mute de una entrada.',obs_volume:'Ajusta el volumen de una entrada.',obs_media:'Play, pausa, stop o reinicio.',obs_stream:'Inicia o detiene el directo.',obs_record:'Inicia o detiene grabación.',obs_replay:'Controla el Replay Buffer.',command:'Ejecuta uno de tus efectos/comandos.',emote:'Lanza un emote configurado.',economy_adjust:'Suma o resta puntos al usuario que disparó el evento.',overlay_message:'Muestra un aviso en el overlay.',audio:'Reproduce un archivo de audio.'
})[t]||''}

function renderHistory(runtime=runtimeState){
  runtimeState=runtime||{};const rows=runtimeState.history||[];const h=$('#history');
  h.innerHTML=rows.length?'<h4>Actividad reciente</h4>'+rows.slice(0,10).map(x=>`<div class="history-row ${x.ok?'ok':'bad'}"><b>${esc(x.name)}</b> · ${x.executed||0} acción(es) · ${x.durationMs||0} ms${x.errors?.length?'<br>'+esc(x.errors[0]):''}</div>`).join(''):'';
}
function renderList(){
  const box=$('#automationList'), q=($('#flowSearch').value||'').trim().toLowerCase(); box.innerHTML='';
  const rows=autos.filter(a=>!q || `${a.name} ${triggerText(a)}`.toLowerCase().includes(q));
  for(const a of rows){const d=document.createElement('div');d.className='auto-card'+(selected&&selected.id===a.id?' active':'');d.innerHTML=`<b><span class="dot ${a.enabled?'on':''}"></span>${esc(a.name)}</b><small>${esc(triggerText(a))}<br>${a.actions?.length||0} acciones · ${a.conditions?.length||0} condiciones</small>`;d.onclick=()=>select(a.id);box.appendChild(d)}
  if(!rows.length)box.innerHTML=`<p class="muted">${q?'No hay coincidencias.':'Aún no hay automatizaciones.'}</p>`;
  $('#flowCount').textContent=`${autos.length} automatización${autos.length===1?'':'es'}`;
  renderHistory();
}
function select(aid){pullEditor();selected=autos.find(x=>x.id===aid)||null;renderList();renderEditor()}

function setSelectEvents(origin,current){
  const sel=$('#triggerEvent');const rows=EVENTS[origin]||[];sel.innerHTML=optionHtml(rows,current);
  const known=rows.some(x=>x[0]===current);
  if(current && !known) sel.insertAdjacentHTML('beforeend',`<option value="__custom__" selected>Personalizado: ${esc(current)}</option>`);
  else sel.insertAdjacentHTML('beforeend','<option value="__custom__">Otro evento…</option>');
  $('#triggerEventCustomWrap').hidden = sel.value!=='__custom__';
  if(sel.value==='__custom__') $('#triggerEventCustom').value=current||'';
}
function updateTriggerControls(preserve=true){
  if(!selected)return;const origin=$('#triggerOrigin').value;const current=preserve?(selected.trigger?.event||$('#triggerEventCustom').value||''):'';
  $('#customTrigger').hidden=origin!=='custom';
  $('#triggerEventWrap').hidden=origin==='custom';
  $('#triggerPlatformWrap').hidden=!['chat'].includes(origin);
  setSelectEvents(origin,current);
  const ev = $('#triggerEvent').value==='__custom__'?$('#triggerEventCustom').value:$('#triggerEvent').value;
  $('#triggerCommandWrap').hidden=!(origin==='brynn' && ev==='redeem');
  const help={manual:'Solo se ejecuta al pulsar “Probar”. Ideal para preparar acciones antes de conectarlas a un evento real.',twitch:'Se activará cuando Brynn reciba este evento desde Twitch.',tiktok:'Se activará cuando TikFinity/Brynn reciba este evento de TikTok.',kick:'Se activará al recibir un webhook firmado de Kick (requiere autorización y túnel HTTPS).',chat:'Escucha mensajes del chat. Usa una condición “Mensaje contiene…” para reaccionar a palabras o frases.',brynn:'Escucha cosas que ya ocurren dentro de Brynn: canjes, emotes, metas y recompensas.',custom:'Configura directamente el tipo interno de disparador.'};
  $('#triggerHelp').textContent=help[origin]||'';renderConditionSuggestions();updateSummary();
}
function renderCommandSelect(){
  $('#triggerCommand').innerHTML='<option value="">Cualquier comando</option>'+commands.map(x=>`<option value="${esc(x.id)}">!${esc(x.id)} · ${esc(x.name||x.id)}</option>`).join('');
}
function renderEditor(){
  if(!selected){$('#editor').hidden=true;$('#emptyEditor').hidden=false;return}
  $('#editor').hidden=false;$('#emptyEditor').hidden=true;
  $('#name').value=selected.name||'';$('#enabled').checked=selected.enabled!==false;$('#cooldown').value=selected.cooldownSeconds||0;$('#stopOnError').checked=selected.stopOnError!==false;
  const o=originFor(selected);$('#triggerOrigin').value=o;
  $('#triggerPlatform').value=selected.trigger?.platform||'any';
  $('#customType').value=selected.trigger?.type||'platform_event';$('#customPlatform').value=selected.trigger?.platform||'any';$('#customEvent').value=selected.trigger?.event||'';
  renderCommandSelect();$('#triggerCommand').value=selected.trigger?.command||'';
  updateTriggerControls(true); renderConditions(); renderActions(); updateSummary();
}
function pullEditor(){
  if(!selected||$('#editor').hidden)return;
  selected.name=$('#name').value.trim()||'Automatización';selected.enabled=$('#enabled').checked;selected.cooldownSeconds=Math.max(0,Number($('#cooldown').value||0));selected.stopOnError=$('#stopOnError').checked;
  const o=$('#triggerOrigin').value; let event=$('#triggerEvent').value==='__custom__'?$('#triggerEventCustom').value.trim():$('#triggerEvent').value;
  if(o==='manual')selected.trigger={type:'manual',platform:'any',event:event||'test'};
  else if(o==='twitch'||o==='tiktok'||o==='kick')selected.trigger={type:'platform_event',platform:o,event};
  else if(o==='chat')selected.trigger={type:'chat_message',platform:$('#triggerPlatform').value||'any',event:event||'message'};
  else if(o==='brynn'){selected.trigger={type:'brynn_event',platform:'any',event};if(event==='redeem'&&$('#triggerCommand').value)selected.trigger.command=$('#triggerCommand').value}
  else selected.trigger={type:$('#customType').value.trim()||'platform_event',platform:$('#customPlatform').value.trim()||'any',event:$('#customEvent').value.trim()};
  updateSummary();renderList();
}
function updateSummary(){
  if(!selected)return;const cond=selected.conditions?.length||0, acts=selected.actions?.filter(a=>!a._disabled).length||0;
  $('#flowSummary').innerHTML=`<strong>Resumen:</strong> Cuando <b>${esc(triggerText(selected))}</b>${cond?`, y se cumplan <b>${cond} condición${cond===1?'':'es'}</b>`:''}, ejecutará <b>${acts} acción${acts===1?'':'es'}</b>${selected.cooldownSeconds?` · cooldown ${selected.cooldownSeconds}s`:''}.`;
}

function renderConditionSuggestions(){
  if(!selected)return;const o=$('#triggerOrigin').value, ev=$('#triggerEvent').value==='__custom__'?$('#triggerEventCustom').value:$('#triggerEvent').value;let rows=[];
  if(o==='tiktok'&&ev==='gift') rows=[['giftName','equals','Rose','🎁 Regalo específico'],['giftCoins','gte','10','🪙 Mínimo de monedas'],['quantity','gte','5','🔢 Cantidad mínima'],['username','equals','','👤 Usuario específico']];
  else if(o==='chat') rows=[['message','contains','hola','💬 Mensaje contiene…'],['username','equals','','👤 Usuario específico'],['platform','equals','twitch','💜 Solo Twitch']];
  else if(o==='kick'&&ev==='gift') rows=[['giftName','contains','KICK','🎁 Tipo de regalo'],['giftCoins','gte','100','🟢 Mínimo de KICKs'],['username','equals','','👤 Usuario específico']];
  else if(o==='twitch'&&ev==='raid') rows=[['quantity','gte','10','👥 Mínimo de viewers'],['username','equals','','👤 Raider específico']];
  else rows=[['username','equals','','👤 Usuario específico']];
  $('#conditionSuggestions').innerHTML=rows.map((x,i)=>`<button class="suggestion" data-suggest="${i}">${esc(x[3])}</button>`).join('');
  $$('#conditionSuggestions [data-suggest]').forEach((b,i)=>b.onclick=()=>{selected.conditions=selected.conditions||[];selected.conditions.push({field:rows[i][0],op:rows[i][1],value:rows[i][2]});markDirty();renderConditions();updateSummary()});
}
function renderConditions(){
  const box=$('#conditions');box.innerHTML='';(selected.conditions||[]).forEach((c,i)=>{
    const known=FIELD_OPTIONS.some(x=>x[0]===c.field);const d=document.createElement('div');d.className='condition-row';
    d.innerHTML=`<div class="condition-field"><select data-field-select>${optionHtml(FIELD_OPTIONS,known?c.field:'__custom__')}</select><input data-field-custom placeholder="raw.campo" value="${esc(known?'':c.field||'')}" ${known?'hidden':''}></div><select data-k="op">${optionHtml(OP_OPTIONS,c.op||'equals')}</select><input data-k="value" placeholder="Valor" value="${esc(c.value??'')}" ${c.op==='exists'?'disabled':''}><button class="icon-btn del" title="Eliminar condición">×</button>`;
    const fs=d.querySelector('[data-field-select]'),fc=d.querySelector('[data-field-custom]'),op=d.querySelector('[data-k=op]'),val=d.querySelector('[data-k=value]');
    const syncField=()=>{fc.hidden=fs.value!=='__custom__';c.field=fs.value==='__custom__'?fc.value:fs.value;markDirty();updateSummary()};fs.onchange=syncField;fc.oninput=syncField;
    op.onchange=()=>{c.op=op.value;val.disabled=op.value==='exists';markDirty()};val.oninput=()=>{c.value=val.value;markDirty()};
    d.querySelector('.del').onclick=()=>{selected.conditions.splice(i,1);markDirty();renderConditions();updateSummary()};box.appendChild(d)
  });
  if(!selected.conditions?.length)box.innerHTML='<div class="empty-actions"><b>Sin condiciones</b>Este flujo se ejecutará para todos los eventos que coincidan con el paso 1.</div>';
}

function allSources(){return [...new Set(Object.values(inventory.sceneItems||{}).flat().map(x=>x.name).filter(Boolean))].sort()}
function filterSources(){return Object.keys(inventory.filters||{}).sort()}
function audioInputs(){const rows=(inventory.inputDetails||[]).filter(x=>x.audio).map(x=>x.name);return rows.length?rows:inventory.inputs||[]}
function actionFields(a){const t=a.type;
  if(t==='wait')return field('Tiempo',`<input data-k="ms" type="number" min="0" max="300000" value="${Number(a.ms??1000)}">`)+field('Unidad','<div class="static-field">milisegundos</div>');
  if(t==='chance')return field('Probabilidad %',`<input data-k="percent" type="number" min="0" max="100" step="1" value="${Number(a.percent??50)}">`)+field('Qué ocurre','<div class="static-field">Si falla, termina el flujo</div>');
  if(t==='stop')return '<div class="static-field">No requiere configuración.</div>';
  if(t==='obs_scene')return field('Escena',`<select data-k="scene"><option value="">Selecciona…</option>${plainOptions(inventory.scenes,a.scene)}</select>`);
  if(t==='obs_transition')return field('Transición',`<select data-k="transition"><option value="">Selecciona…</option>${plainOptions(inventory.transitions,a.transition)}</select>`)+field('Duración ms',`<input data-k="durationMs" type="number" min="50" max="20000" value="${a.durationMs??300}">`);
  if(t==='obs_source')return field('Escena',`<select data-k="scene"><option value="">Escena actual</option>${plainOptions(inventory.scenes,a.scene)}</select>`)+field('Fuente',`<select data-k="source"><option value="">Selecciona…</option>${plainOptions(allSources(),a.source)}</select>`)+field('Acción',`<select data-k="enabled"><option value="true" ${a.enabled!==false?'selected':''}>Mostrar</option><option value="false" ${a.enabled===false?'selected':''}>Ocultar</option></select>`);
  if(t==='obs_filter')return field('Fuente',`<select data-k="source"><option value="">Selecciona…</option>${plainOptions(filterSources(),a.source)}</select>`)+field('Filtro',`<select data-k="filter"><option value="">Selecciona…</option>${plainOptions([...new Set(Object.values(inventory.filters||{}).flat().map(x=>x.name))],a.filter)}</select>`)+field('Acción',`<select data-k="enabled"><option value="true" ${a.enabled!==false?'selected':''}>Activar</option><option value="false" ${a.enabled===false?'selected':''}>Desactivar</option></select>`);
  if(t==='obs_mute')return field('Entrada',`<select data-k="input"><option value="">Selecciona…</option>${plainOptions(audioInputs(),a.input)}</select>`)+field('Acción',`<select data-k="muted"><option value="true" ${a.muted!==false?'selected':''}>Mutear</option><option value="false" ${a.muted===false?'selected':''}>Desmutear</option></select>`);
  if(t==='obs_volume')return field('Entrada',`<select data-k="input"><option value="">Selecciona…</option>${plainOptions(audioInputs(),a.input)}</select>`)+field('Volumen %',`<input data-special="volumePercent" type="number" min="0" max="200" value="${Math.round(Number(a.volume??1)*100)}">`);
  if(t==='obs_media'||t==='obs_media_restart')return field('Fuente multimedia',`<select data-k="input"><option value="">Selecciona…</option>${plainOptions(inventory.inputs,a.input)}</select>`)+(t==='obs_media'?field('Acción',`<select data-k="action">${optionHtml([['restart','Reiniciar'],['play','Reproducir'],['pause','Pausar'],['stop','Detener'],['next','Siguiente'],['previous','Anterior']],a.action||'restart')}</select>`):'');
  if(t==='obs_stream')return field('Streaming',`<select data-k="active"><option value="true" ${a.active!==false?'selected':''}>Iniciar stream</option><option value="false" ${a.active===false?'selected':''}>Detener stream</option></select>`);
  if(t==='obs_record')return field('Grabación',`<select data-k="active"><option value="true" ${a.active!==false?'selected':''}>Iniciar grabación</option><option value="false" ${a.active===false?'selected':''}>Detener grabación</option></select>`);
  if(t==='obs_replay')return field('Replay Buffer',`<select data-k="action">${optionHtml([['start','Iniciar buffer'],['save','Guardar replay'],['stop','Detener buffer']],a.action||'save')}</select>`);
  if(t==='command')return field('Comando / efecto',`<select data-k="id"><option value="">Selecciona…</option>${commands.map(x=>`<option value="${esc(x.id)}" ${x.id===a.id?'selected':''}>!${esc(x.id)} · ${esc(x.name||x.id)}</option>`).join('')}</select>`);
  if(t==='emote')return field('Emote',`<select data-k="id"><option value="">Selecciona…</option>${emotes.map(x=>`<option value="${esc(x.id)}" ${x.id===a.id?'selected':''}>${(x.accessMode||'general')==='exclusive'?'★ Secuencia · ':''}${esc(x.name||x.id)}</option>`).join('')}</select>`);
  if(t==='economy_adjust')return field('Puntos',`<input data-k="delta" type="number" min="-100000" max="100000" value="${Number(a.delta??10)}">`)+field('Motivo',`<input data-k="reason" value="${esc(a.reason||'automation')}" placeholder="bonus_automatizacion">`);
  if(t==='overlay_message')return field('Título',`<input data-k="title" value="${esc(a.title||'Automatización')}">`)+field('Mensaje',`<input data-k="message" value="${esc(a.message||'')}">`)+field('Duración ms',`<input data-k="durationMs" type="number" min="800" max="30000" value="${a.durationMs||4200}">`);
  if(t==='audio')return field('Ruta / URL',`<input data-k="url" value="${esc(a.url||'')}" placeholder="/user_media/audio.mp3">`)+field('Volumen %',`<input data-special="audioVolumePercent" type="number" min="0" max="100" value="${Math.round(Number(a.volume??.8)*100)}">`)+field('Corte ms',`<input data-k="durationMs" type="number" min="0" value="${a.durationMs||0}" title="0 = completo">`)+field('Fade out ms',`<input data-k="fadeOutMs" type="number" min="0" max="10000" value="${a.fadeOutMs??600}">`);
  return '<div class="static-field">Esta acción no tiene editor todavía.</div>';
}
function parseVal(k,v){if(['enabled','muted','active'].includes(k))return v==='true';if(['ms','durationMs','fadeOutMs','percent','delta'].includes(k))return Number(v||0);return v}
function renderActions(){
  const box=$('#actions');box.innerHTML='';(selected.actions||[]).forEach((a,i)=>{const d=document.createElement('div');d.className='action-row'+(a._disabled?' disabled':'');d.innerHTML=`<div class="action-index">${i+1}</div><div class="action-meta"><strong>${esc(actionLabel(a.type))}</strong><small>${esc(actionDescription(a.type))}</small><label class="mini-toggle"><input data-toggle type="checkbox" ${a._disabled?'':'checked'}> Activa</label></div><div class="action-fields">${actionFields(a)}</div><div class="action-tools"><button data-up class="icon-btn" title="Subir">↑</button><button data-down class="icon-btn" title="Bajar">↓</button><button data-copy class="icon-btn" title="Duplicar">⧉</button><button data-del class="icon-btn del" title="Eliminar">×</button></div>`;
    d.querySelectorAll('[data-k]').forEach(el=>{const evt=el.tagName==='SELECT'?'change':'input';el.addEventListener(evt,()=>{a[el.dataset.k]=parseVal(el.dataset.k,el.value);markDirty()})});
    d.querySelectorAll('[data-special]').forEach(el=>el.addEventListener('input',()=>{if(el.dataset.special==='volumePercent')a.volume=Math.max(0,Math.min(200,Number(el.value||0)))/100;if(el.dataset.special==='audioVolumePercent')a.volume=Math.max(0,Math.min(100,Number(el.value||0)))/100;markDirty()}));
    d.querySelector('[data-toggle]').onchange=e=>{a._disabled=!e.target.checked;markDirty();renderActions();updateSummary()};
    d.querySelector('[data-del]').onclick=()=>{selected.actions.splice(i,1);markDirty();renderActions();updateSummary()};
    d.querySelector('[data-copy]').onclick=()=>{selected.actions.splice(i+1,0,deep(a));markDirty();renderActions();updateSummary()};
    d.querySelector('[data-up]').onclick=()=>{if(i){[selected.actions[i-1],selected.actions[i]]=[selected.actions[i],selected.actions[i-1]];markDirty();renderActions()}};
    d.querySelector('[data-down]').onclick=()=>{if(i<selected.actions.length-1){[selected.actions[i+1],selected.actions[i]]=[selected.actions[i],selected.actions[i+1]];markDirty();renderActions()}};box.appendChild(d)
  });
  if(!selected.actions?.length)box.innerHTML='<div class="empty-actions"><b>Aún no hay acciones</b>Usa “+ Añadir acción…” para indicar qué debe hacer Brynn.</div>';
}

async function save(silent=false){
  pullEditor();try{const currentId=selected?.id;const d=await api('/api/automations/save','POST',{automations:autos});autos=d.automations||autos;selected=currentId?autos.find(x=>x.id===currentId)||null:null;markDirty(false);renderList();renderEditor();if(!silent)message('Automatizaciones guardadas.','ok');return true}catch(e){message(e.message,'error');return false}
}
async function deleteSelected(){
  if(!selected)return;const doomed=selected;if(!confirm(`¿Eliminar “${doomed.name}”?\n\nEsta acción no se puede deshacer.`))return;
  try{const d=await api('/api/automations/delete','POST',{id:doomed.id});autos=d.automations||autos.filter(x=>x.id!==doomed.id);selected=autos[0]||null;markDirty(false);renderList();renderEditor();message(`“${doomed.name}” fue eliminada permanentemente.`,'ok')}catch(e){message('No se pudo eliminar: '+e.message,'error')}
}
async function load(){
  try{const d=await api('/api/automations');autos=d.automations||[];runtimeState=d.runtime||{};renderList();
    const [o,c,e]=await Promise.allSettled([api('/api/obs/inventory'),api('/api/commands'),api('/api/emotes')]);
    if(o.status==='fulfilled')inventory=o.value;if(c.status==='fulfilled')commands=c.value.commands||[];if(e.status==='fulfilled')emotes=e.value.emotes||[];renderCommandSelect();if(selected)renderEditor();markDirty(false)
  }catch(e){message(e.message,'error')}
}
function blankAutomation(name='Nueva automatización'){return {id:uid(),name,enabled:true,trigger:{type:'manual',platform:'any',event:'test'},conditions:[],actions:[],cooldownSeconds:0,stopOnError:true}}
function createAutomation(a){pullEditor();autos.unshift(a);selected=a;markDirty();renderList();renderEditor();window.scrollTo({top:0,behavior:'smooth'})}
function fromTemplate(kind){
  const firstScene=inventory.scenes?.[0]||'';let a=blankAutomation();
  if(kind==='manual_scene'){a.name='Cambio de escena';a.actions=[{type:'obs_scene',scene:firstScene}]}
  if(kind==='tiktok_gift'){a.name='Regalo TikTok';a.trigger={type:'platform_event',platform:'tiktok',event:'gift'};a.conditions=[{field:'giftName',op:'equals',value:'Rose'}];a.actions=[{type:'overlay_message',title:'¡Gracias!',message:'Regalo recibido 💜',durationMs:4200}]}
  if(kind==='twitch_follow'){a.name='Nuevo follow Twitch';a.trigger={type:'platform_event',platform:'twitch',event:'follow'};a.actions=[{type:'overlay_message',title:'¡Nuevo follow!',message:'Gracias por seguir el stream 💜',durationMs:4200}]}
  if(kind==='kick_follow'){a.name='Nuevo follow Kick';a.trigger={type:'platform_event',platform:'kick',event:'follow'};a.actions=[{type:'overlay_message',title:'¡Follow en Kick!',message:'Gracias por seguir el canal 💚',durationMs:4200}]}
  if(kind==='chat_keyword'){a.name='Palabra en chat';a.trigger={type:'chat_message',platform:'any',event:'message'};a.conditions=[{field:'message',op:'contains',value:'hola brynn'}];a.actions=[{type:'overlay_message',title:'Chat detectado',message:'¡Te escuché!',durationMs:3000}]}
  if(kind==='raid_scene'){a.name='Raid → escena especial';a.trigger={type:'platform_event',platform:'twitch',event:'raid'};a.actions=[{type:'obs_scene',scene:firstScene},{type:'overlay_message',title:'¡RAID!',message:'¡Bienvenidos!',durationMs:6000}]}
  createAutomation(a)
}

$('#newBtn').onclick=$('#newSmall').onclick=()=>createAutomation(blankAutomation());
$('#saveAll').onclick=$('#saveOne').onclick=()=>save();
$('#deleteBtn').onclick=deleteSelected;
$('#duplicateBtn').onclick=()=>{if(!selected)return;const c=deep(selected);c.id=uid();c.name=(c.name||'Automatización')+' · copia';autos.unshift(c);selected=c;markDirty();renderList();renderEditor();message('Copia creada. Guarda los cambios cuando termines.','ok')};
$('#addCondition').onclick=()=>{if(!selected)return;selected.conditions=selected.conditions||[];selected.conditions.push({field:'username',op:'equals',value:''});markDirty();renderConditions();updateSummary()};
$('#actionPicker').onchange=e=>{if(!selected||!e.target.value)return;let a={type:e.target.value};if(a.type==='wait')a.ms=1000;if(a.type==='chance')a.percent=50;if(a.type==='obs_transition')a.durationMs=300;if(a.type==='obs_volume')a.volume=1;if(a.type==='audio'){a.volume=.8;a.fadeOutMs=600}if(a.type==='economy_adjust')a.delta=10;selected.actions=selected.actions||[];selected.actions.push(a);e.target.value='';markDirty();renderActions();updateSummary()};
$('#flowSearch').oninput=renderList;
$$('.template-chip').forEach(b=>b.onclick=()=>fromTemplate(b.dataset.template));

$('#triggerOrigin').onchange=()=>{if(!selected)return;const o=$('#triggerOrigin').value;if(o==='chat')selected.trigger={type:'chat_message',platform:'any',event:'message'};else if(o==='brynn')selected.trigger={type:'brynn_event',platform:'any',event:'redeem'};else if(o==='twitch'||o==='tiktok'||o==='kick')selected.trigger={type:'platform_event',platform:o,event:(EVENTS[o]?.[0]?.[0]||'')};else if(o==='manual')selected.trigger={type:'manual',platform:'any',event:'test'};updateTriggerControls(true);pullEditor();markDirty()};
$('#triggerEvent').onchange=()=>{if(!selected)return;const custom=$('#triggerEvent').value==='__custom__';$('#triggerEventCustomWrap').hidden=!custom;if(custom){$('#triggerEventCustom').value='';selected.trigger.event='';$('#triggerCommandWrap').hidden=true;renderConditionSuggestions();updateSummary();markDirty();return}pullEditor();updateTriggerControls(true);markDirty()};
$('#triggerEventCustom').oninput=()=>{pullEditor();const o=$('#triggerOrigin').value;$('#triggerCommandWrap').hidden=!(o==='brynn'&&$('#triggerEventCustom').value.trim()==='redeem');renderConditionSuggestions();markDirty()};
$('#triggerPlatform').onchange=()=>{pullEditor();markDirty()};
$('#triggerCommand').onchange=()=>{pullEditor();markDirty()};
['customType','customPlatform','customEvent'].forEach(id=>$('#'+id).addEventListener('input',()=>{pullEditor();markDirty()}));
['name','cooldown'].forEach(id=>$('#'+id).addEventListener('input',()=>{pullEditor();markDirty()}));
['enabled','stopOnError'].forEach(id=>$('#'+id).addEventListener('change',()=>{pullEditor();markDirty()}));

$('#testBtn').onclick=async()=>{
  pullEditor();if(!(await save(true))||!selected)return;
  const platform=selected.trigger?.platform==='any'?'twitch':selected.trigger?.platform||'twitch';
  const sample={source:'manual',platform,event:selected.trigger?.event||'test',command:selected.trigger?.command||'',username:$('#testUsername').value.trim()||'DemoViewer',message:$('#testMessage').value,giftName:$('#testGiftName').value,quantity:Number($('#testQuantity').value||1),giftCoins:Number($('#testGiftCoins').value||0),donationUsd:Number($('#testDonation').value||0)};
  sample.user={key:`${platform}:${sample.username.toLowerCase()}`,username:sample.username,platform,avatar:''};
  try{const r=await api('/api/automations/test','POST',{id:selected.id,event:sample});message('Prueba iniciada: '+(r.started||[]).join(', '),'ok');setTimeout(refreshRuntime,700)}catch(e){message('La prueba no inició: '+e.message+'. Revisa que los datos de prueba cumplan tus condiciones.','error')}
};
async function refreshRuntime(){try{const d=await api('/api/automations');renderHistory(d.runtime||{})}catch{}}
setInterval(refreshRuntime,4000);

load();
