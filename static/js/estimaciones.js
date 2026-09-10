/* Portal de Datos Ambientales Hiberus - modulo: estimaciones y periodos faltantes */
var modalEstimacionBS=null;

async function detectarGaps(){
  var pais=document.getElementById('est-pais').value;
  var anio=document.getElementById('est-anio').value;
  var url='/api/estimaciones/gaps';
  var sep='?';
  if(pais){url+=sep+'pais='+pais;sep='&';}
  if(anio&&anio.length===4){url+=sep+'anio='+anio;sep='&';}
  try{
    var r=await fetch(url);var d=await r.json();
    var panel=document.getElementById('est-gaps-panel');
    var tb=document.getElementById('est-gaps-body');
    if(!d.faltantes||d.faltantes.length===0){
      panel.style.display='none';
    }else{
      panel.style.display='';
      tb.innerHTML=d.faltantes.map(function(f){
        return '<tr>'
          +'<td><span class="badge" style="background:#e8eef7;color:var(--primary);">'+f.pais+'</span></td>'
          +'<td>'+f.sede+'</td>'
          +'<td><strong>'+f.mes+'</strong></td>'
          +'<td><span class="badge bg-danger">Faltante</span></td>'
          +'<td><button class="btn btn-sm btn-outline-warning py-0 px-1" onclick="rellenarEstimacion(\''+f.pais+'\',\''+f.sede+'\',\''+f.mes+'\')"><i class="fa-solid fa-wand-magic-sparkles me-1"></i>Estimar</button></td>'
          +'</tr>';
      }).join('');
    }
    cargarEstimaciones();
  }catch(e){console.error('Error detectando gaps:',e);}
}

async function cargarEstimaciones(){
  var pais=document.getElementById('est-pais').value;
  var anio=document.getElementById('est-anio').value;
  var url='/api/estimaciones?estado=vigente';
  if(pais)url+='&pais='+pais;
  if(anio&&anio.length===4)url+='&anio='+anio;
  try{
    var r=await fetch(url);var d=await r.json();
    var tb=document.getElementById('est-lista-body');
    if(!d.estimaciones||d.estimaciones.length===0){
      tb.innerHTML='<tr><td colspan="10" class="text-center text-muted py-3">Sin estimaciones vigentes</td></tr>';return;
    }
    var metLbl={'media_historica':'Media histórica','mismo_mes_anio_anterior':'Mismo mes año ant.','adyacente':'Adyacentes','manual':'Manual'};
    tb.innerHTML=d.estimaciones.map(function(e){
      var conf=Math.round((e.confianza||0)*100);
      var confCol=conf>=80?'bg-success':conf>=60?'bg-warning text-dark':'bg-danger';
      var estBadge={'vigente':'bg-success','sustituida':'bg-info text-dark','rechazada':'bg-secondary'}[e.estado]||'bg-secondary';
      return '<tr>'
        +'<td><span class="badge" style="background:#e8eef7;color:var(--primary);">'+e.pais+'</span></td>'
        +'<td>'+e.sede+'</td>'
        +'<td><strong>'+e.mes+'</strong></td>'
        +'<td><small>'+(metLbl[e.metodo_estimacion]||e.metodo_estimacion)+'</small></td>'
        +'<td class="text-end">'+((e.consumo_kwh_estimado||0).toLocaleString('es-ES'))+'</td>'
        +'<td class="text-end fw-bold">'+(e.emisiones_estimadas||0).toFixed(4)+'</td>'
        +'<td class="text-center"><span class="badge '+confCol+'" style="font-size:.7rem;">'+conf+'%</span></td>'
        +'<td><span class="badge '+estBadge+'">'+e.estado+'</span></td>'
        +'<td class="text-center">'+(e.desviacion_porcentual_real!=null?e.desviacion_porcentual_real.toFixed(1)+'%':'-')+'</td>'
        +'<td><button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="rechazarEstimacion('+e.id+')" title="Rechazar"><i class="fa-solid fa-xmark"></i></button></td>'
        +'</tr>';
    }).join('');
  }catch(e){console.error('Error cargando estimaciones:',e);}
}

function rellenarEstimacion(pais,sede,mes){
  document.getElementById('me-pais').value=pais;
  document.getElementById('me-sede').value=sede;
  document.getElementById('me-mes').value=mes;
  document.getElementById('me-metodo').value='media_historica';
  document.getElementById('me-col-manual').style.display='none';
  document.getElementById('me-notas').value='';
  if(modalEstimacionBS)modalEstimacionBS.show();
}

function abrirModalEstimacion(){
  document.getElementById('me-pais').value='';
  document.getElementById('me-sede').value='';
  document.getElementById('me-mes').value='';
  document.getElementById('me-metodo').value='media_historica';
  document.getElementById('me-col-manual').style.display='none';
  document.getElementById('me-notas').value='';
  if(modalEstimacionBS)modalEstimacionBS.show();
}

function toggleValorManual(){
  var m=document.getElementById('me-metodo').value;
  document.getElementById('me-col-manual').style.display=m==='manual'?'':'none';
}

async function guardarEstimacion(){
  var payload={
    pais:document.getElementById('me-pais').value,
    sede:document.getElementById('me-sede').value,
    mes:document.getElementById('me-mes').value,
    metodo:document.getElementById('me-metodo').value,
    notas:document.getElementById('me-notas').value||null,
  };
  var vm=parseFloat(document.getElementById('me-valor-manual').value);
  if(payload.metodo==='manual'){
    if(!vm||vm<=0){toast('Introduce un valor manual válido','warning');return;}
    payload.valor_manual=vm;
  }
  if(!payload.pais||!payload.sede||!payload.mes){toast('País, sede y mes son obligatorios','warning');return;}
  try{
    var r=await fetch('/api/estimaciones',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var d=await r.json();
    if(d.exito){
      toast('Estimación creada: '+d.estimacion.consumo_kwh_estimado+' kWh','success');
      if(modalEstimacionBS)modalEstimacionBS.hide();
      cargarEstimaciones();detectarGaps();
    }else{toast('Error: '+d.error,'danger');}
  }catch(e){toast('Error de red: '+e.message,'danger');}
}

async function rechazarEstimacion(id){
  if(!confirm('¿Rechazar esta estimación?'))return;
  try{
    var r=await fetch('/api/estimaciones/'+id,{method:'DELETE'});
    var d=await r.json();
    if(d.exito){toast('Estimación rechazada','success');cargarEstimaciones();}
    else{toast('Error: '+d.error,'danger');}
  }catch(e){toast('Error de red','danger');}
}
