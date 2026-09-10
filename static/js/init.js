/* Portal de Datos Ambientales Hiberus - modulo: bootstrap de la aplicacion */
// Arranque de la SPA: instancia los modales Bootstrap y carga datos iniciales.
// Debe cargarse el ultimo, despues de todos los modulos de feature.

window.addEventListener('DOMContentLoaded', function () {
  modalRevision       = new bootstrap.Modal(document.getElementById('modalRevision'));
  modalFactorBS       = new bootstrap.Modal(document.getElementById('modalFactor'));
  modalHistorialFactorBS = new bootstrap.Modal(document.getElementById('modalHistorialFactor'));
  modalFuenteBS       = new bootstrap.Modal(document.getElementById('modalFuente'));
  modalEstimacionBS   = new bootstrap.Modal(document.getElementById('modalEstimacion'));
});

window.addEventListener('load', function () { cargarEstadisticas(); });
