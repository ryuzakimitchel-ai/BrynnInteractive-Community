const $=id=>document.getElementById(id);
function state(el,text,kind=''){el.textContent=text;el.className=kind}
async function refresh(){
  $('status').textContent='Consultando diagnóstico...';
  try{
    const r=await fetch('/api/diagnostics',{cache:'no-store'});const d=await r.json();
    if(!r.ok||!d.ok)throw new Error(d.error||'No disponible');
    state($('serverState'),'🟢 Activo','ok');$('serverDetail').textContent=`Puertos ${d.ports.local} / ${d.ports.webhook} · ${d.serverSession}`;
    const sl=d.integrations.streamlabs||{}; state($('streamlabsState'),sl.connected?'🟢 Conectado':sl.tokenPresent?'🟡 Preparando':'⚪ Sin configurar',sl.connected?'ok':sl.tokenPresent?'warn':'');$('streamlabsDetail').textContent=`Bridge ${sl.activeBridges||0} · ${sl.state||''}`;
    const tk=d.integrations.tikfinity||{}; state($('tikfinityState'),tk.enabled?'🟢 Habilitado':'⚪ Deshabilitado',tk.enabled?'ok':'');$('tikfinityDetail').textContent=`${tk.mode||''} · ${tk.publicBaseUrl||'sin URL pública'}`;
    state($('wsState'),d.websocketClient?'🟢 Disponible':'🔴 No disponible',d.websocketClient?'ok':'bad');$('wsDetail').textContent=`Eventos ${d.eventsBuffered} · debug ${d.debugEventsBuffered}`;
    const files=$('files');files.innerHTML='';
    for(const [name,row] of Object.entries(d.files||{})){
      const div=document.createElement('div');div.className='file-row';div.innerHTML=`<b>${name}</b><code>${row.path}</code><span class="${row.parentWritable?'ok':'bad'}">${row.parentWritable?'Escribible':'Sin escritura'}</span>`;files.appendChild(div);
    }
    $('raw').textContent=JSON.stringify(d,null,2);$('status').textContent='✅ Diagnóstico actualizado.';
  }catch(e){state($('serverState'),'🔴 Error','bad');$('status').textContent='❌ '+e.message}
}
async function test(kind){
  const map={
    'streamlabs-follow':{service:'streamlabs',type:'follow'},
    'streamlabs-bits':{service:'streamlabs',type:'bits'},
    'tikfinity-follow':{service:'tikfinity',type:'follow'},
    'tikfinity-like':{service:'tikfinity',type:'like'}
  };
  $('status').textContent='Ejecutando prueba...';
  try{const r=await fetch('/api/integrations/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(map[kind])});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Error');$('status').textContent='✅ Señal de prueba enviada. Revisa Alertas / Monitor.';setTimeout(refresh,350)}catch(e){$('status').textContent='❌ '+e.message}
}
$('refreshBtn').onclick=refresh;document.querySelectorAll('[data-test]').forEach(b=>b.onclick=()=>test(b.dataset.test));refresh();setInterval(refresh,6000);
