/* Portal de Datos Ambientales Hiberus - modulo: factores de emision y fuentes bibliograficas */
var modalFactorBS=null;
var modalHistorialFactorBS=null;
var modalFuenteBS=null;

function switchSubTab(sub){
  document.getElementById('sub-tab-factores-lista').style.display=sub==='factores-lista'?'':'none';
  document.getElementById('sub-tab-fuentes-lista').style.display=sub==='fuentes-lista'?'':'none';
  document.getElementById('sub-tab-factores-btn').classList.toggle('active',sub==='factores-lista');
  document.getElementById('sub-tab-fuentes-btn').classList.toggle('active',sub==='fuentes-lista');
}

async function cargarFactores(){
  var pais=document.getElementById('filtro-pais-factor').value;
  var anio=document.getElementById('filtro-anio-factor').value;
  var soloActivos=document.getElementById('filtro-solo-activos').checked?'1':'0';
  var url='/api/factores?solo_versiones_activas='+soloActivos;
  if(pais)url+='&pais='+pais;
  if(anio&&anio.length===4)url+='&anio='+anio;
  try{
    var r=await fetch(url);var d=await r.json();
    renderTablaFactores(d.factores||[]);
  }catch(e){
    document.getElementById('tablaFactoresBody').innerHTML=
      '<tr><td colspan="10" class="text-center text-danger">Error cargando factores</td></tr>';
  }
}

function renderTablaFactores(filas){
  var tb=document.getElementById('tablaFactoresBody');
  if(filas.length===0){
    tb.innerHTML='<tr><td colspan="10" class="text-center text-muted py-4">No hay factores disponibles</td></tr>';return;
  }
  tb.innerHTML=filas.map(function(f){
    var actBadge=f.es_version_activa
      ?'<span class="badge bg-success">Activo</span>'
      :'<span class="badge bg-secondary">Inactivo</span>';
    return '<tr>'
      +'<td><span class="badge" style="background:#e8eef7;color:var(--primary);">'+f.pais+'</span></td>'
      +'<td>'+f.tipo_energia+'</td>'
      +'<td>'+f.anio+'</td>'
      +'<td class="text-center">v'+f.version+'</td>'
      +'<td class="text-end fw-bold">'+f.factor_kg_co2_mwh+'</td>'
      +'<td><small>'+f.unidad+'</small></td>'
      +'<td><small title="'+(f.fuente_organizacion||'')+'">'+(f.fuente_nombre||'-')+'</small></td>'
      +'<td><small>'+(f.fecha_vigencia_desde||'-')+'</small></td>'
      +'<td>'+actBadge+'</td>'
      +'<td>'
        +'<div class="d-flex gap-1">'
        +'<button class="btn btn-sm btn-outline-primary py-0 px-1" title="Nueva versión" onclick="abrirModalNuevaVersion('+f.id+','+JSON.stringify(f).replace(/"/g,"'")+')"><i class="fa-solid fa-code-branch"></i></button>'
        +'<button class="btn btn-sm btn-outline-secondary py-0 px-1" title="Historial" onclick="verHistorialFactor('+f.id+')"><i class="fa-solid fa-clock-rotate-left"></i></button>'
        +(f.es_version_activa
          ?'<button class="btn btn-sm btn-outline-warning py-0 px-1" title="Desactivar" onclick="cambiarEstadoFactor('+f.id+',false)"><i class="fa-solid fa-toggle-off"></i></button>'
          :'<button class="btn btn-sm btn-outline-success py-0 px-1" title="Activar" onclick="cambiarEstadoFactor('+f.id+',true)"><i class="fa-solid fa-toggle-on"></i></button>')
        +'</div>'
      +'</td>'
      +'</tr>';
  }).join('');
}

async function cargarFuentes(){
  try{
    var r=await fetch('/api/fuentes?solo_activas=0');var d=await r.json();
    renderTablaFuentes(d.fuentes||[]);
  }catch(e){
    document.getElementById('tablaFuentesBody').innerHTML=
      '<tr><td colspan="7" class="text-center text-danger">Error cargando fuentes</td></tr>';
  }
}

function renderTablaFuentes(filas){
  var tb=document.getElementById('tablaFuentesBody');
  if(filas.length===0){
    tb.innerHTML='<tr><td colspan="7" class="text-center text-muted py-4">No hay fuentes registradas</td></tr>';return;
  }
  tb.innerHTML=filas.map(function(f){
    return '<tr>'
      +'<td><code>'+f.codigo+'</code></td>'
      +'<td>'+f.nombre+'</td>'
      +'<td>'+(f.organizacion||'-')+'</td>'
      +'<td class="text-center">'+(f.anio_publicacion||'-')+'</td>'
      +'<td>'+(f.url?'<a href="'+f.url+'" target="_blank" rel="noopener"><i class="fa-solid fa-arrow-up-right-from-square"></i></a>':'-')+'</td>'
      +'<td><small>'+(f.notas||'-')+'</small></td>'
      +'<td><button class="btn btn-sm btn-outline-secondary py-0 px-1" onclick="abrirModalEditarFuente('+JSON.stringify(f).replace(/"/g,"'")+')"><i class="fa-solid fa-pen"></i></button></td>'
      +'</tr>';
  }).join('');
}

async function rellenarSelectFuentes(){
  try{
    var r=await fetch('/api/fuentes?solo_activas=1');var d=await r.json();
    var sel=document.getElementById('mf-fuente-id');
    sel.innerHTML='<option value="">-- Selecciona --</option>';
    (d.fuentes||[]).forEach(function(f){
      var o=document.createElement('option');o.value=f.id;
      o.textContent=f.nombre+' ('+f.codigo+')';sel.appendChild(o);
    });
  }catch(e){console.error('Error cargando fuentes para select:',e);}
}

function abrirModalNuevoFactor(){
  document.getElementById('mf-mode').value='crear';
  document.getElementById('mf-factor-id').value='';
  document.getElementById('modalFactorTitulo').textContent='Nuevo factor de emisión';
  ['mf-pais','mf-anio','mf-valor','mf-unidad','mf-fuente-id','mf-vigencia-desde','mf-vigencia-hasta','mf-descripcion','mf-notas'].forEach(function(id){
    var el=document.getElementById(id);if(el)el.value='';
  });
  document.getElementById('mf-tipo-energia').value='electricidad';
  document.getElementById('mf-unidad').value='kg CO2eq/MWh';
  document.getElementById('mf-pais').disabled=false;
  document.getElementById('mf-anio').disabled=false;
  rellenarSelectFuentes();
  if(modalFactorBS)modalFactorBS.show();
}

function abrirModalNuevaVersion(factorId, f){
  document.getElementById('mf-mode').value='version';
  document.getElementById('mf-factor-id').value=factorId;
  document.getElementById('modalFactorTitulo').textContent='Nueva versión — '+f.pais+' '+f.tipo_energia+' '+f.anio;
  document.getElementById('mf-pais').value=f.pais;document.getElementById('mf-pais').disabled=true;
  document.getElementById('mf-anio').value=f.anio;document.getElementById('mf-anio').disabled=true;
  document.getElementById('mf-tipo-energia').value=f.tipo_energia;
  document.getElementById('mf-valor').value='';
  document.getElementById('mf-unidad').value=f.unidad||'kg CO2eq/MWh';
  document.getElementById('mf-vigencia-desde').value=new Date().toISOString().slice(0,10);
  document.getElementById('mf-vigencia-hasta').value='';
  document.getElementById('mf-descripcion').value=f.descripcion||'';
  document.getElementById('mf-notas').value='';
  rellenarSelectFuentes();
  if(modalFactorBS)modalFactorBS.show();
}

async function guardarFactor(){
  var mode=document.getElementById('mf-mode').value;
  var payload={
    pais:document.getElementById('mf-pais').value,
    anio:document.getElementById('mf-anio').value,
    tipo_energia:document.getElementById('mf-tipo-energia').value,
    factor_kg_co2_mwh:parseFloat(document.getElementById('mf-valor').value),
    unidad:document.getElementById('mf-unidad').value||'kg CO2eq/MWh',
    fuente_id:parseInt(document.getElementById('mf-fuente-id').value)||null,
    descripcion:document.getElementById('mf-descripcion').value||null,
    notas:document.getElementById('mf-notas').value||null,
    fecha_vigencia_desde:document.getElementById('mf-vigencia-desde').value||null,
    fecha_vigencia_hasta:document.getElementById('mf-vigencia-hasta').value||null,
  };
  if(!payload.fuente_id){toast('Debes seleccionar una fuente','warning');return;}
  if(!payload.factor_kg_co2_mwh||payload.factor_kg_co2_mwh<=0){toast('El valor del factor debe ser positivo','warning');return;}
  try{
    var url, method;
    if(mode==='crear'){url='/api/factores';method='POST';}
    else{url='/api/factores/'+document.getElementById('mf-factor-id').value+'/nueva-version';method='PUT';}
    var r=await fetch(url,{method:method,headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var d=await r.json();
    if(d.exito){
      toast(mode==='crear'?'Factor creado correctamente':'Nueva versión creada','success');
      if(modalFactorBS)modalFactorBS.hide();
      cargarFactores();
    }else{toast('Error: '+d.error,'danger');}
  }catch(e){toast('Error de red: '+e.message,'danger');}
}

async function cambiarEstadoFactor(id,activo){
  var msg=activo?'¿Activar este factor?':'¿Desactivar este factor?';
  if(!confirm(msg))return;
  try{
    var r=await fetch('/api/factores/'+id+'/estado',
      {method:'PATCH',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({activo:activo})});
    var d=await r.json();
    if(d.exito){toast(activo?'Factor activado':'Factor desactivado','success');cargarFactores();}
    else{toast('Error: '+d.error,'danger');}
  }catch(e){toast('Error de red','danger');}
}

async function verHistorialFactor(id){
  document.getElementById('modalHistorialFactorBody').innerHTML='<p class="text-muted">Cargando...</p>';
  if(modalHistorialFactorBS)modalHistorialFactorBS.show();
  try{
    var r=await fetch('/api/factores/'+id+'/historial');var d=await r.json();
    var eventos=d.historial||[];
    if(eventos.length===0){
      document.getElementById('modalHistorialFactorBody').innerHTML='<p class="text-muted">Sin historial registrado.</p>';return;
    }
    var accionBadge=function(a){
      var cols={creado:'success',nueva_version:'primary',editado_metadatos:'info',activado:'success',desactivado:'secondary',importado:'light'};
      return '<span class="badge bg-'+(cols[a]||'secondary')+'">'+a+'</span>';
    };
    document.getElementById('modalHistorialFactorBody').innerHTML=
      '<table class="table table-sm tabla-historial"><thead><tr>'
      +'<th>Fecha</th><th>Acción</th><th>Campo</th><th>Antes</th><th>Después</th><th>Versión</th><th>Usuario</th><th>Notas</th>'
      +'</tr></thead><tbody>'
      +eventos.map(function(e){
        return '<tr>'
          +'<td><small>'+new Date(e.fecha_cambio).toLocaleString('es-ES')+'</small></td>'
          +'<td>'+accionBadge(e.accion)+'</td>'
          +'<td><small>'+(e.campo||'-')+'</small></td>'
          +'<td><small class="text-danger">'+(e.valor_anterior||'-')+'</small></td>'
          +'<td><small class="text-success">'+(e.valor_nuevo||'-')+'</small></td>'
          +'<td class="text-center">'+(e.version_resultante!=null?'v'+e.version_resultante:'-')+'</td>'
          +'<td><small>'+(e.usuario||'-')+'</small></td>'
          +'<td><small>'+(e.notas||'-')+'</small></td>'
          +'</tr>';
      }).join('')
      +'</tbody></table>';
  }catch(ex){document.getElementById('modalHistorialFactorBody').innerHTML='<p class="text-danger">Error cargando historial</p>';}
}

function abrirModalNuevaFuente(){
  document.getElementById('mfuente-id').value='';
  document.getElementById('modalFuenteTitulo').textContent='Nueva fuente bibliográfica';
  ['mfuente-codigo','mfuente-nombre','mfuente-organizacion','mfuente-anio','mfuente-url','mfuente-notas'].forEach(function(id){
    document.getElementById(id).value='';
  });
  document.getElementById('mfuente-codigo').disabled=false;
  if(modalFuenteBS)modalFuenteBS.show();
}

function abrirModalEditarFuente(f){
  document.getElementById('mfuente-id').value=f.id;
  document.getElementById('modalFuenteTitulo').textContent='Editar fuente — '+f.codigo;
  document.getElementById('mfuente-codigo').value=f.codigo;
  document.getElementById('mfuente-codigo').disabled=true;
  document.getElementById('mfuente-nombre').value=f.nombre||'';
  document.getElementById('mfuente-organizacion').value=f.organizacion||'';
  document.getElementById('mfuente-anio').value=f.anio_publicacion||'';
  document.getElementById('mfuente-url').value=f.url||'';
  document.getElementById('mfuente-notas').value=f.notas||'';
  if(modalFuenteBS)modalFuenteBS.show();
}

async function guardarFuente(){
  var id=document.getElementById('mfuente-id').value;
  var payload={
    codigo:document.getElementById('mfuente-codigo').value.trim().toUpperCase(),
    nombre:document.getElementById('mfuente-nombre').value.trim(),
    organizacion:document.getElementById('mfuente-organizacion').value||null,
    anio_publicacion:document.getElementById('mfuente-anio').value||null,
    url:document.getElementById('mfuente-url').value||null,
    notas:document.getElementById('mfuente-notas').value||null,
  };
  if(!payload.nombre){toast('El nombre es obligatorio','warning');return;}
  try{
    var url=id?'/api/fuentes/'+id:'/api/fuentes';
    var method=id?'PUT':'POST';
    var r=await fetch(url,{method:method,headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var d=await r.json();
    if(d.exito){
      toast(id?'Fuente actualizada':'Fuente creada','success');
      if(modalFuenteBS)modalFuenteBS.hide();
      cargarFuentes();
    }else{toast('Error: '+d.error,'danger');}
  }catch(e){toast('Error de red: '+e.message,'danger');}
}
