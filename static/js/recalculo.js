/* Portal de Datos Ambientales Hiberus - modulo: recalculo masivo de emisiones */
function onAlcanceChange(){
  var a=document.getElementById('rc-alcance').value;
  document.getElementById('rc-col-pais').style.display=(a==='pais'||a==='sede'||a==='anio')?'':'none';
  document.getElementById('rc-col-sede').style.display=(a==='sede')?'':'none';
  document.getElementById('rc-col-anio').style.display=(a==='anio')?'':'none';
  document.getElementById('rc-col-fid').style.display=(a==='individual')?'':'none';
  document.getElementById('rc-impacto').style.display='none';
  document.getElementById('btnEjecutarRecalc').disabled=true;
}

async function analizarImpacto(){
  var alcance=document.getElementById('rc-alcance').value;
  var pais=document.getElementById('rc-pais').value;
  var sede=document.getElementById('rc-sede').value;
  var anio=document.getElementById('rc-anio').value;
  var fid=document.getElementById('rc-factura-id').value;
  var url='/api/recalculo/impacto?alcance='+alcance;
  if(pais)url+='&pais='+pais;
  if(sede)url+='&sede='+encodeURIComponent(sede);
  if(anio)url+='&anio='+anio;
  if(fid)url+='&factura_id='+fid;
  try{
    var r=await fetch(url);var d=await r.json();
    if(!d.exito){toast('Error: '+d.error,'danger');return;}
    renderImpacto(d);
    document.getElementById('rc-impacto').style.display='';
    document.getElementById('btnEjecutarRecalc').disabled=(d.facturas_afectadas===0);
  }catch(e){toast('Error de red: '+e.message,'danger');}
}

function renderImpacto(d){
  var signo=d.diferencia>=0?'+':'';
  var col=d.diferencia>0?'text-danger':d.diferencia<0?'text-success':'text-muted';
  var html='<div class="row g-3 mb-3">'
    +'<div class="col-6 col-md-2"><div class="stat-card"><div class="number">'+d.facturas_afectadas+'</div><div class="label">Facturas afectadas</div></div></div>'
    +'<div class="col-6 col-md-2"><div class="stat-card"><div class="number">'+d.paises_afectados+'</div><div class="label">Países</div></div></div>'
    +'<div class="col-6 col-md-2"><div class="stat-card"><div class="number">'+d.sedes_afectadas+'</div><div class="label">Sedes</div></div></div>'
    +'<div class="col-6 col-md-2"><div class="stat-card"><div class="number">'+(d.total_emisiones_original||0).toFixed(2)+'</div><div class="label">Emisiones actuales (tCO₂e)</div></div></div>'
    +'<div class="col-6 col-md-2"><div class="stat-card"><div class="number">'+(d.total_emisiones_nueva||0).toFixed(2)+'</div><div class="label">Emisiones nuevas (tCO₂e)</div></div></div>'
    +'<div class="col-6 col-md-2"><div class="stat-card"><div class="number '+col+'">'+signo+(d.diferencia||0).toFixed(4)+'</div><div class="label">Diferencia (tCO₂e)</div></div></div>'
    +'</div>';
  if(d.desglose&&d.desglose.length){
    html+='<div class="table-responsive"><table class="table table-sm tabla-historial"><thead><tr>'
      +'<th>País</th><th>Año</th><th>Facturas</th><th>Original (tCO₂e)</th><th>Nueva (tCO₂e)</th><th>Δ</th>'
      +'</tr></thead><tbody>'
      +d.desglose.map(function(x){
        var s=x.diferencia>=0?'+':'';var c2=x.diferencia>0?'text-danger':x.diferencia<0?'text-success':'';
        return '<tr><td>'+x.pais+'</td><td>'+x.anio+'</td><td>'+x.facturas+'</td>'
          +'<td>'+x.original.toFixed(4)+'</td><td>'+x.nueva.toFixed(4)+'</td>'
          +'<td class="fw-bold '+c2+'">'+s+x.diferencia.toFixed(4)+'</td></tr>';
      }).join('')
      +'</tbody></table></div>';
  }
  if(d.advertencias&&d.advertencias.length){
    html+='<div class="alert alert-warning mt-2" style="font-size:.82rem;"><i class="fa-solid fa-triangle-exclamation me-1"></i>'
      +d.advertencias.join('<br>')+'</div>';
  }
  document.getElementById('rc-impacto-body').innerHTML=html;
}

async function ejecutarRecalculo(){
  if(!confirm('¿Ejecutar el recálculo? Los valores originales se conservarán intactos. Se guardará un registro completo del recálculo.'))return;
  var payload={
    alcance:document.getElementById('rc-alcance').value,
    pais:document.getElementById('rc-pais').value||undefined,
    sede:document.getElementById('rc-sede').value||undefined,
    anio:document.getElementById('rc-anio').value||undefined,
    factura_id:parseInt(document.getElementById('rc-factura-id').value)||undefined,
    motivo:document.getElementById('rc-motivo').value||'Recálculo manual',
  };
  document.getElementById('btnEjecutarRecalc').disabled=true;
  try{
    var r=await fetch('/api/recalculo/ejecutar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var d=await r.json();
    if(d.exito){
      var res=d.lote&&d.lote.resumen||{};
      var msg='Recálculo completado: '+(d.lote.procesadas_ok||0)+' facturas. Δ='+(res.diferencia||0).toFixed(4)+' tCO₂e';
      toast(msg,'success');
      cargarHistorialRecalculos();
    }else{toast('Error: '+d.error,'danger');}
  }catch(e){toast('Error de red','danger');}
  document.getElementById('btnEjecutarRecalc').disabled=false;
}

async function cargarHistorialRecalculos(){
  try{
    var r=await fetch('/api/recalculo/lotes?limit=30');var d=await r.json();
    var tb=document.getElementById('rc-historial-body');
    if(!d.lotes||d.lotes.length===0){
      tb.innerHTML='<tr><td colspan="10" class="text-center text-muted py-3">Sin recálculos registrados</td></tr>';return;
    }
    tb.innerHTML=d.lotes.map(function(l){
      var res=l.resumen||{};
      var dif=res.diferencia||0;
      var s=dif>=0?'+':'';var col=dif>0?'text-danger':dif<0?'text-success':'';
      var estBadge={'completado':'bg-success','completado_con_errores':'bg-warning text-dark','procesando':'bg-primary','pendiente':'bg-secondary'}[l.estado]||'bg-secondary';
      return '<tr>'
        +'<td><small>'+new Date(l.fecha_inicio).toLocaleString('es-ES')+'</small></td>'
        +'<td><span class="badge bg-info text-dark">'+l.alcance+'</span></td>'
        +'<td><small>'+(l.filtro_pais||'')+(l.filtro_sede?' / '+l.filtro_sede:'')+(l.filtro_anio?' / '+l.filtro_anio:'')+'</small></td>'
        +'<td class="text-center">'+l.total_facturas+'</td>'
        +'<td><span class="badge '+estBadge+'">'+l.estado+'</span></td>'
        +'<td class="text-end">'+(res.total_emisiones_original||0).toFixed(4)+'</td>'
        +'<td class="text-end">'+(res.total_emisiones_nueva||0).toFixed(4)+'</td>'
        +'<td class="text-end fw-bold '+col+'">'+s+dif.toFixed(4)+'</td>'
        +'<td><small>'+(l.usuario||'-')+'</small></td>'
        +'<td><small>'+(l.motivo||'-')+'</small></td>'
        +'</tr>';
    }).join('');
  }catch(e){console.error('Error cargando historial recálculos:',e);}
}
