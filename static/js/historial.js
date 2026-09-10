/* Portal de Datos Ambientales Hiberus - modulo: historial (listado, paginacion, exportacion) */
async function cargarEstadisticas(){
  try{
    var r=await fetch('/api/estadisticas');var d=await r.json();
    if(!d.exito)return;
    document.getElementById('st-facturas').textContent=d.total_facturas;
    document.getElementById('st-emisiones').textContent=d.total_emisiones.toFixed(2);
    document.getElementById('st-consumo').textContent=d.total_consumo.toFixed(2);
    document.getElementById('st-paises').textContent=d.num_paises;
    document.getElementById('statsRow').style.display='';
  }catch(e){console.error('Stats:',e);}
}

async function cargarHistorial(page){
  paginaActual=page||1;
  var pais=document.getElementById('filtroPais').value||'';
  var anio=document.getElementById('filtroAnio').value||'';
  var url='/api/historial?page='+paginaActual+'&per_page='+POR_PAGINA;
  if(pais)url+='&pais='+pais;
  if(anio)url+='&anio='+anio;
  try{
    var r=await fetch(url);var d=await r.json();
    renderTabla(d.historial||[]);renderPaginacion(d.total||0,d.page,d.per_page);
    document.getElementById('totalRegistros').textContent=(d.total||0)+' registro'+(d.total!==1?'s':'');
    // El panel de consumo mensual comparte los filtros de pais/anio.
    if(consumoMensualCargado)cargarConsumoMensual();
  }catch(e){
    document.getElementById('cuerpoTabla').innerHTML='<tr><td colspan="13" class="text-center text-danger">Error cargando historial</td></tr>';
  }
}

function renderTabla(filas){
  var tbody=document.getElementById('cuerpoTabla');
  if(filas.length===0){
    tbody.innerHTML='<tr><td colspan="13" class="text-center text-muted py-4">No hay facturas procesadas aun</td></tr>';return;
  }
  tbody.innerHTML=filas.map(function(f){
    var periodo=f.periodo_inicio&&f.periodo_fin
      ?(f.periodo_inicio.slice(0,7)+' > '+f.periodo_fin.slice(0,7)):(f.mes||'-');
    var bc='badge-estado-'+(f.estado||'procesada');
    var conf=f.confianza_ocr!=null?Math.round(f.confianza_ocr*100):null;
    var cb=conf!=null?(' <span class="badge '+(conf>=80?'bg-success':conf>=60?'bg-warning text-dark':'bg-danger')+'" title="Confianza OCR" style="font-size:.68rem;">'+conf+'%</span>'):'';
    // Importe con su divisa: sin ella la columna no seria comparable entre paises.
    var imp=f.importe_total!=null
      ?(f.importe_total.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' '+(f.moneda||''))
      :'<span class="text-muted">-</span>';
    var tar=f.tarifa?('<span class="badge bg-light text-dark border" style="font-size:.68rem;">'+f.tarifa+'</span>'):'<span class="text-muted">-</span>';
    return '<tr>'
      +'<td><span class="badge" style="background:#e8eef7;color:var(--primary);">'+f.pais+'</span></td>'
      +'<td>'+f.sede+'</td>'
      +'<td class="text-truncate" style="max-width:130px;" title="'+(f.sociedad||'')+'">'+(f.sociedad||'<span class="text-muted">-</span>')+'</td>'
      +'<td>'+(f.comercializadora||'<span class="text-muted">-</span>')+'</td>'
      +'<td style="white-space:nowrap;">'+periodo+cb+'</td>'
      +'<td class="text-center">'+(f.dias_facturados!=null?f.dias_facturados:'-')+'</td>'
      +'<td class="text-end">'+((f.consumo_mwh||0).toFixed(2))+'</td>'
      +'<td class="text-end fw-bold" style="color:var(--primary);">'+((f.emisiones_tco2e||0).toFixed(4))+'</td>'
      +'<td>'+tar+'</td>'
      +'<td class="text-end" style="white-space:nowrap;">'+imp+'</td>'
      +'<td><span class="badge '+bc+'" style="font-size:.72rem;">'+(f.estado||'procesada')+'</span></td>'
      +'<td><small>'+(f.fecha_carga?new Date(f.fecha_carga).toLocaleDateString('es-ES'):'-')+'</small></td>'
      +'<td><button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="eliminarFactura('+f.id+')" title="Eliminar"><i class="fa-solid fa-trash-can"></i></button></td>'
      +'</tr>';
  }).join('');
}

function renderPaginacion(total,page,perPage){
  var nav=document.getElementById('paginacion');var ul=document.getElementById('listaPaginas');
  var tp=Math.ceil(total/perPage);
  if(tp<=1){nav.style.display='none';return;}
  nav.style.display='';
  var h='<li class="page-item '+(page<=1?'disabled':'')+'"><a class="page-link" href="#" onclick="cargarHistorial('+(page-1)+');return false;">&lsaquo;</a></li>';
  for(var i=1;i<=tp;i++){
    if(i===1||i===tp||Math.abs(i-page)<=2){
      h+='<li class="page-item '+(i===page?'active':'')+'"><a class="page-link" href="#" onclick="cargarHistorial('+i+');return false;">'+i+'</a></li>';
    }else if(Math.abs(i-page)===3){
      h+='<li class="page-item disabled"><span class="page-link">&hellip;</span></li>';
    }
  }
  h+='<li class="page-item '+(page>=tp?'disabled':'')+'"><a class="page-link" href="#" onclick="cargarHistorial('+(page+1)+');return false;">&rsaquo;</a></li>';
  ul.innerHTML=h;
}

/* Consumo mensual por sede: una sede puede tener varios puntos de suministro
   (CUPS) y recibir una factura de cada uno en el mismo mes. El consumo del mes
   es la SUMA de todas ellas; aqui se muestra ese total con su desglose para
   poder comprobar que ninguna factura queda fuera del calculo. */
var consumoMensualCargado=false;
var datosConsumoMensual=[];

function toggleConsumoMensual(){
  var cuerpo=document.getElementById('cuerpoConsumoMensual');
  var icono=document.getElementById('iconoConsumoMensual');
  var abierto=cuerpo.style.display!=='none';
  cuerpo.style.display=abierto?'none':'block';
  icono.className='fa-solid fa-chevron-'+(abierto?'down':'up');
  if(!abierto&&!consumoMensualCargado)cargarConsumoMensual();
}

async function cargarConsumoMensual(){
  var pais=document.getElementById('filtroPais').value||'';
  var anio=document.getElementById('filtroAnio').value||'';
  var url='/api/consumo-mensual?';
  if(pais)url+='pais='+pais+'&';
  if(anio)url+='anio='+anio;
  var tbody=document.getElementById('cuerpoTablaConsumoMensual');
  tbody.innerHTML='<tr><td colspan="8" class="text-center text-muted py-3">Cargando...</td></tr>';
  try{
    var r=await fetch(url);var d=await r.json();
    datosConsumoMensual=d.meses||[];
    consumoMensualCargado=true;
    renderConsumoMensual(d);
  }catch(e){
    tbody.innerHTML='<tr><td colspan="8" class="text-center text-danger py-3">Error cargando el consumo mensual</td></tr>';
  }
}

function renderConsumoMensual(d){
  var tbody=document.getElementById('cuerpoTablaConsumoMensual');
  var resumen=document.getElementById('resumenMultiCups');
  var meses=d.meses||[];
  if(meses.length===0){
    tbody.innerHTML='<tr><td colspan="8" class="text-center text-muted py-3">Sin datos para el filtro actual</td></tr>';
    resumen.textContent='';
    return;
  }
  resumen.textContent=d.meses_multi_cups>0
    ?(d.meses_multi_cups+' mes'+(d.meses_multi_cups!==1?'es':'')+' con varios CUPS')
    :'';
  tbody.innerHTML=meses.map(function(m,i){
    var badgeCups=m.multi_cups
      ?'<span class="badge bg-info text-dark" title="Varios puntos de suministro: el consumo mostrado es la suma">'+m.n_cups+'</span>'
      :'<span class="text-muted">'+m.n_cups+'</span>';
    var fila='<tr>'
      +'<td><span class="badge" style="background:#e8eef7;color:var(--primary);">'+m.pais+'</span></td>'
      +'<td>'+m.sede+'</td>'
      +'<td>'+m.mes+'</td>'
      +'<td class="text-center">'+m.n_facturas+'</td>'
      +'<td class="text-center">'+badgeCups+'</td>'
      +'<td class="text-end fw-bold">'+m.consumo_kwh.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'</td>'
      +'<td class="text-end" style="color:var(--primary);">'+m.emisiones_tco2e.toFixed(4)+'</td>'
      +'<td class="text-end"><button class="btn btn-sm btn-link py-0 px-1" onclick="toggleDetalleCups('+i+')">'
      +'<i class="fa-solid fa-list-ul"></i></button></td>'
      +'</tr>';
    // Filas de desglose: muestran que factura aporta cada kWh del total.
    var detalle=m.detalle.map(function(f){
      return '<tr class="detalle-cups-'+i+' table-light" style="display:none;font-size:.8rem;">'
        +'<td></td><td colspan="2" class="text-muted">'+(f.cups||'(sin CUPS)')+'</td>'
        +'<td colspan="2" class="text-muted text-truncate" style="max-width:220px;" title="'+(f.archivo_nombre||'')+'">'
        +(f.periodo_inicio||'?')+' &rarr; '+(f.periodo_fin||'?')+'</td>'
        +'<td class="text-end">'+((f.consumo_kwh||0).toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2}))+'</td>'
        +'<td class="text-end">'+((f.emisiones_tco2e||0).toFixed(4))+'</td>'
        +'<td class="text-muted small text-truncate" style="max-width:140px;" title="'+(f.sociedad||'')+'">'+(f.sociedad||'')+'</td>'
        +'</tr>';
    }).join('');
    return fila+detalle;
  }).join('');
}

function toggleDetalleCups(i){
  var filas=document.querySelectorAll('.detalle-cups-'+i);
  for(var k=0;k<filas.length;k++){
    filas[k].style.display=filas[k].style.display==='none'?'table-row':'none';
  }
}

async function eliminarFactura(id){
  if(!confirm('Eliminar este registro? Esta accion no se puede deshacer.'))return;
  try{
    var r=await fetch('/api/factura/'+id,{method:'DELETE'});var d=await r.json();
    if(d.exito){toast('Registro eliminado','success');cargarHistorial(paginaActual);cargarEstadisticas();}
    else{toast('Error: '+d.error,'danger');}
  }catch(e){toast('Error de red','danger');}
}

async function descargarExcel(){
  var pais=document.getElementById('filtroPais').value||'';
  var anio=document.getElementById('filtroAnio').value||'';
  var url='/api/descargar-excel?';
  if(pais)url+='pais='+pais+'&';
  if(anio)url+='anio='+anio+'&';
  try{
    var resp=await fetch(url);
    if(!resp.ok){var err=await resp.json().catch(function(){return{};});toast('Error: '+(err.error||'No se pudo generar'),'danger');return;}
    var blob=await resp.blob();
    var a=document.createElement('a');a.href=URL.createObjectURL(blob);
    a.download='facturas_HC_'+new Date().toISOString().slice(0,10)+'.xlsx';a.click();
    URL.revokeObjectURL(a.href);
  }catch(e){toast('Error: '+e.message,'danger');}
}
