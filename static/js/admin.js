/* Portal de Datos Ambientales Hiberus - modulo: utilidades de administracion / entorno de pruebas */
function confirmarResetDatos(){
  var modal=new bootstrap.Modal(document.getElementById('modalResetDatos'));
  modal.show();
}

function ejecutarResetDatos(){
  var modal=bootstrap.Modal.getInstance(document.getElementById('modalResetDatos'));
  fetch('/api/dev/reset-datos',{method:'POST'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(modal)modal.hide();
      if(d.exito){
        mostrarAlerta('Datos de prueba eliminados correctamente.','success');
        cargarHistorial();
        cargarEstadisticas();
      } else {
        mostrarAlerta('Error: '+(d.error||'No permitido en este entorno.'),'danger');
      }
    })
    .catch(function(){
      if(modal)modal.hide();
      mostrarAlerta('Error de conexión al limpiar datos.','danger');
    });
}
