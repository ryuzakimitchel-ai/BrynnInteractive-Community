const $=id=>document.getElementById(id);
let data=null;
let target='chat';
const defaults={
  chat:{width:450,scale:100,position:'bottom-left',accent:'#76ff6a',backgroundOpacity:92,radius:14},
  alerts:{width:720,scale:100,position:'top-center',accent:'#76ff6a',backgroundOpacity:94,radius:16}
};
const positions={
  chat:[['bottom-left','Abajo izquierda'],['bottom-right','Abajo derecha'],['top-left','Arriba izquierda'],['top-right','Arriba derecha']],
  alerts:[['top-center','Arriba centro'],['center','Centro'],['top-left','Arriba izquierda'],['top-right','Arriba derecha'],['bottom-left','Abajo izquierda'],['bottom-center','Abajo centro'],['bottom-right','Abajo derecha']]
};
function clone(v){return JSON.parse(JSON.stringify(v))}
async function load(){
  try{const r=await fetch('/api/layout-studio',{cache:'no-store'});const d=await r.json();data=d.layout||clone(defaults);render();$('status').textContent='Listo.'}
  catch(e){data=clone(defaults);render();$('status').textContent='No se pudo cargar: '+e.message}
}
function fillPositions(){
  const sel=$('position'); sel.innerHTML='';
  for(const [v,l] of positions[target]){const o=document.createElement('option');o.value=v;o.textContent=l;sel.appendChild(o)}
}
function render(){
  if(!data)data=clone(defaults);
  const c=data[target]||clone(defaults[target]);
  $('targetTitle').textContent=target==='chat'?'Chat':'Alertas';
  $('previewLabel').textContent=target.toUpperCase();
  fillPositions();
  for(const id of ['width','scale','position','accent','backgroundOpacity','radius'])$(id).value=c[id];
  $('accentText').value=c.accent;
  updatePreview();
}
function read(){
  const accent=/^#[0-9a-fA-F]{6}$/.test($('accentText').value)?$('accentText').value:$('accent').value;
  return {width:+$('width').value,scale:+$('scale').value,position:$('position').value,accent,backgroundOpacity:+$('backgroundOpacity').value,radius:+$('radius').value};
}
function place(el,pos){
  el.style.left=el.style.right=el.style.top=el.style.bottom='auto';
  el.style.transformOrigin=pos.includes('right')?'bottom right':'bottom left';
  if(pos==='center'||pos.includes('center')){el.style.left='50%';if(pos==='center')el.style.top='50%';else if(pos.startsWith('top'))el.style.top='24px';else el.style.bottom='24px';}
  if(pos.includes('left'))el.style.left='24px';
  if(pos.includes('right'))el.style.right='24px';
  if(pos.startsWith('top'))el.style.top='24px';
  if(pos.startsWith('bottom'))el.style.bottom='24px';
}
function updatePreview(){
  if(!data)return; data[target]=read(); const c=data[target];
  $('widthOut').textContent=c.width+' px';$('scaleOut').textContent=c.scale+'%';$('opacityOut').textContent=c.backgroundOpacity+'%';$('radiusOut').textContent=c.radius+' px';
  const chat=$('chatPreview'),alert=$('alertPreview');
  chat.classList.toggle('hidden',target!=='chat');alert.classList.toggle('hidden',target!=='alerts');
  const el=target==='chat'?chat:alert;
  el.style.width=c.width+'px';el.style.scale=(c.scale/100);el.style.setProperty('--preview-accent',c.accent);el.style.borderRadius=c.radius+'px';
  if(target==='chat')el.querySelector('.message-card').style.background=`rgba(16,18,28,${c.backgroundOpacity/100})`;
  else el.style.background=`rgba(16,18,28,${c.backgroundOpacity/100})`;
  place(el,c.position);
  if(c.position==='center'||c.position.includes('center')){
    const scale=c.scale/100;
    const x='translateX(-50%)'; const y=c.position==='center'?' translateY(-50%)':'';
    el.style.transform=x+y;
  }else el.style.transform='';
}
for(const id of ['width','scale','position','backgroundOpacity','radius'])$(id).addEventListener('input',updatePreview);
$('accent').addEventListener('input',()=>{$('accentText').value=$('accent').value;updatePreview()});
$('accentText').addEventListener('input',()=>{if(/^#[0-9a-fA-F]{6}$/.test($('accentText').value)){$('accent').value=$('accentText').value;updatePreview()}});
document.querySelectorAll('.target-tab').forEach(btn=>btn.onclick=()=>{document.querySelectorAll('.target-tab').forEach(x=>x.classList.remove('active'));btn.classList.add('active');target=btn.dataset.target;render()});
$('resetBtn').onclick=()=>{data[target]=clone(defaults[target]);render();$('status').textContent='Target restablecido localmente. Pulsa Guardar.'};
$('controls').onsubmit=async e=>{e.preventDefault();data[target]=read();$('status').textContent='Guardando...';try{const r=await fetch('/api/layout-studio/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({layout:data})});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Error');data=d.layout;$('status').textContent='✅ Layout guardado. OBS lo aplicará automáticamente.';render()}catch(err){$('status').textContent='❌ '+err.message}};
load();
