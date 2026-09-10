/* Portal de Datos Ambientales Hiberus - modulo: alertas automaticas */
async function cargarResumenAlertas(){
  try{
    var r = await fetch('/api/alertas/resumen').then(function(r){return r.json();});
    if(r.exito){
      document.getElementById('al-criticas').textContent = r.pendientes.critica||0;
      document.getElementById('al-medias').textContent   = r.pendientes.media||0;
      document.getElementById('al-informativas').textContent = r.pendientes.informativa||0;
      document.getElementById('al-resueltas').textContent = r.resueltas||0;
      var badge = document.getElementById('badge-alertas-criticas');
      var nc = r.pendientes.critica||0;
      if(badge){ badge.textContent=nc; badge.style.display=nc>0?'':'none'; }
    }
  }catch(e){}
}

async function cargarAlertas(){
  var estado   = document.getElementById('alerta-filtro-estado').value;
  var sev      = document.getElementById('alerta-filtro-severidad').value;
  var tipo     = document.getElementById('alerta-filtro-tipo').value;
  var qs = '?'+(estado?'estado='+estado+'&':'')+(sev?'severidad='+sev+'&':'')+(tipo?'tipo='+tipo:'');
  try{
    var r = await fetch('/api/alertas'+qs).then(function(rr){return rr.json();});
    if(r.exito) _renderAlertas(r.alertas||[]);
  }catch(e){ console.error('Error alertas:',e); }
}

function _renderAlertas(alertas){
  var div = document.getElementById('alertas-lista');
  if(!alertas.length){
    div.innerHTML='<div class="text-center text-muted py-4"><i class="fa-solid fa-check-circle fa-2x text-success mb-2 d-block"></i>No hay alertas con los filtros seleccionados</div>';
    return;
  }
  div.innerHTML = alertas.map(function(a){
    var cls = 'alerta-'+(a.severidad||'media');
    var bdg = 'badge-'+(a.severidad||'media');
    var icon = a.severidad==='critica'?'fa-triangle-exclamation':
               a.severidad==='media'?'fa-circle-exclamation':'fa-circle-info';
    var btns = a.estado==='pendiente'
      ? '<button class="btn btn-xs btn-sm btn-outline-success me-1" onclick="resolverAlerta('+a.id+')" style="font-size:.75rem;padding:2px 8px;"><i class="fa-solid fa-check me-1"></i>Resolver</button>'
        +'<button class="btn btn-xs btn-sm btn-outline-secondary" onclick="ignorarAlerta('+a.id+')" style="font-size:.75rem;padding:2px 8px;">Ignorar</button>'
      : '<span class="badge bg-secondary">'+a.estado+'</span>';
    return '<div class="p-3 mb-2 rounded '+cls+'">'
      +'<div class="d-flex justify-content-between align-items-start flex-wrap gap-2">'
        +'<div>'
          +'<span class="badge '+bdg+' me-2"><i class="fa-solid '+icon+' me-1"></i>'+a.severidad.toUpperCase()+'</span>'
          +'<span class="badge bg-light text-dark me-2">'+a.tipo+'</span>'
          +(a.pais?'<span class="badge bg-light text-dark me-1">'+a.pais+'</span>':'')
          +(a.sede?'<span class="badge bg-light text-dark me-1">'+a.sede+'</span>':'')
          +'<strong class="d-block mt-1">'+a.titulo+'</strong>'
          +(a.descripcion?'<small class="text-muted d-block">'+a.descripcion+'</small>':'')
          +'<small class="text-muted">'+( a.fecha_creacion||'')+'</small>'
        +'</div>'
        +'<div class="text-end">'+btns+'</div>'
      +'</div>'
      +'</div>';
  }).join('');
}

async function generarAlertas(){
  var btn = event.currentTarget;
  btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-1"></i>Analizando...';
  try{
    var r = await fetch('/api/alertas/generar',{method:'POST'}).then(function(rr){return rr.json();});
    toast((r.generadas||0)+' alertas nuevas generadas','success');
    cargarResumenAlertas(); cargarAlertas();
  }catch(e){ toast('Error al generar alertas','danger'); }
  finally{ btn.disabled=false; btn.innerHTML='<i class="fa-solid fa-bolt me-1"></i>Analizar ahora'; }
}

async function resolverAlerta(id){
  try{
    var r = await fetch('/api/alertas/'+id+'/resolver',{method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({})}).then(function(rr){return rr.json();});
    if(r.exito){ toast('Alerta resuelta','success'); cargarResumenAlertas(); cargarAlertas(); }
    else toast('Error: '+r.error,'danger');
  }catch(e){ toast('Error de red','danger'); }
}

async function ignorarAlerta(id){
  try{
    var r = await fetch('/api/alertas/'+id+'/ignorar',{method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({})}).then(function(rr){return rr.json();});
    if(r.exito){ toast('Alerta ignorada','info'); cargarAlertas(); }
    else toast('Error: '+r.error,'danger');
  }catch(e){ toast('Error de red','danger'); }
}
