/* Portal de Datos Ambientales Hiberus - modulo: informe GHG Protocol */
async function previewGHG(){
  var anio = document.getElementById('ghg-anio').value || new Date().getFullYear();
  var pais = document.getElementById('ghg-pais').value;
  var qs = '?anio='+anio+(pais?'&pais='+pais:'');
  try{
    var r = await fetch('/api/ghg/preview'+qs).then(function(rr){return rr.json();});
    if(!r.exito){ toast('Error: '+r.error,'danger'); return; }
    var inf = r.informe;
    document.getElementById('ghg-preview').style.display='';

    // Resumen KPIs
    var resumen = inf.resumen||{};
    document.getElementById('ghg-resumen-kpis').innerHTML =
      _ghgKpi('tCO₂e Totales', (resumen.total_emisiones_tco2e||0)+' t', 'primary')
      +_ghgKpi('Consumo MWh', (resumen.total_consumo_mwh||0), 'success')
      +_ghgKpi('Facturas analizadas', resumen.n_facturas||0, 'secondary')
      +_ghgKpi('Sedes', resumen.n_sedes||0, 'info');

    // Scopes
    var sc = inf.scopes||{};
    document.getElementById('ghg-scope1-total').textContent = (sc.scope_1||{}).total_tco2e+' tCO₂e';
    document.getElementById('ghg-scope2-total').textContent = (sc.scope_2||{}).total_tco2e+' tCO₂e';
    document.getElementById('ghg-scope3-total').textContent = (sc.scope_3||{}).total_tco2e+' tCO₂e';
    ['scope_1','scope_2','scope_3'].forEach(function(k,i){
      var div = document.getElementById('ghg-scope'+[1,2,3][i]+'-detalle');
      var det = (sc[k]||{}).detalle||[];
      div.innerHTML = det.map(function(d){
        return '<div>'+d.energia+': <strong>'+d.emisiones_tco2e+'</strong> tCO₂e ('+d.n_facturas+' facturas)</div>';
      }).join('') || '<span class="text-muted">Sin datos</span>';
    });

    // Calidad
    var cal = inf.calidad||{};
    var pr=cal.pct_real||0, pe=cal.pct_estimado||0, pg=cal.pct_faltante||0;
    document.getElementById('ghg-bar-real').style.width=pr+'%';
    document.getElementById('ghg-pct-real').textContent=pr>8?pr+'% Real':'';
    document.getElementById('ghg-bar-est').style.width=pe+'%';
    document.getElementById('ghg-pct-est').textContent=pe>8?pe+'% Est':'';
    document.getElementById('ghg-bar-gap').style.width=pg+'%';
    document.getElementById('ghg-pct-gap').textContent=pg>8?pg+'% Gap':'';
    document.getElementById('ghg-calidad-detalle').innerHTML =
      '<b>'+cal.nivel_calidad+'</b><br>'
      +'Facturas reales: '+cal.facturas_reales+' | Estimadas: '+cal.facturas_estimadas
      +' | Faltantes: '+cal.periodos_faltantes+'<br>'
      +'Confianza OCR media: '+(cal.confianza_ocr_media||'N/D');

    // Trazabilidad
    var tr = inf.trazabilidad||{};
    document.getElementById('ghg-trazabilidad-detalle').innerHTML =
      'Recálculos realizados: <b>'+tr.n_recalculos+'</b><br>'
      +'Modificaciones manuales: <b>'+tr.n_modificaciones_manuales+'</b><br>'
      +'Con documento PDF: <b>'+tr.n_facturas_con_documento+' ('+tr.pct_con_documento+'%)</b><br>'
      +'Estimaciones generadas: <b>'+tr.n_estimaciones+'</b><br>'
      +'Error medio estimaciones: <b>'+(tr.error_medio_estimaciones_pct||'N/D')+'%</b>';

    // Factores metodología
    var facs = (inf.metodologia||{}).factores||[];
    document.getElementById('ghg-factores-body').innerHTML = facs.length===0
      ? '<tr><td colspan="7" class="text-center text-muted py-3">Sin datos</td></tr>'
      : facs.map(function(f){
          return '<tr><td>'+f.pais+'</td><td>'+f.tipo_energia+'</td><td>'+f.anio+'</td>'
            +'<td>'+f.factor_kg_co2_mwh+'</td><td>'+(f.fuente||'—')+'</td>'
            +'<td>Scope '+(f.scope_ghg||2)+'</td><td>'+f.n_facturas_usadas+'</td></tr>';
        }).join('');

    toast('Vista previa cargada','success');
  }catch(e){ toast('Error cargando preview GHG: '+e.message,'danger'); }
}

function _ghgKpi(label, valor, color){
  return '<div class="col-6 col-md-3"><div class="stat-card"><div class="number text-'+color+'">'
    +valor+'</div><div class="label">'+label+'</div></div></div>';
}

function descargarGHG(){
  var anio = document.getElementById('ghg-anio').value || new Date().getFullYear();
  var pais = document.getElementById('ghg-pais').value;
  var url = '/api/ghg/informe?anio='+anio+(pais?'&pais='+pais:'');
  window.open(url,'_blank');
  toast('Generando Excel GHG...','info');
}
