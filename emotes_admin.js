const $ = id => document.getElementById(id);
const TIER_ORDER = ['top1','top2','top3','top10'];
const TIER_LABELS = {top1:'Top 1',top2:'Top 2',top3:'Top 3',top10:'Top 4–10'};
let emotes = [], current = null, urls = {visualUrl:'',visualType:'image',audioUrl:''};
let currency = {symbol:'💀',plural:'Gumpitas'}, filterMode = 'all', bulkItems = [];
let weeklyData = {config:null, active:null}, owners = {};

function esc(v){return String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function status(msg,error=false){$('status').textContent=msg;$('status').className='status'+(error?' error':'')}
function outputs(){$('sizeOut').textContent=$('size').value+'%';$('volumeOut').textContent=Math.round(Number($('volume').value)*100)+'%'}
function slugFromName(name){const base=String(name||'').replace(/\.[^.]+$/,'');return base.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9_-]+/g,'-').replace(/^-+|-+$/g,'').slice(0,40)||'emote'}
function visibleFromName(name){return String(name||'').replace(/\.[^.]+$/,'').trim()||'Emote'}
function uniqueId(base,used){let id=base,n=2;while(used.has(id)){id=`${base.slice(0,Math.max(1,37-String(n).length))}-${n++}`}used.add(id);return id}
function fmtDate(value){if(!value)return 'sin vigencia activa';try{return new Intl.DateTimeFormat('es-MX',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value))}catch{return String(value)}}
function preview(){const box=$('preview');box.innerHTML='';if(!urls.visualUrl){box.textContent='Sube un emote.';return}const img=document.createElement('img');img.src=urls.visualUrl;img.alt='';box.appendChild(img)}
function files(){$('visualCurrent').textContent=urls.visualUrl||'Sin archivo';$('audioCurrent').textContent=urls.audioUrl||'Sin archivo';preview()}

function weeklyTiersFor(id){
  const cfg=weeklyData.config;if(!cfg||!id)return [];
  return TIER_ORDER.filter(t=>(cfg.tiers?.[t]?.emoteIds||[]).map(String).map(x=>x.toLowerCase()).includes(String(id).toLowerCase()));
}
function isReserved(id){return (weeklyData.config?.reservedEmoteIds||[]).map(String).map(x=>x.toLowerCase()).includes(String(id||'').toLowerCase())}
function isWeekly(id){return weeklyTiersFor(id).length>0||isReserved(id)}
function winnerCanUse(winner,tiers){const eligible=winner?.eligibleTiers||[];return tiers.some(t=>eligible.includes(t))}
function renderWeeklyAccessPreview(){
  const box=$('weeklyAccessPreview');if(!box)return;const id=current?.id||$('id').value.trim().toLowerCase();const tiers=weeklyTiersFor(id),reserved=isReserved(id),active=weeklyData.active||{};
  const badge=$('scopeBadge');const help=$('accessHelp');
  badge.className='scope-badge '+(isWeekly(id)?'exclusive':'general');badge.textContent=isWeekly(id)?'RECOMPENSA':'GENERAL';
  if(!isWeekly(id)){help.textContent='Este emote es general mientras no esté asignado a un rango semanal.';box.textContent='General · disponible para todos los viewers.';return}
  if(reserved&&!tiers.length){help.textContent='Recurso reservado migrado. Asígnalo a un rango o hazlo general desde Recompensas.';box.innerHTML='<span class="warn">Reservado sin rango:</span> solo el propietario puede probarlo.';return}
  const viewers=(active.winners||[]).filter(w=>winnerCanUse(w,tiers)&&!w.ownerOverride);let html=`<span class="ok">✓ Recompensa semanal:</span> ${tiers.map(t=>TIER_LABELS[t]).join(', ')}.`;if(active.expiresAt)html+=` Vence ${fmtDate(active.expiresAt)}.`;if(viewers.length)html+='<br>Acceso actual: '+viewers.map(w=>`<span class="user-chip">${esc(w.username)} · ${esc(w.platform||'')}</span>`).join('');box.innerHTML=html;help.textContent='La asignación se administra desde Recompensas semanales.';
}
function updateAccessHelp(){renderWeeklyAccessPreview()}
function filteredEmotes(){const q=$('search').value.trim().toLowerCase();return emotes.filter(e=>(filterMode==='all'||(filterMode==='exclusive'?isWeekly(e.id):!isWeekly(e.id)))&&(!q||`${e.id} ${e.name} ${e.description||''}`.toLowerCase().includes(q)))}
function render(){
  const rows=filteredEmotes();$('countBadge').textContent=String(rows.length);
  $('list').innerHTML=rows.length?rows.map(e=>{
    const ex=isWeekly(e.id);
    const tiers=weeklyTiersFor(e.id);
    return `<button class="item ${current&&current.id===e.id?'active':''}" data-id="${esc(e.id)}"><img class="thumb" src="${esc(e.visualUrl)}"><span><b>!emote ${esc(e.id)}</b><small>${esc(e.name)}</small></span><span class="meta-stack"><span class="mini-scope ${ex?'exclusive':''}">${ex?(tiers.length?'RECOMPENSA':'RESERVADO'):'GENERAL'}</span><span class="price">${e.cost} ${esc(currency.symbol||'')}</span></span></button>`
  }).join(''):'<div class="empty-list">No hay emotes en este filtro.</div>';
  document.querySelectorAll('.item').forEach(b=>b.onclick=()=>load(b.dataset.id));
}
function reset(){
  current=null;urls={visualUrl:'',visualType:'image',audioUrl:''};$('form').reset();$('editorTitle').textContent='Nuevo emote';$('cost').value=25;$('duration').value=3;$('size').value=45;$('volume').value=.8;$('position').value='center';$('enterAnimation').value='pop';$('animation').value='float';$('exitAnimation').value='fade';$('enabled').checked=true;$('showCard').checked=false;outputs();files();updateAccessHelp();render();status('Nuevo emote listo.');
}
function load(id){
  const e=emotes.find(x=>x.id===id);if(!e)return;current=e;urls={visualUrl:e.visualUrl||'',visualType:e.visualType||'image',audioUrl:e.audioUrl||''};$('editorTitle').textContent=e.name||e.id;$('id').value=e.id;$('name').value=e.name;$('description').value=e.description||'';$('cost').value=e.cost;$('duration').value=Number(e.durationMs||3000)/1000;$('size').value=e.size||45;$('volume').value=e.audioVolume??.8;$('position').value=e.position||'center';$('enterAnimation').value=e.enterAnimation||'pop';$('animation').value=e.animation||'float';$('exitAnimation').value=e.exitAnimation||'fade';$('enabled').checked=e.enabled!==false;$('showCard').checked=e.showCard===true;outputs();files();updateAccessHelp();render();status('Editando '+e.name+' · Guardar actualizará este mismo emote.');
}
async function refresh(){
  try{const [ec,wr,pr]=await Promise.all([fetch('/api/economy-config',{cache:'no-store'}).then(r=>r.json()),fetch('/api/weekly-rewards',{cache:'no-store'}).then(r=>r.json()),fetch('/api/profile',{cache:'no-store'}).then(r=>r.json())]);currency=ec.branding||currency;weeklyData={config:wr.config||null,active:wr.active||null};owners=pr.profile?.owners||{};}catch{}
  const d=await fetch('/api/emotes',{cache:'no-store'}).then(r=>r.json());emotes=d.emotes||[];render();
  if(current){const targetId=current.id;const still=emotes.find(e=>e.id===targetId);if(still)load(still.id)}else if(emotes.length)load(emotes[0].id);else reset();
}
async function upload(file,kind){if(!file)return null;status('Subiendo '+file.name+'...');const r=await fetch(`/api/upload?kind=${encodeURIComponent(kind)}&filename=${encodeURIComponent(file.name)}`,{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Error de subida');return d}
function payload(){const id=$('id').value.trim().toLowerCase().replace(/^!/,'');return{id,name:$('name').value.trim()||id,description:$('description').value.trim(),accessMode:'general',cost:Number($('cost').value||0),enabled:$('enabled').checked,aliases:[id],visualUrl:urls.visualUrl,visualType:'image',audioUrl:urls.audioUrl,audioVolume:Number($('volume').value||0),durationMs:Math.round(Number($('duration').value||3)*1000),enterAnimation:$('enterAnimation').value,exitAnimation:$('exitAnimation').value,animation:$('animation').value,position:$('position').value,size:Number($('size').value||45),showCard:$('showCard').checked}}

$('form').addEventListener('submit',async e=>{
  e.preventDefault();try{
    const originalId=current?.id||'';
    const visual=await upload($('visualFile').files[0],'visual');if(visual){if(visual.visualType==='video')throw new Error('Para emotes usa PNG, JPG, WEBP o GIF.');urls.visualUrl=visual.url;urls.visualType=visual.visualType||'image'}
    const audio=await upload($('audioFile').files[0],'audio');if(audio)urls.audioUrl=audio.url;
    const emote=payload();if(!emote.id)throw new Error('Escribe un nombre');if(!emote.visualUrl)throw new Error('Sube una imagen o GIF');
    const r=await fetch('/api/emotes/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({emote,originalId})}),d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'No se pudo guardar');
    emotes=d.emotes||[];current=d.emote;$('visualFile').value='';$('audioFile').value='';
    try{const wr=await fetch('/api/weekly-rewards',{cache:'no-store'}).then(x=>x.json());weeklyData={config:wr.config||weeklyData.config,active:wr.active||weeklyData.active}}catch{}
    files();render();updateAccessHelp();status(`✅ ${originalId?'Actualizado':'Creado'}: ${d.emote.name}. El acceso semanal se administra en Recompensas.`);
  }catch(err){status('❌ '+err.message,true)}
});
$('testBtn').onclick=async()=>{const id=current?.id||$('id').value.trim();if(!id){status('Guarda primero el emote.',true);return}const r=await fetch('/api/emotes/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})}),d=await r.json();status(d.ok?'✅ Prueba enviada a OBS.':'❌ '+(d.error||'Error'),!d.ok)};
$('deleteBtn').onclick=async()=>{if(!current||!confirm('¿Eliminar '+current.name+'?'))return;const id=current.id,r=await fetch('/api/emotes/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})}),d=await r.json();if(!d.ok)return status('❌ '+(d.error||'No se pudo eliminar'),true);emotes=d.emotes||[];current=null;await refresh();status('Emote eliminado.')} ;

function revokeBulkUrls(){bulkItems.forEach(x=>{if(x.previewUrl)URL.revokeObjectURL(x.previewUrl)})}
function renderBulk(){const host=$('bulkQueue');$('bulkImportBtn').disabled=!bulkItems.length;if(!bulkItems.length){host.innerHTML='<div class="bulk-empty">Selecciona archivos para preparar la importación.</div>';$('bulkStatus').textContent='Sin archivos pendientes.';return}host.innerHTML=bulkItems.map((x,i)=>`<div class="bulk-row" data-i="${i}"><img src="${esc(x.previewUrl)}"><input data-field="id" value="${esc(x.id)}" title="ID / comando"><input data-field="name" value="${esc(x.name)}" title="Nombre visible"><span class="mini-scope">GENERAL</span><button type="button" class="bulk-remove" data-i="${i}">×</button></div>`).join('');host.querySelectorAll('[data-field]').forEach(el=>el.oninput=()=>{const i=Number(el.closest('.bulk-row').dataset.i);bulkItems[i][el.dataset.field]=el.value});host.querySelectorAll('.bulk-remove').forEach(b=>b.onclick=()=>{const i=Number(b.dataset.i);if(bulkItems[i]?.previewUrl)URL.revokeObjectURL(bulkItems[i].previewUrl);bulkItems.splice(i,1);renderBulk()});$('bulkStatus').textContent=`${bulkItems.length} emote(s) listos para importar.`}
$('bulkFiles').onchange=()=>{revokeBulkUrls();const used=new Set(emotes.map(e=>e.id));bulkItems=[...$('bulkFiles').files].filter(f=>/^image\/(png|jpeg|webp|gif)$/i.test(f.type)||/\.(png|jpe?g|webp|gif)$/i.test(f.name)).map(file=>{const base=slugFromName(file.name);return{file,id:uniqueId(base,used),name:visibleFromName(file.name),description:'',previewUrl:URL.createObjectURL(file)}});renderBulk()};
$('bulkImportBtn').onclick=async()=>{if(!bulkItems.length)return;const btn=$('bulkImportBtn');btn.disabled=true;let ok=0,errors=[];for(let i=0;i<bulkItems.length;i++){const x=bulkItems[i];$('bulkStatus').textContent=`Importando ${i+1}/${bulkItems.length}: ${x.name}`;try{const uploaded=await upload(x.file,'visual');const emote={id:slugFromName(x.id),name:x.name.trim()||x.id,description:'',accessMode:'general',cost:Number($('bulkCost').value||0),enabled:true,aliases:[slugFromName(x.id)],visualUrl:uploaded.url,visualType:'image',audioUrl:'',audioVolume:.8,durationMs:Math.round(Number($('bulkDuration').value||3)*1000),enterAnimation:'pop',exitAnimation:'fade',animation:'float',position:'center',size:45,showCard:false};const r=await fetch('/api/emotes/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({emote})}),d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'No se pudo guardar');ok++}catch(err){errors.push(`${x.name}: ${err.message}`)}}await refresh();revokeBulkUrls();bulkItems=[];$('bulkFiles').value='';renderBulk();btn.disabled=false;$('bulkStatus').textContent=errors.length?`Importados ${ok}. Errores: ${errors.length}. ${errors[0]}`:`✅ ${ok} emotes importados correctamente.`};
$('bulkClearBtn').onclick=()=>{revokeBulkUrls();bulkItems=[];$('bulkFiles').value='';renderBulk()};
$('bulkToggleBtn').onclick=()=>{$('bulkPanel').classList.toggle('hidden')};$('bulkCloseBtn').onclick=()=>{$('bulkPanel').classList.add('hidden')};
$('newBtn').onclick=reset;$('size').oninput=outputs;$('volume').oninput=outputs;$('search').oninput=render;document.querySelectorAll('.filter-tabs button').forEach(b=>b.onclick=()=>{filterMode=b.dataset.filter;document.querySelectorAll('.filter-tabs button').forEach(x=>x.classList.toggle('active',x===b));render()});$('visualFile').onchange=()=>{const f=$('visualFile').files[0];if(f){const u=URL.createObjectURL(f);$('preview').innerHTML=`<img src="${u}">`}};
reset();renderBulk();refresh();
