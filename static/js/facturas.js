/* Portal de Datos Ambientales Hiberus - modulo: facturas (carga, lote, progreso, revision OCR) */
function agregarArchivos(files){
  for(var i=0;i<files.length;i++){
    var f=files[i];
    if(f.name.toLowerCase().endsWith('.pdf')&&!archivosSeleccionados.find(function(a){return a.nombre===f.name;})){
      archivosSeleccionados.push({file:f,nombre:f.name});
    }
  }
  renderListaArchivos();
}

function eliminarArchivo(i){
  archivosSeleccionados.splice(i,1);
  renderListaArchivos();
}

// Vacía toda la lista de archivos seleccionados de golpe. Útil cuando se han
// arrastrado muchos PDFs por error o se quiere empezar de cero sin ir
// borrando uno a uno.
function limpiarListaArchivos(){
  if(archivosSeleccionados.length===0)return;
  archivosSeleccionados=[];
  renderListaArchivos();
}

function renderListaArchivos(){
  var contenedor=document.getElementById('listaArchivos');
  var btn=document.getElementById('btnProcesar');
  var btnLimpiar=document.getElementById('btnLimpiarLista');
  if(archivosSeleccionados.length===0){
    contenedor.innerHTML='';btn.disabled=true;
    btn.innerHTML='<i class="fa-solid fa-bolt me-2"></i>PROCESAR FACTURAS';
    if(btnLimpiar)btnLimpiar.style.display='none';return;
  }
  if(btnLimpiar)btnLimpiar.style.display='';
  contenedor.innerHTML=archivosSeleccionados.map(function(a,i){
    return '<div class="archivo-item" id="aitem-'+i+'">'
      +'<i class="fa-solid fa-file-pdf text-danger"></i>'
      +'<span class="nombre">'+a.nombre+'</span>'
      +'<span class="tamanio">'+(a.file.size/1024/1024).toFixed(2)+' MB</span>'
      +'<button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="eliminarArchivo('+i+')">'
      +'<i class="fa-solid fa-xmark"></i></button></div>';
  }).join('');
  var n=archivosSeleccionados.length;
  btn.disabled=false;
  btn.innerHTML='<i class="fa-solid fa-bolt me-2"></i>PROCESAR '+n+' FACTURA'+(n>1?'S':'');
}

var ua=document.getElementById('uploadArea');
ua.addEventListener('dragover',function(e){e.preventDefault();ua.classList.add('drag-over');});
ua.addEventListener('dragleave',function(){ua.classList.remove('drag-over');});
ua.addEventListener('drop',function(e){e.preventDefault();ua.classList.remove('drag-over');agregarArchivos(e.dataTransfer.files);});

async function procesarFacturas(){
  var pais=document.getElementById('pais').value;
  var sede=document.getElementById('sede').value;
  if(!pais||!sede){toast('Selecciona pais y sede','warning');return;}
  if(archivosSeleccionados.length===0){toast('Selecciona al menos un PDF','warning');return;}
  document.getElementById('btnProcesar').disabled=true;
  mostrar('seccionProgreso');
  ocultar('resumenLote');
  inicializarProgreso();
  var fd=new FormData();
  fd.append('pais',pais);fd.append('sede',sede);
  // Respaldo por si la plantilla no logra leer la sociedad de la factura.
  var socManual=document.getElementById('sociedad_manual');
  if(socManual&&socManual.value.trim())fd.append('sociedad',socManual.value.trim());
  archivosSeleccionados.forEach(function(a){fd.append('archivos[]',a.file);});
  try{
    // La subida de los PDF puede tardar y hasta ahora no se anunciaba: el
    // usuario veia la pantalla quieta sin saber si habia pasado algo.
    document.getElementById('textoProgreso').textContent=
      'Subiendo '+archivosSeleccionados.length+' archivo'+(archivosSeleccionados.length>1?'s':'')+'...';
    var resp=await fetch('/api/procesar-lote',{method:'POST',body:fd});
    var data=await resp.json();
    if(!data.exito){toast('Error: '+(data.error||'desconocido'),'danger');resetUI();return;}
    loteIdActual=data.lote_id;
    document.getElementById('textoProgreso').textContent='Analizando facturas...';
    iniciarPolling();
  }catch(err){toast('Error de red: '+err.message,'danger');resetUI();}
}

function inicializarProgreso(){
  var lista=document.getElementById('listaProgreso');
  lista.innerHTML=archivosSeleccionados.map(function(a,i){
    return '<div class="progreso-archivo" id="prog-'+i+'" data-nombre="'+a.nombre+'">'
      +'<div class="d-flex justify-content-between align-items-center">'
      +'<span style="font-size:.87rem;"><i class="fa-solid fa-file-pdf text-danger me-1"></i>'+a.nombre+'</span>'
      +'<span id="est-'+i+'" class="badge bg-info text-dark"><i class="fa-solid fa-spinner fa-spin me-1"></i>Procesando</span>'
      +'</div></div>';
  }).join('');
  // finalizarLote() reescribe este titulo; si no se restaura, una segunda carga
  // arranca mostrando "Procesamiento completado" mientras aun esta procesando.
  document.getElementById('titProgreso').innerHTML=
    '<i class="fa-solid fa-spinner fa-spin me-2"></i>3. Procesando...';
  document.getElementById('barraGlobal').style.width='0%';
  document.getElementById('textoProgreso').textContent='Iniciando procesamiento...';
}

function iniciarPolling(){
  // Un lote pequeno termina en menos de 2 s, asi que con el intervalo anterior
  // la primera consulta ya lo encontraba acabado y no se veia progreso alguno:
  // la pantalla saltaba de "Iniciando" a "Completado". Se consulta de
  // inmediato y con mas frecuencia.
  var consultar=async function(){
    try{
      var resp=await fetch('/api/lote/'+loteIdActual+'/estado');
      var data=await resp.json();
      actualizarUIProgreso(data);
      if(data.estado!=='procesando'){clearInterval(pollingInterval);pollingInterval=null;finalizarLote(data);}
    }catch(e){console.error('Polling:',e);}
  };
  pollingInterval=setInterval(consultar,800);
  consultar();
}

function actualizarUIProgreso(data){
  var p=data.progreso;
  var pct=p.total>0?Math.round((p.procesados/p.total)*100):0;
  document.getElementById('barraGlobal').style.width=pct+'%';
  document.getElementById('textoProgreso').textContent=
    'Procesando '+p.procesados+' de '+p.total+' \u00b7 OK: '+p.ok+'  Errores: '+p.error;
  data.resultados.forEach(function(r){
    var idx=archivosSeleccionados.findIndex(function(a){return a.nombre===r.archivo;});
    if(idx<0)return;
    var badge=document.getElementById('est-'+idx);
    if(!badge)return;
    if(r.estado==='ok'){
      badge.className='badge '+(r.requiere_revision?'bg-warning text-dark':'bg-success');
      badge.innerHTML=r.requiere_revision?'<i class="fa-solid fa-pen-to-square me-1"></i>Revisar':'<i class="fa-solid fa-check me-1"></i>OK';
      // Una extraccion de alta confianza no abre el modal sola, pero el usuario
      // debe poder comprobarla igualmente: el badge abre su revision.
      badge.style.cursor='pointer';
      badge.title='Ver y confirmar los datos extraidos';
      badge.onclick=function(){revisarArchivo(r.archivo);};
    }else if(r.estado==='error'){
      badge.className='badge bg-danger';
      badge.innerHTML='<i class="fa-solid fa-xmark me-1"></i>Error';
      var box=document.getElementById('prog-'+idx);
      if(box&&!box.querySelector('.err-msg')){
        var pm=document.createElement('p');pm.className='err-msg text-danger mb-0 mt-1';
        pm.style.fontSize='.78rem';pm.textContent=r.error||'Error desconocido';box.appendChild(pm);
      }
    }
  });
}

function finalizarLote(data){
  var p=data.progreso;
  document.getElementById('titProgreso').innerHTML=p.error===0
    ?'<i class="fa-solid fa-circle-check text-success me-2"></i>Procesamiento completado'
    :'<i class="fa-solid fa-triangle-exclamation text-warning me-2"></i>Completado con errores';
  mostrar('resumenLote');
  var nRev=data.resultados.filter(function(r){return r.estado==='ok'&&r.requiere_revision;}).length;
  resultadosLote=data.resultados.filter(function(r){return r.estado==='ok';});
  document.getElementById('contenidoResumen').innerHTML=
    '<div class="row g-3 mb-3">'
    +'<div class="col-6 col-md-3"><div class="stat-card"><div class="number text-success">'+p.ok+'</div><div class="label">Procesadas OK</div></div></div>'
    +'<div class="col-6 col-md-3"><div class="stat-card"><div class="number text-danger">'+p.error+'</div><div class="label">Con error</div></div></div>'
    +'<div class="col-6 col-md-3"><div class="stat-card"><div class="number text-warning">'+nRev+'</div><div class="label">Pendientes revision</div></div></div>'
    +'<div class="col-6 col-md-3"><div class="stat-card"><div class="number">'+p.total+'</div><div class="label">Total facturas</div></div></div>'
    +'</div>'
    +'<div class="d-flex gap-2 flex-wrap">'
    // Antes solo se abria el modal cuando la confianza era baja, asi que una
    // factura bien extraida no habia forma de comprobarla desde aqui.
    +(resultadosLote.length
      ?'<button class="btn btn-sm btn-primary" onclick="revisarTodas()">'
       +'<i class="fa-solid fa-list-check me-1"></i>Revisar datos extraidos ('+resultadosLote.length+')</button>'
      :'')
    +'<button class="btn btn-sm btn-outline-primary" onclick="switchTab(\'historial\')"><i class="fa-solid fa-table me-1"></i>Ver historial</button>'
    +'<button class="btn btn-sm btn-outline-success" onclick="descargarExcel()"><i class="fa-solid fa-file-excel me-1"></i>Descargar Excel</button>'
    +'<button class="btn btn-sm btn-outline-secondary" onclick="resetUI()"><i class="fa-solid fa-arrow-rotate-left me-1"></i>Nueva carga</button>'
    +'</div>';
  colaRevision=data.resultados.filter(function(r){return r.estado==='ok'&&r.requiere_revision;});
  if(colaRevision.length>0)setTimeout(function(){abrirSiguienteRevision();},600);
}

// Encola todas las facturas correctas del lote para revisarlas una a una.
function revisarTodas(){
  if(!resultadosLote.length){toast('No hay facturas que revisar','warning');return;}
  colaRevision=resultadosLote.slice();
  abrirSiguienteRevision();
}

// Abre la revision de un archivo concreto sin encolar el resto.
function revisarArchivo(nombre){
  var r=resultadosLote.find(function(x){return x.archivo===nombre;});
  if(!r){toast('Esa factura ya no esta disponible para revisar','warning');return;}
  colaRevision=[r];
  abrirSiguienteRevision();
}

function resetUI(){
  archivosSeleccionados=[];loteIdActual=null;colaRevision=[];resultadosLote=[];
  renderListaArchivos();
  ocultar('seccionProgreso');
  ocultar('resumenLote');
  document.getElementById('listaProgreso').innerHTML='';
  document.getElementById('btnProcesar').disabled=false;
}

var modalRevision=null;

// #seccionProgreso y #resumenLote se ocultan desde app.css con una REGLA CSS,
// no con estilo en linea. Poner style.display='' solo borra el estilo en linea
// y el elemento vuelve a caer en la regla display:none, asi que seguia
// invisible: no se veia el progreso de la carga ni el resumen final con el
// boton de revisar. Hay que fijar un valor explicito que gane a la regla.
function mostrar(id){ var el=document.getElementById(id); if(el) el.style.display='block'; }
function ocultar(id){ var el=document.getElementById(id); if(el) el.style.display='none'; }

// Formatea un número para la UI, distinguiendo "no extraído" (—) de cero: un
// consumo de 0 y un consumo que no se pudo leer no son lo mismo y no deben
// pintarse igual, que es lo que hacía el antiguo '(r.consumo_kwh || 0)'.
function fmtNum(v, dec) {
    if (v === null || v === undefined || v === '') return '—';
    var n = Number(v);
    if (isNaN(n)) return '—';
    return n.toLocaleString('es-ES', {maximumFractionDigits: dec === undefined ? 3 : dec});
}

function abrirSiguienteRevision() {
    if (colaRevision.length === 0) return;
    revisionActual = colaRevision.shift();
    var r = revisionActual.resumen;
    var conf = r.confianza_por_campo || {};
    var campos_rev = revisionActual.campos_a_revisar || [];
    // QW8: orden de campos por impacto en la confianza global (calculado en backend).
    // Fallback al orden anterior si el backend aún no lo envía (compatibilidad).
    var orden = r.campos_ordenados_por_impacto || ['consumo', 'periodo', 'cups', 'sociedad', 'comercializadora', 'fecha_factura', 'direccion', 'sede'];
    document.getElementById('modalInfo').textContent = 'Archivo: ' + revisionActual.archivo + '  (quedan ' + colaRevision.length + ' mas)';
    function fc(label, id, valor, c, bajo) {
        var pct = Math.round((c || 0) * 100);
        var col = pct >= 80 ? 'success' : pct >= 60 ? 'warning' : 'danger';
        var cls = bajo ? 'low' : 'ok';
        return '<div class="field-revision ' + cls + '" id="' + id + '_wrap">'
            + '<div class="d-flex justify-content-between align-items-center mb-1">'
            + '<label class="form-label mb-0 fw-semibold" style="font-size:.85rem;">' + label + '</label>'
            + '<span class="badge bg-' + col + '" id="' + id + '_badge" style="font-size:.7rem;">' + pct + '% confianza</span>'
            + '</div>'
            + '<input type="text" class="form-control form-control-sm" id="' + id + '" value="' + (valor || '') + '"></div>';
    }
    // Bloques editables indexados por campo de confianza; se insertan en el
    // orden de impacto que envía el backend.
    var campos = {
        periodo: fc('Periodo inicio', 'rev_pi', r.periodo_inicio, conf.periodo, campos_rev.includes('periodo'))
            + fc('Periodo fin', 'rev_pf', r.periodo_fin, conf.periodo, campos_rev.includes('periodo'))
            + fc('Dias facturados', 'rev_dias', r.dias_facturados, conf.periodo, false),
        fecha_factura: fc('Fecha factura', 'rev_ff', r.fecha_factura, conf.fecha_factura, campos_rev.includes('fecha_factura')),
        sociedad: fc('Sociedad', 'rev_soc', r.sociedad, conf.sociedad, campos_rev.includes('sociedad')),
        direccion: fc('Direccion suministro', 'rev_dir', r.direccion_suministro, conf.direccion, campos_rev.includes('direccion'))
    };
    var hayDudosos = campos_rev.length > 0;
    var html = hayDudosos
        ? '<p class="text-muted mb-3" style="font-size:.85rem;">Los campos en amarillo tienen baja confianza. Se muestran primero los que más afectan a la confianza global. Corrige si es necesario antes de guardar.</p>'
        : '<p class="text-success mb-3" style="font-size:.85rem;"><i class="fa-solid fa-circle-check me-1"></i>'
          + 'Todos los campos se extrajeron con alta confianza. Revísalos contra el PDF y corrige lo que no cuadre.</p>';
    html += '<p class="text-muted mb-2" style="font-size:.8rem;"><i class="fa-solid fa-id-card me-1"></i>Identificación del suministro</p>';
    orden.forEach(function (campo) {
        if (campos[campo]) { html += campos[campo]; delete campos[campo]; }
    });
    // Fallback de seguridad: cualquier campo editable no cubierto por 'orden'
    Object.keys(campos).forEach(function (k) { html += campos[k]; });

    // Consumo y cálculo de emisiones. Va en su propio bloque y no mezclado con
    // los datos del contrato porque es lo ÚNICO de esta pantalla que entra en
    // el cálculo: si el consumo está mal, la huella está mal. Antes solo se
    // mostraba como una línea gris de solo lectura al final, debajo de datos
    // que no afectan al resultado, y no se podía corregir.
    html += '<hr><p class="text-muted mb-2" style="font-size:.8rem;">'
        + '<i class="fa-solid fa-calculator me-1"></i>Consumo y cálculo de emisiones '
        + '<span class="text-danger fw-semibold">(sí afecta al resultado)</span></p>';
    html += fc('Consumo (kWh)', 'rev_kwh', r.consumo_kwh, conf.consumo, campos_rev.includes('consumo'));

    // Trazabilidad del cálculo: de dónde sale el número publicado. Es solo
    // lectura — el factor lo fija el catálogo oficial por país y año, no el
    // usuario; lo corregible es el consumo, y las emisiones se recalculan
    // en el servidor al guardar.
    var factor = r.factor_kg_co2_mwh;
    html += '<div class="p-2 mb-2 rounded" style="background:#f8f9fa;font-size:.8rem;">'
        + '<div class="d-flex justify-content-between"><span class="text-muted">Consumo</span>'
        + '<span>' + fmtNum(r.consumo_mwh) + ' MWh</span></div>'
        + '<div class="d-flex justify-content-between"><span class="text-muted">× Factor de emisión'
        + (r.anio_factor ? ' (' + r.anio_factor + ')' : '') + '</span>'
        + '<span>' + fmtNum(factor) + ' kg CO2e/MWh</span></div>'
        + '<div class="d-flex justify-content-between border-top mt-1 pt-1 fw-semibold">'
        + '<span>= Emisiones</span><span>' + fmtNum(r.emisiones_tco2e) + ' tCO2e</span></div>'
        + (r.fuente_factor ? '<div class="text-muted mt-1" style="font-size:.72rem;">Fuente: '
            + r.fuente_factor + '</div>' : '')
        + '<div class="text-muted mt-1" style="font-size:.72rem;">'
        + 'Si corriges el consumo, las emisiones se recalculan al guardar.</div>'
        + '</div>';

    // Datos comerciales/tecnicos. Solo se pintan los que la plantilla declara:
    // mostrar una caja de 'Potencia contratada' en una factura que no la trae
    // invita a rellenarla a mano con un dato inventado.
    var aplicables = r.campos_aplicables || [];
    var comerciales = [
        ['importe',       'Importe' + (r.moneda ? ' (' + r.moneda + ')' : ''), 'rev_imp',  r.importe_total],
        ['tarifa',        'Tarifa / peaje de acceso',                          'rev_tar',  r.tarifa],
        ['potencia',      'Potencia contratada (kW)',                          'rev_pot',  r.potencia_kw],
        ['contrato',      'Referencia de contrato',                            'rev_con',  r.contrato],
        ['distribuidora', 'Distribuidora',                                     'rev_dis',  r.distribuidora]
    ].filter(function (c) { return aplicables.indexOf(c[0]) !== -1; });

    if (comerciales.length) {
        html += '<hr><p class="text-muted mb-2" style="font-size:.8rem;">'
            + '<i class="fa-solid fa-file-invoice me-1"></i>Datos del contrato '
            + '<span class="text-secondary">(no afectan al calculo de emisiones)</span></p>';
        comerciales.forEach(function (c) {
            html += fc(c[1], c[2], c[3], conf[c[0]], campos_rev.includes(c[0]));
        });
    }

    // La antigua línea 'Consumo / Emisiones' de solo lectura que había aquí se
    // ha sustituido por el bloque de cálculo de arriba, que además es editable.
    document.getElementById('modalBody').innerHTML = html;

    // El % de confianza describe lo fiable que es la LECTURA AUTOMÁTICA. En
    // cuanto alguien teclea sobre el campo esa cifra ya no aplica: el valor lo
    // pone una persona que está viendo el PDF al lado. El badge lo refleja al
    // instante para que se vea qué se está dando por bueno, y el servidor sube
    // esos campos a 100% al guardar.
    marcarVerificadoAlEditar();

    
    // Cargar PDF en el visor (si existe la factura_id)
    if (revisionActual.factura_id) {
        document.getElementById('pdfViewer').src = '/api/factura/' + revisionActual.factura_id + '/pdf';
    }
    
    // Si init.js no llego a instanciar el modal (p.ej. un error previo en el
    // arranque), antes esto no hacia nada y el usuario se quedaba mirando una
    // pantalla que no reaccionaba, sin ningun error visible. Se instancia aqui
    // como ultimo recurso y, si tampoco es posible, se avisa.
    if (!modalRevision && window.bootstrap) {
        var el = document.getElementById('modalRevision');
        if (el) modalRevision = new bootstrap.Modal(el);
    }
    if (modalRevision) {
        modalRevision.show();
    } else {
        console.error('No se pudo instanciar el modal de revision');
        toast('No se pudo abrir la ventana de revision', 'danger');
    }
}

function marcarVerificadoAlEditar() {
    var cont = document.getElementById('modalBody');
    if (!cont || !cont.querySelectorAll) return;
    cont.querySelectorAll('input[id^="rev_"]').forEach(function (input) {
        var original = input.value;
        var badge = document.getElementById(input.id + '_badge');
        var wrap = document.getElementById(input.id + '_wrap');
        if (!badge) return;
        var etiquetaOriginal = badge.textContent;
        var claseOriginal = badge.className;
        input.addEventListener('input', function () {
            // Si se deshace la edición y el valor vuelve al extraído, se
            // restaura el % original: el servidor tampoco lo marcaría como
            // corregido, y el badge no debe prometer algo distinto.
            var editado = input.value !== original;
            badge.textContent = editado ? 'Verificado manualmente' : etiquetaOriginal;
            badge.className = editado
                ? 'badge bg-primary'
                : claseOriginal;
            badge.style.fontSize = '.7rem';
            if (wrap) wrap.classList.toggle('low', !editado && wrap.dataset.bajo === '1');
        });
        if (wrap && wrap.classList.contains('low')) wrap.dataset.bajo = '1';
    });
}

function togglePdfViewer(){
  var panel=document.getElementById('modalPdfPanel');
  var formPanel=document.getElementById('modalFormPanel');
  var btn=document.getElementById('btnTogglePdf');
  var visible=panel.style.display!=='none';
  if(visible){
    panel.style.display='none';
    formPanel.style.maxWidth='100%';formPanel.style.flex='1';
    btn.classList.remove('btn-light');btn.classList.add('btn-outline-light');
  } else {
    panel.style.display='flex';
    formPanel.style.maxWidth='500px';formPanel.style.flex='0 0 420px';
    btn.classList.remove('btn-outline-light');btn.classList.add('btn-light');
  }
}

async function confirmarRevision(){
  if(!revisionActual)return;
  // Los campos comerciales solo existen en el DOM si la plantilla los declara,
  // asi que se leen de forma defensiva y se omiten del payload si no estan.
  function val(id){ var el=document.getElementById(id); return el && el.value!=='' ? el.value : null; }
  function num(id){ var v=val(id); if(v===null) return null; var n=parseFloat(String(v).replace(',','.')); return isNaN(n)?null:n; }

  var payload={
    periodo_inicio:document.getElementById('rev_pi').value||null,
    periodo_fin:document.getElementById('rev_pf').value||null,
    dias_facturados:parseInt(document.getElementById('rev_dias').value)||null,
    fecha_factura:document.getElementById('rev_ff').value||null,
    sociedad:document.getElementById('rev_soc').value||null,
    direccion_suministro:document.getElementById('rev_dir').value||null,
    // El servidor recalcula consumo_mwh y emisiones_tco2e a partir de esto.
    consumo_kwh:num('rev_kwh'),
    importe_total:num('rev_imp'),
    potencia_kw:num('rev_pot'),
    tarifa:val('rev_tar'),
    contrato:val('rev_con'),
    distribuidora:val('rev_dis')
  };
  var facturaId=revisionActual.factura_id;
  try{
    var resp=await fetch('/api/factura/'+facturaId+'/confirmar',
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var data=await resp.json();
    var msg=data.exito?'Datos guardados correctamente'
                      :'Error: '+(data.error||(data.errores||[]).join('; '));
    toast(msg,data.exito?'success':'danger');
    if(data.exito){marcarFacturaRevisada(facturaId,true);}
  }catch(e){toast('Error de red','danger');}
  if(modalRevision)modalRevision.hide();
  revisionActual=null;
  if(colaRevision.length>0)setTimeout(function(){abrirSiguienteRevision();},400);
}

function saltarRevision(){
  if(modalRevision)modalRevision.hide();
  // Una factura omitida sale de la cola de pendientes: ya no está "pendiente
  // de revisar" en esta sesión, aunque en BD siga como pendiente_revision.
  // Actualizamos el badge a "Revisada" para que el contador baje y no
  // quede ahí eternamente marcada.
  if(revisionActual&&revisionActual.factura_id){
    marcarFacturaRevisada(revisionActual.factura_id,false);
  }
  revisionActual=null;
  if(colaRevision.length>0)setTimeout(function(){abrirSiguienteRevision();},400);
}

// Actualiza el badge de una factura en la lista de progreso (de "Revisar" a
// "Revisada ✓") y decrementa el contador de "Pendientes revision" del
// resumen del lote. Sin esto, el resumen se queda congelado con el número
// inicial aunque el usuario ya haya revisado todas las facturas.
//   facturaId : id de la factura revisada
//   confirmada: true si se confirmó y guardó, false si se omitió
function marcarFacturaRevisada(facturaId,confirmada){
  // 1) Actualizar el badge en la lista de progreso.
  //    Buscamos el archivo por factura_id en resultadosLote (no dependemos
  //    de revisionActual, que puede ya ser null según dónde se llame).
  var r=resultadosLote.find(function(x){return x.factura_id===facturaId;});
  var idx=r?archivosSeleccionados.findIndex(function(a){return a.nombre===r.archivo;}):-1;
  if(idx>=0){
    var badge=document.getElementById('est-'+idx);
    if(badge){
      badge.className='badge '+(confirmada?'bg-success':'bg-secondary');
      badge.innerHTML=confirmada
        ?'<i class="fa-solid fa-check me-1"></i>Revisada'
        :'<i class="fa-solid fa-forward-step me-1"></i>Omitida';
      badge.onclick=null;
      badge.title=confirmada?'Factura revisada y confirmada':'Factura omitida en la revisión';
    }
  }

  // 2) Actualizar el resumen del lote (contador de pendientes)
  var elPendientes=document.querySelector('#contenidoResumen .number.text-warning');
  if(elPendientes){
    var n=parseInt(elPendientes.textContent)||0;
    if(n>0){elPendientes.textContent=n-1;}
  }

  // 3) Actualizar resultadosLote para que refleje el estado
  var item=resultadosLote.find(function(x){return x.factura_id===facturaId;});
  if(item){item.revisada=true;item.confirmada=confirmada;}
}
