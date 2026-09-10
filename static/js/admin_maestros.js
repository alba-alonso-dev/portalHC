/* Portal de Datos Ambientales Hiberus - modulo: admin de datos maestros
 *
 * Gestiona CRUD sobre paises, sedes, comercializadoras, tipos_energia y suministros.
 * Las operaciones de escritura requieren ALLOW_ADMIN_MAESTROS=true en el backend;
 * si no está activo, los endpoints responden 403 y la UI lo indica en un banner.
 */

// Estado interno del módulo
var adminSubTabActual = 'paises';
var adminEntidadEditando = null;   // {tipo, id} cuando se edita
var ADMIN_HABILITADO = false;      // se actualiza al cargar la pestaña
var modalAdminBS = null;

// ── Utilidades ──────────────────────────────────────────────────────────────

function adminFetch(url, opts) {
  opts = opts || {};
  opts.headers = opts.headers || {};
  if (opts.body && typeof opts.body === 'object') {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.body);
  }
  return fetch(url, opts).then(function (r) {
    return r.json().then(function (d) {
      d._status = r.status;
      return d;
    });
  });
}

function adminIncluirInactivos() {
  var el = document.getElementById('admin-incluir-inactivos');
  return el && el.checked ? '1' : '0';
}

function adminBadge(activo) {
  if (activo) return '<span class="badge bg-success">Sí</span>';
  return '<span class="badge bg-secondary">No</span>';
}

function adminBotones(tipo, id, opts) {
  opts = opts || {};
  var html = '';
  if (opts.toggleEstado !== false) {
    html += '<button class="btn btn-sm btn-outline-secondary me-1" title="Activar/Desactivar" ' +
            'onclick="adminToggleEstado(\'' + tipo + '\',' + id + ')">' +
            '<i class="fa-solid fa-power-off"></i></button>';
  }
  html += '<button class="btn btn-sm btn-outline-primary me-1" title="Editar" ' +
          'onclick="adminEditar(\'' + tipo + '\',' + id + ')">' +
          '<i class="fa-solid fa-pen"></i></button>';
  if (opts.borrar !== false) {
    html += '<button class="btn btn-sm btn-outline-danger" title="Borrar" ' +
            'onclick="adminBorrar(\'' + tipo + '\',' + id + ')">' +
            '<i class="fa-solid fa-trash"></i></button>';
  }
  return html;
}

function adminCheckAdmin() {
  return adminFetch('/api/admin/estado').then(function (d) {
    ADMIN_HABILITADO = !!(d && d.exito && d.admin_habilitado);
    var banner = document.getElementById('admin-banner');
    if (!banner) return;
    if (ADMIN_HABILITADO) {
      banner.style.display = 'block';
      banner.className = 'alert alert-success mb-3';
      banner.innerHTML = '<i class="fa-solid fa-check-circle me-1"></i>' +
                         '<strong>Modo admin habilitado.</strong> Puedes crear, editar y borrar maestros. ' +
                         'Cada cambio queda registrado en <code>audit_log</code>.';
    } else {
      banner.style.display = 'block';
      banner.className = 'alert alert-warning mb-3';
      banner.innerHTML = '<i class="fa-solid fa-triangle-exclamation me-1"></i>' +
                         '<strong>Modo admin deshabilitado.</strong> Solo lectura. ' +
                         'Para modificar maestros, arranca con ' +
                         '<code>$env:ALLOW_ADMIN_MAESTROS="true"</code> antes de <code>app.py</code>.';
    }
  });
}

// ── Navegación de sub-tabs ─────────────────────────────────────────────────

function adminSwitchSubTab(tab) {
  adminSubTabActual = tab;
  var tabs = ['paises', 'sedes', 'sociedades', 'comercializadoras', 'tipos', 'suministros'];
  tabs.forEach(function (t) {
    var panel = document.getElementById('sub-tab-' + t + '-panel');
    var btn = document.getElementById('sub-tab-' + t + '-btn');
    if (panel) panel.style.display = (t === tab ? '' : 'none');
    if (btn) btn.classList.toggle('active', t === tab);
  });
  adminRecargar();
}

function adminRecargar() {
  if (adminSubTabActual === 'paises') adminCargarPaises();
  if (adminSubTabActual === 'sedes') adminCargarSedes();
  if (adminSubTabActual === 'sociedades') adminCargarSociedades();
  if (adminSubTabActual === 'comercializadoras') adminCargarComercializadoras();
  if (adminSubTabActual === 'tipos') adminCargarTipos();
  if (adminSubTabActual === 'suministros') adminCargarSuministros();
}

// ── Países ──────────────────────────────────────────────────────────────────

function adminCargarPaises() {
  adminFetch('/api/admin/paises?incluir_inactivos=' + adminIncluirInactivos())
    .then(function (d) {
      var tbody = document.getElementById('admin-tbody-paises');
      if (!d || !d.exito) { tbody.innerHTML = '<tr><td colspan="5">Error</td></tr>'; return; }
      var rows = d.paises || [];
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-muted text-center">Sin países</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(function (r) {
        return '<tr>' +
          '<td><code>' + esc(r.codigo) + '</code></td>' +
          '<td>' + esc(r.nombre) + '</td>' +
          '<td>' + esc(r.zona_horaria || '') + '</td>' +
          '<td class="text-center">' + adminBadge(r.activo) + '</td>' +
          '<td class="text-end">' + adminBotones('pais', r.codigo, { borrar: false }) + '</td>' +
          '</tr>';
      }).join('');
    });
}

function adminAbrirModalPais(codigo) {
  adminEntidadEditando = codigo ? { tipo: 'pais', id: codigo } : null;
  var titulo = codigo ? 'Editar país' : 'Nuevo país';
  var pais = null;
  if (codigo) {
    // Buscar el país del listado actual
    var filas = document.querySelectorAll('#admin-tbody-paises tr');
    filas.forEach(function (tr) {
      if (tr.querySelector('td code') && tr.querySelector('td code').textContent === codigo) {
        var tds = tr.querySelectorAll('td');
        pais = { codigo: codigo, nombre: tds[1].textContent, zona_horaria: tds[2].textContent };
      }
    });
  }
  var html =
    adminCampo('codigo', 'Código', pais ? pais.codigo : '', 'text', 'Ej: ES', pais ? true : false) +
    adminCampo('nombre', 'Nombre', pais ? pais.nombre : '', 'text', 'Ej: España') +
    adminCampo('zona_horaria', 'Zona horaria', pais ? pais.zona_horaria : '', 'text', 'Ej: Europe/Madrid');
  adminMostrarModal(titulo, html);
}

// ── Sedes ───────────────────────────────────────────────────────────────────

function adminCargarSedes() {
  adminFetch('/api/admin/sedes?incluir_inactivos=' + adminIncluirInactivos())
    .then(function (d) {
      var tbody = document.getElementById('admin-tbody-sedes');
      if (!d || !d.exito) { tbody.innerHTML = '<tr><td colspan="6">Error</td></tr>'; return; }
      var rows = d.sedes || [];
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-muted text-center">Sin sedes</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(function (r) {
        return '<tr>' +
          '<td>' + r.id + '</td>' +
          '<td><code>' + esc(r.pais_codigo) + '</code></td>' +
          '<td>' + esc(r.nombre) + '</td>' +
          '<td>' + esc(r.direccion || '') + '</td>' +
          '<td class="text-center">' + adminBadge(r.activo) + '</td>' +
          '<td class="text-end">' + adminBotones('sede', r.id) + '</td>' +
          '</tr>';
      }).join('');
    });
}

function adminAbrirModalSede(id) {
  adminEntidadEditando = id ? { tipo: 'sede', id: id } : null;
  var titulo = id ? 'Editar sede' : 'Nueva sede';
  var sede = null;
  if (id) {
    var filas = document.querySelectorAll('#admin-tbody-sedes tr');
    filas.forEach(function (tr) {
      if (tr.querySelector('td').textContent == id) {
        var tds = tr.querySelectorAll('td');
        sede = {
          pais_codigo: tds[1].querySelector('code').textContent,
          nombre: tds[2].textContent,
          direccion: tds[3].textContent
        };
      }
    });
  }
  var html =
    adminCampo('pais_codigo', 'País', sede ? sede.pais_codigo : '', 'text', 'Ej: ES') +
    adminCampo('nombre', 'Nombre', sede ? sede.nombre : '', 'text', 'Ej: Madrid') +
    adminCampo('direccion', 'Dirección', sede ? sede.direccion : '', 'text', 'Opcional');
  adminMostrarModal(titulo, html);
}
// ── Sociedades ───────────────────────────────────────────────────────────────

function adminCargarSociedades() {
  adminFetch('/api/admin/sociedades?incluir_inactivos=' + adminIncluirInactivos())
    .then(function (d) {
      var tbody = document.getElementById('admin-tbody-sociedades');
      if (!d || !d.exito) { tbody.innerHTML = '<tr><td colspan="6">Error</td></tr>'; return; }
      var rows = d.sociedades || [];
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-muted text-center">Sin sociedades</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(function (r) {
        return '<tr>' +
          '<td>' + r.id + '</td>' +
          '<td>' + esc(r.nombre) + '</td>' +
          '<td>' + esc(r.cif || '') + '</td>' +
          '<td><code>' + esc(r.pais_codigo || '') + '</code></td>' +
          '<td class="text-center">' + adminBadge(r.activo) + '</td>' +
          '<td class="text-end">' + adminBotones('sociedad', r.id) + '</td>' +
          '</tr>';
      }).join('');
    });
}

function adminAbrirModalSociedad(id) {
  adminEntidadEditando = id ? { tipo: 'sociedad', id: id } : null;
  var titulo = id ? 'Editar sociedad' : 'Nueva sociedad';
  var soc = null;
  if (id) {
    var filas = document.querySelectorAll('#admin-tbody-sociedades tr');
    filas.forEach(function (tr) {
      if (tr.querySelector('td').textContent == id) {
        var tds = tr.querySelectorAll('td');
        soc = {
          nombre: tds[1].textContent,
          cif: tds[2].textContent,
          pais_codigo: tds[3].querySelector('code') ? tds[3].querySelector('code').textContent : ''
        };
      }
    });
  }
  var html =
    adminCampo('nombre', 'Nombre (razón social)', soc ? soc.nombre : '', 'text', 'Ej: HIBERUS DIGITAL S.L.') +
    adminCampo('cif', 'CIF/NIF', soc ? soc.cif : '', 'text', 'Opcional') +
    adminCampo('pais_codigo', 'País', soc ? soc.pais_codigo : '', 'text', 'Ej: ES (opcional)');
  adminMostrarModal(titulo, html);
}
// ── Comercializadoras ───────────────────────────────────────────────────────

function adminCargarComercializadoras() {
  adminFetch('/api/admin/comercializadoras?incluir_inactivos=' + adminIncluirInactivos())
    .then(function (d) {
      var tbody = document.getElementById('admin-tbody-comercializadoras');
      if (!d || !d.exito) { tbody.innerHTML = '<tr><td colspan="6">Error</td></tr>'; return; }
      var rows = d.comercializadoras || [];
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-muted text-center">Sin comercializadoras</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(function (r) {
        return '<tr>' +
          '<td>' + r.id + '</td>' +
          '<td><code>' + esc(r.pais_codigo) + '</code></td>' +
          '<td>' + esc(r.nombre) + '</td>' +
          '<td>' + esc(r.tipo_energia || '') + '</td>' +
          '<td class="text-center">' + adminBadge(r.activo) + '</td>' +
          '<td class="text-end">' + adminBotones('comercializadora', r.id) + '</td>' +
          '</tr>';
      }).join('');
    });
}

function adminAbrirModalComercializadora(id) {
  adminEntidadEditando = id ? { tipo: 'comercializadora', id: id } : null;
  var titulo = id ? 'Editar comercializadora' : 'Nueva comercializadora';
  var com = null;
  if (id) {
    var filas = document.querySelectorAll('#admin-tbody-comercializadoras tr');
    filas.forEach(function (tr) {
      if (tr.querySelector('td').textContent == id) {
        var tds = tr.querySelectorAll('td');
        com = {
          pais_codigo: tds[1].querySelector('code').textContent,
          nombre: tds[2].textContent,
          tipo_energia: tds[3].textContent
        };
      }
    });
  }
  var html =
    adminCampo('pais_codigo', 'País', com ? com.pais_codigo : '', 'text', 'Ej: ES') +
    adminCampo('nombre', 'Nombre', com ? com.nombre : '', 'text', 'Ej: Endesa') +
    adminCampo('tipo_energia', 'Tipo energía', com ? com.tipo_energia : 'electricidad', 'text', 'electricidad');
  adminMostrarModal(titulo, html);
}

// ── Tipos de energía ────────────────────────────────────────────────────────

function adminCargarTipos() {
  adminFetch('/api/admin/tipos-energia?incluir_inactivos=' + adminIncluirInactivos())
    .then(function (d) {
      var tbody = document.getElementById('admin-tbody-tip');
      if (!d || !d.exito) { tbody.innerHTML = '<tr><td colspan="6">Error</td></tr>'; return; }
      var rows = d.tipos_energia || [];
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-muted text-center">Sin tipos</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(function (r) {
        return '<tr>' +
          '<td><code>' + esc(r.codigo) + '</code></td>' +
          '<td>' + esc(r.nombre) + '</td>' +
          '<td>' + esc(r.unidad_medida) + '</td>' +
          '<td>' + esc(r.unidad_emision) + '</td>' +
          '<td class="text-center">' + adminBadge(r.activo) + '</td>' +
          '<td class="text-end">' + adminBotones('tipo', r.codigo, { borrar: false }) + '</td>' +
          '</tr>';
      }).join('');
    });
}

function adminAbrirModalTipoEnergia(codigo) {
  adminEntidadEditando = codigo ? { tipo: 'tipo', id: codigo } : null;
  var titulo = codigo ? 'Editar tipo de energía' : 'Nuevo tipo de energía';
  var tipo = null;
  if (codigo) {
    var filas = document.querySelectorAll('#admin-tbody-tip tr');
    filas.forEach(function (tr) {
      var code = tr.querySelector('td code');
      if (code && code.textContent === codigo) {
        var tds = tr.querySelectorAll('td');
        tipo = {
          codigo: codigo,
          nombre: tds[1].textContent,
          unidad_medida: tds[2].textContent,
          unidad_emision: tds[3].textContent
        };
      }
    });
  }
  var html =
    adminCampo('codigo', 'Código', tipo ? tipo.codigo : '', 'text', 'Ej: gas', tipo ? true : false) +
    adminCampo('nombre', 'Nombre', tipo ? tipo.nombre : '', 'text', 'Ej: Gas Natural') +
    adminCampo('unidad_medida', 'Unidad medida', tipo ? tipo.unidad_medida : '', 'text', 'Ej: m3') +
    adminCampo('unidad_emision', 'Unidad emisión', tipo ? tipo.unidad_emision : '', 'text', 'Ej: kg CO2eq/m3');
  adminMostrarModal(titulo, html);
}

// ── Suministros ─────────────────────────────────────────────────────────────

function adminCargarSuministros() {
  adminFetch('/api/admin/suministros?incluir_inactivos=' + adminIncluirInactivos())
    .then(function (d) {
      var tbody = document.getElementById('admin-tbody-suministros');
      if (!d || !d.exito) { tbody.innerHTML = '<tr><td colspan="9">Error</td></tr>'; return; }
      var rows = d.suministros || [];
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-muted text-center">Sin suministros</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(function (r) {
        return '<tr>' +
          '<td>' + r.id + '</td>' +
          '<td><code>' + esc(r.pais_codigo || '') + '</code></td>' +
          '<td>' + esc(r.sede_nombre || '') + '</td>' +
          '<td>' + esc(r.tipo_energia || '') + '</td>' +
          '<td>' + esc(r.referencia || '') + '</td>' +
          '<td>' + esc(r.sociedad_nombre || '') + '</td>' +
          '<td>' + esc(r.notas || '') + '</td>' +
          '<td class="text-center">' + adminBadge(r.activo) + '</td>' +
          '<td class="text-end">' + adminBotones('suministro', r.id) + '</td>' +
          '</tr>';
      }).join('');
    });
}

function adminAbrirModalSuministro(id) {
  adminEntidadEditando = id ? { tipo: 'suministro', id: id } : null;
  var titulo = id ? 'Editar suministro' : 'Nuevo suministro';
  var sum = null;
  if (id) {
    var filas = document.querySelectorAll('#admin-tbody-suministros tr');
    filas.forEach(function (tr) {
      if (tr.querySelector('td').textContent == id) {
        var tds = tr.querySelectorAll('td');
        sum = {
          tipo_energia: tds[3].textContent,
          referencia: tds[4].textContent,
          sociedad_nombre: tds[5].textContent,
          notas: tds[6].textContent
        };
      }
    });
  }
  var html =
    adminCampo('sede_id', 'ID sede', sum ? sum.sede_id : '', 'number', 'ID de la sede (ver tabla)') +
    adminCampo('tipo_energia', 'Tipo energía', sum ? sum.tipo_energia : 'electricidad', 'text', 'electricidad') +
    adminCampo('referencia', 'Referencia (CUPS)', sum ? sum.referencia : '', 'text', 'Opcional') +
    adminCampoSociedad(sum ? sum.sociedad_nombre : '') +
    adminCampo('notas', 'Notas', sum ? sum.notas : '', 'text', 'Opcional');
  adminMostrarModal(titulo, html);
}

function adminCampoSociedad(sociedadNombreActual) {
  // El select de sociedad se puebla dinámicamente desde /api/admin/sociedades
  var html = '<div class="mb-3">' +
    '<label class="form-label small">Sociedad titular <small class="text-muted">(titular del CUPS)</small></label>' +
    '<select class="form-select" name="sociedad_id">' +
    '<option value="">— Sin asignar —</option>' +
    '</select>' +
    '<div class="form-text" id="admin-sociedad-actual">' +
    (sociedadNombreActual ? 'Actual: ' + esc(sociedadNombreActual) : '') +
    '</div>' +
    '</div>';
  // Poblar el select de forma asíncrona
  setTimeout(function () {
    var sel = document.querySelector('#admin-form select[name="sociedad_id"]');
    if (!sel) return;
    adminFetch('/api/admin/sociedades').then(function (d) {
      if (!d || !d.exito) return;
      var sociedades = d.sociedades || [];
      var actualId = null;
      // Si hay un nombre actual, buscar su id
      if (sociedadNombreActual) {
        for (var i = 0; i < sociedades.length; i++) {
          if (sociedades[i].nombre === sociedadNombreActual) {
            actualId = sociedades[i].id;
            break;
          }
        }
      }
      sociedades.forEach(function (s) {
        var o = document.createElement('option');
        o.value = s.id;
        o.textContent = s.nombre + (s.cif ? ' (' + s.cif + ')' : '');
        if (actualId && s.id === actualId) o.selected = true;
        sel.appendChild(o);
      });
    });
  }, 50);
  return html;
}

// ── Modal genérico ──────────────────────────────────────────────────────────

function adminCampo(name, label, valor, tipo, placeholder, readonly) {
  var ro = readonly ? ' readonly' : '';
  return '<div class="mb-3">' +
    '<label class="form-label small">' + esc(label) + '</label>' +
    '<input type="' + (tipo || 'text') + '" class="form-control" name="' + name + '" ' +
    'value="' + esc(valor || '') + '" placeholder="' + esc(placeholder || '') + '"' + ro + '>' +
    '</div>';
}

function adminMostrarModal(titulo, html) {
  if (!modalAdminBS) {
    modalAdminBS = new bootstrap.Modal(document.getElementById('modalAdminMaestro'));
  }
  document.getElementById('admin-modal-titulo').innerHTML = '<i class="fa-solid fa-pen me-2"></i>' + esc(titulo);
  document.getElementById('admin-form-campos').innerHTML = html;
  modalAdminBS.show();
}

function adminFormValues() {
  var vals = {};
  var inputs = document.querySelectorAll('#admin-form input');
  inputs.forEach(function (inp) {
    if (inp.name) vals[inp.name] = inp.value;
  });
  return vals;
}

// ── Acciones de escritura ───────────────────────────────────────────────────

function adminGuardar() {
  if (!ADMIN_HABILITADO) {
    mostrarAlerta('Modo admin deshabilitado. Establece ALLOW_ADMIN_MAESTROS=true.', 'danger');
    return;
  }
  if (!adminEntidadEditando) {
    // Crear nuevo
    adminCrear(adminSubTabActual);
  } else {
    adminActualizar(adminEntidadEditando);
  }
}

function adminCrear(tipo) {
  var vals = adminFormValues();
  var url, body;
  if (tipo === 'pais') {
    url = '/api/admin/paises';
    body = vals;
  } else if (tipo === 'sedes') {
    url = '/api/admin/sedes';
    body = vals;
  } else if (tipo === 'sociedades') {
    url = '/api/admin/sociedades';
    body = vals;
  } else if (tipo === 'comercializadoras') {
    url = '/api/admin/comercializadoras';
    body = vals;
  } else if (tipo === 'tipos') {
    url = '/api/admin/tipos-energia';
    body = vals;
  } else if (tipo === 'suministros') {
    url = '/api/admin/suministros';
    body = vals;
    var socId = vals.sociedad_id;
    if (socId) body.sociedad_id = parseInt(socId, 10);
  } else {
    return;
  }
  adminFetch(url, { method: 'POST', body: body }).then(function (d) {
    if (d && d.exito) {
      if (modalAdminBS) modalAdminBS.hide();
      mostrarAlerta('Maestro creado correctamente.', 'success');
      adminRecargar();
    } else {
      mostrarAlerta('Error: ' + (d && d.error ? d.error : 'desconocido'), 'danger');
    }
  });
}

function adminActualizar(ent) {
  var vals = adminFormValues();
  var url, body;
  if (ent.tipo === 'pais') {
    url = '/api/admin/paises/' + encodeURIComponent(ent.id);
    body = { nombre: vals.nombre, zona_horaria: vals.zona_horaria };
  } else if (ent.tipo === 'sede') {
    url = '/api/admin/sedes/' + ent.id;
    body = { nombre: vals.nombre, direccion: vals.direccion };
  } else if (ent.tipo === 'sociedad') {
    url = '/api/admin/sociedades/' + ent.id;
    body = { nombre: vals.nombre, cif: vals.cif, pais_codigo: vals.pais_codigo };
  } else if (ent.tipo === 'comercializadora') {
    url = '/api/admin/comercializadoras/' + ent.id;
    body = { nombre: vals.nombre, tipo_energia: vals.tipo_energia };
  } else if (ent.tipo === 'tipo') {
    url = '/api/admin/tipos-energia/' + encodeURIComponent(ent.id);
    body = { nombre: vals.nombre, unidad_medida: vals.unidad_medida, unidad_emision: vals.unidad_emision };
  } else if (ent.tipo === 'suministro') {
    url = '/api/admin/suministros/' + ent.id;
    body = { tipo_energia: vals.tipo_energia, referencia: vals.referencia,
             notas: vals.notas };
    var socId = vals.sociedad_id;
    if (socId) body.sociedad_id = parseInt(socId, 10);
  } else {
    return;
  }
  adminFetch(url, { method: 'PUT', body: body }).then(function (d) {
    if (d && d.exito) {
      if (modalAdminBS) modalAdminBS.hide();
      mostrarAlerta('Maestro actualizado correctamente.', 'success');
      adminRecargar();
    } else {
      mostrarAlerta('Error: ' + (d && d.error ? d.error : 'desconocido'), 'danger');
    }
  });
}

function adminToggleEstado(tipo, id) {
  if (!ADMIN_HABILITADO) {
    mostrarAlerta('Modo admin deshabilitado. Establece ALLOW_ADMIN_MAESTROS=true.', 'danger');
    return;
  }
  if (!confirm('¿Cambiar el estado (activo/inactivo)?')) return;
  var url;
  if (tipo === 'pais') url = '/api/admin/paises/' + encodeURIComponent(id) + '/estado';
  else if (tipo === 'sede') url = '/api/admin/sedes/' + id + '/estado';
  else if (tipo === 'sociedad') url = '/api/admin/sociedades/' + id + '/estado';
  else if (tipo === 'comercializadora') url = '/api/admin/comercializadoras/' + id + '/estado';
  else if (tipo === 'tipo') url = '/api/admin/tipos-energia/' + encodeURIComponent(id) + '/estado';
  else if (tipo === 'suministro') url = '/api/admin/suministros/' + id + '/estado';
  else return;
  // No conocemos el estado actual desde la fila sin parsear: togglear leyendo
  // Primero obtenemos la lista para saber el estado, luego enviamos el opuesto.
  adminFetch(url.replace('/estado', '')).then(function (d) {
    // Para paises/tipos el GET individual no existe; leemos de la lista cacheada.
    var actual = adminBuscarEnTabla(tipo, id);
    var nuevo = actual ? !actual : true;
    adminFetch(url, { method: 'PATCH', body: { activo: nuevo } }).then(function (r) {
      if (r && r.exito) {
        mostrarAlerta('Estado actualizado.', 'success');
        adminRecargar();
      } else {
        mostrarAlerta('Error: ' + (r && r.error ? r.error : 'desconocido'), 'danger');
      }
    });
  });
}

function adminBuscarEnTabla(tipo, id) {
  // Devuelve true/false del estado 'activo' o null si no se encuentra.
  var tbody;
  if (tipo === 'pais') tbody = document.getElementById('admin-tbody-paises');
  else if (tipo === 'sede') tbody = document.getElementById('admin-tbody-sedes');
  else if (tipo === 'sociedad') tbody = document.getElementById('admin-tbody-sociedades');
  else if (tipo === 'comercializadora') tbody = document.getElementById('admin-tbody-comercializadoras');
  else if (tipo === 'tipo') tbody = document.getElementById('admin-tbody-tip');
  else if (tipo === 'suministro') tbody = document.getElementById('admin-tbody-suministros');
  if (!tbody) return null;
  var filas = tbody.querySelectorAll('tr');
  for (var i = 0; i < filas.length; i++) {
    var tds = filas[i].querySelectorAll('td');
    if (!tds.length) continue;
    // El identificador está en la primera columna (id o code)
    var primer = tds[0].textContent.trim();
    var code = tds[0].querySelector('code');
    if (code) primer = code.textContent.trim();
    if (String(primer) === String(id)) {
      // El badge 'activo' está en la penúltima columna (antes de Acciones)
      var badgeTd = tds[tds.length - 2];
      return badgeTd.querySelector('.bg-success') !== null;
    }
  }
  return null;
}

function adminEditar(tipo, id) {
  if (tipo === 'pais') adminAbrirModalPais(id);
  else if (tipo === 'sede') adminAbrirModalSede(id);
  else if (tipo === 'sociedad') adminAbrirModalSociedad(id);
  else if (tipo === 'comercializadora') adminAbrirModalComercializadora(id);
  else if (tipo === 'tipo') adminAbrirModalTipoEnergia(id);
  else if (tipo === 'suministro') adminAbrirModalSuministro(id);
}

function adminBorrar(tipo, id) {
  if (!ADMIN_HABILITADO) {
    mostrarAlerta('Modo admin deshabilitado. Establece ALLOW_ADMIN_MAESTROS=true.', 'danger');
    return;
  }
  if (!confirm('¿Borrar definitivamente este maestro? Esta acción no se puede deshacer.')) return;
  var url;
  if (tipo === 'sede') url = '/api/admin/sedes/' + id;
  else if (tipo === 'sociedad') url = '/api/admin/sociedades/' + id;
  else if (tipo === 'comercializadora') url = '/api/admin/comercializadoras/' + id;
  else if (tipo === 'suministro') url = '/api/admin/suministros/' + id;
  else {
    mostrarAlerta('Este maestro no permite borrado físico; usa cambio de estado.', 'warning');
    return;
  }
  adminFetch(url, { method: 'DELETE' }).then(function (d) {
    if (d && d.exito) {
      mostrarAlerta('Maestro borrado.', 'success');
      adminRecargar();
    } else {
      mostrarAlerta('Error: ' + (d && d.error ? d.error : 'desconocido'), 'danger');
    }
  });
}

// ── Helper de escape HTML ────────────────────────────────────────────────────

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Inicialización al cambiar a la pestaña admin ────────────────────────────

function adminInit() {
  adminCheckAdmin().then(function () {
    adminSwitchSubTab(adminSubTabActual);
  });
}
