/**
 * API client común para el frontend.
 *
 * Centraliza las llamadas fetch para:
 *  - Evitar repetir el patrón `.then(r => r.json())` en cada llamada.
 *  - Manejar errores HTTP de forma consistente (toast automático).
 *  - Aceptar bodies como objetos JS (se serializan a JSON automáticamente).
 *
 * Fase 1 — Refactor de bajo riesgo.
 *
 * Uso:
 *   // GET
 *   const data = await api.get('/api/dashboard/resumen?anio=2026');
 *
 *   // POST con body JSON
 *   const data = await api.post('/api/estimaciones', { pais: 'ES', ... });
 *
 *   // POST con FormData (uploads)
 *   const data = await api.postForm('/api/procesar-lote', formData);
 *
 *   // DELETE
 *   const data = await api.del('/api/factura/42');
 *
 *   // PATCH
 *   const data = await api.patch('/api/factores/12/estado', { activo: false });
 *
 *   // Descarga de archivo (blob)
 *   const blob = await api.blob('/api/descargar-excel?pais=ES');
 */

/**
 * Lanza un toast de error si la respuesta no es OK.
 * Devuelve los datos JSON parseados, o null si la respuesta no es JSON.
 *
 * @param {Response} r — respuesta de fetch
 * @param {string} [contexto] — descripción para el mensaje de error
 * @returns {Promise<object|null>} — datos JSON o null
 */
async function _apiParse(r, contexto) {
  if (!r.ok) {
    let msg = 'Error ' + r.status;
    try {
      const err = await r.json();
      msg = err.error || msg;
    } catch (_) { /* respuesta no JSON */ }
    if (typeof toast === 'function') {
      toast((contexto ? contexto + ': ' : '') + msg, 'danger');
    }
    return null;
  }
  // Respuesta OK — intentar parsear como JSON, fallback a null
  try {
    return await r.json();
  } catch (_) {
    return null;
  }
}

const api = {
  /**
   * GET a una URL. Devuelve los datos JSON o null si hay error.
   * @param {string} url
   * @param {string} [contexto] — descripción para mensajes de error
   * @returns {Promise<object|null>}
   */
  async get(url, contexto) {
    const r = await fetch(url);
    return _apiParse(r, contexto);
  },

  /**
   * POST con body JSON. Serializa automáticamente el body.
   * @param {string} url
   * @param {object} body — objeto a serializar como JSON
   * @param {string} [contexto]
   * @returns {Promise<object|null>}
   */
  async post(url, body, contexto) {
    const opts = { method: 'POST' };
    if (body instanceof FormData) {
      opts.body = body;
    } else {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(url, opts);
    return _apiParse(r, contexto);
  },

  /**
   * POST con FormData (para uploads de archivos).
   * @param {string} url
   * @param {FormData} formData
   * @param {string} [contexto]
   * @returns {Promise<object|null>}
   */
  async postForm(url, formData, contexto) {
    return this.post(url, formData, contexto);
  },

  /**
   * PUT con body JSON.
   * @param {string} url
   * @param {object} body
   * @param {string} [contexto]
   * @returns {Promise<object|null>}
   */
  async put(url, body, contexto) {
    const opts = {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    };
    const r = await fetch(url, opts);
    return _apiParse(r, contexto);
  },

  /**
   * PATCH con body JSON.
   * @param {string} url
   * @param {object} body
   * @param {string} [contexto]
   * @returns {Promise<object|null>}
   */
  async patch(url, body, contexto) {
    const opts = {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    };
    const r = await fetch(url, opts);
    return _apiParse(r, contexto);
  },

  /**
   * DELETE.
   * @param {string} url
   * @param {string} [contexto]
   * @returns {Promise<object|null>}
   */
  async del(url, contexto) {
    const r = await fetch(url, { method: 'DELETE' });
    return _apiParse(r, contexto);
  },

  /**
   * GET que devuelve un Blob (para descargas de Excel/PDF).
   * Lanza toast si hay error.
   * @param {string} url
   * @param {string} [contexto]
   * @returns {Promise<Blob|null>}
   */
  async blob(url, contexto) {
    const r = await fetch(url);
    if (!r.ok) {
      let msg = 'Error ' + r.status;
      try {
        const err = await r.json();
        msg = err.error || msg;
      } catch (_) { /* */ }
      if (typeof toast === 'function') {
        toast((contexto ? contexto + ': ' : '') + msg, 'danger');
      }
      return null;
    }
    return r.blob();
  },
};

// Exponer globalmente para los módulos vanilla JS
window.api = api;
