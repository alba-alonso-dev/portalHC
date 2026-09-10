/* Portal de Datos Ambientales Hiberus - modulo: dashboard ESG (KPIs y graficos) */
var _chartEvolucion = null;
var _chartPais = null;

async function cargarDashboard(){
  var anio = document.getElementById('dash-anio').value || new Date().getFullYear();
  var pais  = document.getElementById('dash-pais').value || '';
  document.getElementById('dash-anio').value = anio;
  document.getElementById('dash-ultima-act').textContent = 'Actualizado: '+new Date().toLocaleTimeString('es-ES');

  var qs = '?anio='+anio+(pais?'&pais='+pais:'');
  try{
    var [rResumen, rFact, rCal, rEvo, rEmis] = await Promise.all([
      fetch('/api/dashboard/resumen'+qs).then(function(r){return r.json();}),
      fetch('/api/dashboard/facturacion'+qs).then(function(r){return r.json();}),
      fetch('/api/dashboard/calidad'+qs).then(function(r){return r.json();}),
      fetch('/api/dashboard/evolucion'+qs).then(function(r){return r.json();}),
      fetch('/api/dashboard/emisiones'+qs).then(function(r){return r.json();}),
    ]);
    if(rResumen.exito) _renderResumen(rResumen);
    if(rFact.exito)    _renderFacturacion(rFact);
    if(rCal.exito)     _renderCalidad(rCal);
    if(rEmis.exito){
      window._dashEmisionesPais = rEmis.por_pais||[];
      _renderTopEmisores(rEmis.por_sede||[], rEmis.total_tco2e||0);
      _renderScopeChart(rEmis.por_scope||[]);
    }
    if(rEvo.exito)     _renderEvolucion(rEvo);
    // Cargar sedes usando cobertura
    var rCob = await fetch('/api/dashboard/cobertura'+qs).then(function(r){return r.json();});
    if(rCob.exito) _renderSedes(rCob);
  }catch(e){console.error('Error cargando dashboard ESG:',e);}
}

function _renderResumen(d){
  var emis = (d.emisiones_tco2e||0).toFixed(2);
  document.getElementById('dash-kpi-emisiones').textContent = emis+' t';
  var vp = d.variacion_emisiones_pct;
  var vpTxt = vp!=null ? (vp>0?'+':'')+vp+'%' : 'N/D';
  document.getElementById('dash-kpi-variacion').textContent = vpTxt;
  // Semáforo: rojo si emisiones suben, verde si bajan
  var card = document.getElementById('dash-kpi-variacion-card');
  var icon = document.getElementById('dash-variacion-icon');
  if(card && vp!=null){
    if(vp > 0){
      card.className='kpi-card red'; icon.className='fa-solid fa-arrow-trend-up me-1';
    } else if(vp < 0){
      card.className='kpi-card green'; icon.className='fa-solid fa-arrow-trend-down me-1';
    } else {
      card.className='kpi-card gray'; icon.className='fa-solid fa-minus me-1';
    }
  }
  document.getElementById('dash-kpi-facturas').textContent = d.n_facturas||0;
  document.getElementById('dash-kpi-sedes').textContent = d.n_sedes||0;
  if(document.getElementById('dash-kpi-paises')) document.getElementById('dash-kpi-paises').textContent = d.n_paises||0;

  var cob = d.cobertura||{};
  document.getElementById('dash-kpi-pct-real').textContent = (cob.pct_real||0)+'%';
  document.getElementById('dash-kpi-pct-est').textContent  = (cob.pct_estimado||0)+'%';
  document.getElementById('dash-kpi-pct-gap').textContent  = (cob.pct_faltante||0)+'%';
  document.getElementById('dash-kpi-sedes-pend').textContent = d.sedes_pendientes||0;

  var pr=cob.pct_real||0, pe=cob.pct_estimado||0, pg=cob.pct_faltante||0;
  document.getElementById('dash-bar-real').style.width=pr+'%';
  document.getElementById('dash-pct-real-bar').textContent=pr>8?pr+'% Real':'';
  document.getElementById('dash-bar-est').style.width=pe+'%';
  document.getElementById('dash-pct-est-bar').textContent=pe>8?pe+'% Est':'';
  document.getElementById('dash-bar-gap').style.width=pg+'%';
  document.getElementById('dash-pct-gap-bar').textContent=pg>8?pg+'% Gap':'';

  // Badge alertas críticas en tab
  var alCrit = (d.alertas||{}).critica||0;
  var badge = document.getElementById('badge-alertas-criticas');
  if(badge){ badge.textContent=alCrit; badge.style.display=alCrit>0?'':'none'; }
}

function _renderFacturacion(d){
  document.getElementById('dash-fact-revisadas').textContent = d.revisadas||0;
  document.getElementById('dash-fact-pendientes').textContent = d.pendientes_revision||0;
  document.getElementById('dash-fact-duplic').textContent = d.duplicados_detectados||0;
  document.getElementById('dash-fact-total').textContent = d.total||0;
}

function _renderCalidad(d){
  document.getElementById('dash-cal-ocr').textContent = d.facturas_ocr_bajo||0;
  document.getElementById('dash-cal-anomalos').textContent = d.consumos_anomalos||0;
  document.getElementById('dash-cal-score').textContent = (d.score_calidad_global||0)+'%';
  var ocrEl = document.getElementById('dash-cal-ocr-media');
  if(ocrEl){
    var ocr = d.confianza_ocr_media;
    if(ocr!=null){
      var pct = Math.round(ocr*100);
      var color = pct>=90?'text-success':pct>=70?'text-warning':'text-danger';
      ocrEl.innerHTML='<span class="'+color+'">'+(ocr.toFixed(3))+' ('+pct+'%)</span>';
    } else { ocrEl.textContent='N/D'; }
  }
}

function _renderEvolucion(d){
  var labels = d.serie.map(function(s){return s.mes;});
  var real    = d.serie.map(function(s){return s.real||0;});
  var est     = d.serie.map(function(s){return s.estimado||0;});
  var ant     = d.serie.map(function(s){return s.anio_anterior||0;});
  var ctx = document.getElementById('chart-evolucion').getContext('2d');
  if(_chartEvolucion) _chartEvolucion.destroy();
  _chartEvolucion = new Chart(ctx,{
    type:'bar',
    data:{
      labels:labels,
      datasets:[
        {label:'Real '+d.anio, data:real, backgroundColor:'rgba(39,174,96,.7)', stack:'actual'},
        {label:'Estimado '+d.anio, data:est, backgroundColor:'rgba(243,156,18,.7)', stack:'actual'},
        {label:'Año anterior', data:ant, backgroundColor:'rgba(52,152,219,.35)',
         type:'line', borderColor:'rgba(52,152,219,.9)', borderWidth:2, fill:false, pointRadius:3},
      ]
    },
    options:{responsive:true, plugins:{legend:{position:'bottom'}},
      scales:{y:{beginAtZero:true, title:{display:true, text:'tCO₂e'}}}}
  });

  // Por país — pie chart
  if(d.serie && window._dashEmisionesPais){
    var paises = window._dashEmisionesPais;
    var ctx2 = document.getElementById('chart-por-pais').getContext('2d');
    if(_chartPais) _chartPais.destroy();
    _chartPais = new Chart(ctx2,{
      type:'doughnut',
      data:{
        labels: paises.map(function(p){return p.pais;}),
        datasets:[{data: paises.map(function(p){return p.emisiones;}),
          backgroundColor:['#1e3c72','#27ae60','#f39c12','#e74c3c','#9b59b6','#3498db']}]
      },
      options:{responsive:true, plugins:{legend:{position:'bottom'}}}
    });
  }
}

function _renderSedes(d){
  var tb = document.getElementById('dash-sedes-body');
  var sedes = d.detalle_sedes||[];
  if(!sedes.length){
    tb.innerHTML='<tr><td colspan="7" class="text-center text-muted py-3">Sin datos</td></tr>'; return;
  }

  tb.innerHTML = sedes.slice(0,20).map(function(s){
    var rowCls = s.completo?'calidad-row-ok':s.meses_faltantes>6?'calidad-row-bad':'calidad-row-warn';
    var icon   = s.completo?'<i class="fa-solid fa-check-circle text-success"></i>':
                 s.meses_faltantes>6?'<i class="fa-solid fa-times-circle text-danger"></i>':
                 '<i class="fa-solid fa-exclamation-circle text-warning"></i>';
    return '<tr class="'+rowCls+'">'
      +'<td><span class="badge" style="background:#e8eef7;color:var(--primary);">'+s.pais+'</span></td>'
      +'<td>'+s.sede+'</td>'
      +'<td class="text-center"><span class="badge bg-success">'+s.meses_reales+'</span></td>'
      +'<td class="text-center"><span class="badge bg-warning text-dark">'+s.meses_estimados+'</span></td>'
      +'<td class="text-center"><span class="badge bg-danger">'+s.meses_faltantes+'</span></td>'
      +'<td><div class="progress" style="height:10px;">'
        +'<div class="progress-bar progress-bar-real" style="width:'+s.pct_real+'%"></div>'
        +'<div class="progress-bar progress-bar-est" style="width:'+s.pct_estimado+'%"></div>'
        +'<div class="progress-bar progress-bar-gap" style="width:'+s.pct_faltante+'%"></div>'
        +'</div><small class="text-muted">'+s.pct_real+'% real</small></td>'
      +'<td class="text-center">'+icon+'</td>'
      +'</tr>';
  }).join('');
  document.getElementById('dash-cal-alertas').textContent = '—';
}

function _renderTopEmisores(sedes, totalGlobal){
  var tb = document.getElementById('dash-top-emisores-body');
  if(!tb) return;
  var top = sedes.slice(0,10);
  if(!top.length){
    tb.innerHTML='<tr><td colspan="5" class="text-center text-muted py-2">Sin datos de emisiones</td></tr>'; return;
  }
  tb.innerHTML = top.map(function(s, i){
    var pct = totalGlobal>0 ? (s.emisiones/totalGlobal*100).toFixed(1) : 0;
    var barColor = i<3?'#e74c3c':i<6?'#f39c12':'#3498db';
    // Indicador de multi-sociedad (sede con CUPS de varias sociedades)
    var nSoc = (s.sociedades && s.sociedades.length) || 0;
    var multiBadge = s.multi_sociedad
      ? ' <span class="badge bg-info text-dark ms-1" title="'+nSoc+' sociedades en esta sede">⊕'+nSoc+'</span>'
      : (nSoc===1 ? ' <span class="badge bg-secondary ms-1" title="1 sociedad">1</span>' : '');
    var expandBtn = nSoc>0
      ? '<button class="btn btn-sm btn-link p-0 ms-1 dash-sede-expand" data-sede-key="'+s.pais+'|'+s.sede+'" title="Ver sociedades">+ sociedades</button>'
      : '';
    var row = '<tr>'
      +'<td><span class="badge" style="background:#e8eef7;color:var(--primary);">'+s.pais+'</span></td>'
      +'<td>'+s.sede+multiBadge+' '+expandBtn+'</td>'
      +'<td class="text-end fw-bold">'+s.emisiones.toFixed(2)+'</td>'
      +'<td class="text-end text-muted">'+s.consumo_mwh.toFixed(1)+'</td>'
      +'<td><div class="progress" style="height:8px;" title="'+pct+'% del total">'
        +'<div class="progress-bar" style="width:'+pct+'%;background:'+barColor+';"></div>'
        +'</div><small class="text-muted">'+pct+'%</small></td>'
      +'</tr>';
    // Fila expandible con el detalle por sociedad (oculta por defecto)
    if(nSoc>0){
      row += '<tr class="dash-sede-detalle" id="detalle-'+s.pais+'-'+s.sede.replace(/\s/g,'')+'" style="display:none;">'
        +'<td colspan="5" class="bg-light">'
        +'<table class="table table-sm mb-0">'
          +'<thead><tr>'
          +'<th>Sociedad</th>'
          +'<th class="text-end">tCO₂e</th>'
          +'<th class="text-end">MWh</th>'
          +'<th class="text-end">Facturas</th>'
          +'<th style="width:120px;">%</th>'
          +'</tr></thead><tbody>'
        + s.sociedades.map(function(soc){
            var socPct = soc.pct||0;
            return '<tr>'
              +'<td>'+soc.sociedad+(soc.cif?' <small class="text-muted">'+soc.cif+'</small>':'')+'</td>'
              +'<td class="text-end">'+(soc.emisiones||0).toFixed(2)+'</td>'
              +'<td class="text-end">'+(soc.mwh||soc.consumo_mwh||0).toFixed(1)+'</td>'
              +'<td class="text-end">'+(soc.n_facturas||0)+'</td>'
              +'<td><div class="progress" style="height:8px;"><div class="progress-bar" style="width:'+socPct+'%;background:#8e44ad;"></div></div><small class="text-muted">'+socPct+'%</small></td>'
              +'</tr>';
          }).join('')
        +'</tbody></table>'
        +'</td></tr>';
    }
    return row;
  }).join('');
  // Asignar handler de expandir/contraer
  var btns = tb.querySelectorAll('.dash-sede-expand');
  btns.forEach(function(btn){
    btn.addEventListener('click', function(){
      var key = btn.getAttribute('data-sede-key');
      var parts = key.split('|');
      var detalleId = 'detalle-'+parts[0]+'-'+parts[1].replace(/\s/g,'');
      var el = document.getElementById(detalleId);
      if(el){
        if(el.style.display==='none'){
          el.style.display='';
          btn.textContent='– ocultar';
        } else {
          el.style.display='none';
          btn.textContent='+ sociedades';
        }
      }
    });
  });
}

var _chartScope = null;
function _renderScopeChart(scopes){
  var ctx = document.getElementById('chart-scope');
  var noDataEl = document.getElementById('dash-scope-sin-datos');
  if(!ctx) return;
  var valid = scopes.filter(function(s){return s.emisiones>0;});
  if(!valid.length){
    ctx.style.display='none';
    if(noDataEl) noDataEl.style.display='';
    return;
  }
  ctx.style.display='';
  if(noDataEl) noDataEl.style.display='none';
  if(_chartScope) _chartScope.destroy();
  var labels = valid.map(function(s){return s.label||('Scope '+s.scope);});
  var vals = valid.map(function(s){return s.emisiones;});
  var colors = valid.map(function(s){
    return s.scope==1?'rgba(192,57,43,.8)':s.scope==2?'rgba(41,128,185,.8)':'rgba(39,174,96,.8)';
  });
  _chartScope = new Chart(ctx.getContext('2d'),{
    type:'doughnut',
    data:{labels:labels, datasets:[{data:vals, backgroundColor:colors, borderWidth:2}]},
    options:{responsive:true, plugins:{legend:{position:'bottom',labels:{font:{size:11}}},
      tooltip:{callbacks:{label:function(ctx){return ctx.label+': '+ctx.parsed.toFixed(2)+' tCO₂e';}}}}}
  });
}
