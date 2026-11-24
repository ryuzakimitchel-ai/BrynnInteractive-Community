/* Seguidores: configuración local. El navegador nunca recibe tokens guardados. */
(()=>{
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={tiktok:'TikTok',kick:'Kick',twitch:'Twitch'};
  const sources={none:'Sin cifra inicial',manual:'Cifra manual',event_estimate:'Estimación por follows',official:'API oficial',external:'Fuente HTTPS externa'};
  const friendly=time=>time?new Date(time).toLocaleString('es-MX'):'Nunca';
  async function json(url,opts){
    const response=await fetch(url,{cache:'no-store',...opts});
    const body=await response.json();
    if(!response.ok||body.ok===false)throw Error(body.error||'HTTP '+response.status);
    return body;
  }
  const post=(url,body)=>json(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  function setMessage(text,isError=false){const el=$('followersStatus');el.textContent=text;el.style.color=isError?'#ff8995':'#97f1ce'}
  async function refresh(){
    try{
      const d=await json('/api/followers');
      $('followersInterval').value=d.intervalSeconds;
      for(const platform of ['tiktok','kick','twitch']){
        const r=d.platforms[platform]||{};
        $('followersCount_'+platform).textContent=r.count===null||r.count===undefined?'—':Number(r.count).toLocaleString('es-MX');
        const status=r.fresh?'VERIFICADO':(r.count==null?'SIN BASE':'ESTIMADO');
        $('followersState_'+platform).textContent=status+' · '+(sources[r.source]||r.source||'');
        $('followersState_'+platform).className='followers-chip '+(r.fresh?'verified':'estimated');
        $('followersTime_'+platform).textContent='Consulta: '+friendly(r.checkedAt)+' · Cambio: '+friendly(r.updatedAt);
        $('followersError_'+platform).textContent=r.lastError||'';
      }
      $('tiktokTokenStatus').textContent=d.settings?.tiktok?.tokenPresent?'Token guardado (no se muestra)':'Sin token de estadísticas';
      if(document.activeElement!==$('kickFollowersUrl'))$('kickFollowersUrl').value=d.settings?.kick?.externalUrl||'';
    }catch(e){setMessage('No se pudo consultar seguidores: '+e.message,true)}
  }
  async function sync(platform){
    setMessage('Consultando '+labels[platform]+'…');
    try{const d=await post('/api/followers/sync',{platform});setMessage(labels[platform]+': '+d.count+' seguidores recibidos.');}
    catch(e){setMessage(labels[platform]+': '+e.message,true)}
    await refresh();
  }
  for(const platform of ['tiktok','kick','twitch']){
    $('followersSync_'+platform).onclick=()=>sync(platform);
    $('followersManual_'+platform).onclick=async()=>{
      const input=$('followersManualValue_'+platform);
      if(input.value===''||!Number.isInteger(Number(input.value))||Number(input.value)<0){
        setMessage('Escribe un total entero no negativo para '+labels[platform],true);return;
      }
      try{await post('/api/followers/manual',{platform,count:Number(input.value)});setMessage('Cifra inicial de '+labels[platform]+' guardada. Se mostrará como estimación.');await refresh();}
      catch(e){setMessage(e.message,true)}
    };
  }
  $('followersSave').onclick=async()=>{
    const tiktok={},kick={externalUrl:$('kickFollowersUrl').value.trim()};
    for(const id of ['accessToken','refreshToken','clientKey','clientSecret']){
      const value=$('tiktok_'+id).value.trim();
      if(value)tiktok[id]=value;
    }
    if($('clearTikTokAuth').checked)tiktok.clearCredentials=true;
    try{
      await post('/api/followers/settings',{intervalSeconds:parseInt($('followersInterval').value,10)||180,tiktok,kick});
      for(const id of ['accessToken','refreshToken','clientKey','clientSecret'])$('tiktok_'+id).value='';
      $('clearTikTokAuth').checked=false;
      setMessage('Opciones de sincronización guardadas.');await refresh();
    }catch(e){setMessage(e.message,true)}
  };
  $('followersRefreshAll').onclick=async()=>{
    for(const p of ['tiktok','kick','twitch'])await sync(p);
  };
  refresh();setInterval(refresh,7000);
})();
