/* Portal de Datos Ambientales Hiberus - modulo: core (estado global, navegacion, notificaciones) */
var archivosSeleccionados=[];
var loteIdActual=null;
var pollingInterval=null;
var colaRevision=[];
// Todos los resultados OK del ultimo lote, requieran revision o no: permite
// abrir la revision a demanda aunque la extraccion fuese de alta confianza.
var resultadosLote=[];
var revisionActual=null;
var paginaActual=1;
var POR_PAGINA=50;

var SEDES={
  "AR":["Buenos Aires"],
  "CL":["Santiago"],
  "CO":["Bogota"],
  "EC":["Guayaquil","Quito"],
  "MX":["Queretaro"],
  "ES":["Almeria","Asturias","Barcelona","Bilbao","Granada","Lleida","Logrono","Madrid","Pamplona","Santander","Valencia","Valladolid","Vitoria","Zaragoza"]
};

function switchTab(tab){
  var allTabs=['carga','historial','factores','recalculo','estimaciones','dashboard','alertas','ghg','admin'];
  allTabs.forEach(function(t){
    var el=document.getElementById('tab-'+t);
    var btn=document.getElementById('tab-'+t+'-btn');
    if(el) el.style.display=(t===tab?'':'none');
    if(btn) btn.classList.toggle('active',t===tab);
  });
  if(tab==='historial'){cargarEstadisticas();cargarHistorial();}
  if(tab==='factores'){cargarFactores();cargarFuentes();}
  if(tab==='recalculo'){cargarHistorialRecalculos();}
  if(tab==='estimaciones'){cargarEstimaciones();detectarGaps();}
  if(tab==='dashboard'){cargarDashboard();}
  if(tab==='alertas'){cargarResumenAlertas();cargarAlertas();}
  if(tab==='ghg'){document.getElementById('ghg-anio').value=document.getElementById('ghg-anio').value||new Date().getFullYear();}
  if(tab==='admin' && typeof adminInit==='function'){adminInit();}
}

function actualizarSedes(){
  var pais=document.getElementById('pais').value;
  var sel=document.getElementById('sede');
  sel.innerHTML='<option value="">-- Selecciona sede --</option>';
  (SEDES[pais]||[]).forEach(function(s){
    var o=document.createElement('option');o.value=s;o.textContent=s;sel.appendChild(o);
  });
}

function toast(msg,tipo){
  tipo=tipo||'primary';
  var el=document.getElementById('toast');
  var cols={success:'#28a745',danger:'#dc3545',warning:'#856404',primary:'#1e3c72'};
  el.style.backgroundColor=cols[tipo]||'#1e3c72';
  document.getElementById('toastMsg').textContent=msg;
  bootstrap.Toast.getOrCreateInstance(el,{delay:3500}).show();
}

function mostrarAlerta(msg,tipo){
  var div=document.createElement('div');
  div.className='alert alert-'+tipo+' alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3';
  div.style.zIndex='9999';
  div.style.minWidth='320px';
  div.innerHTML=msg+'<button type="button" class="btn-close" data-bs-dismiss="alert"></button>';
  document.body.appendChild(div);
  setTimeout(function(){div.remove();},4000);
}
