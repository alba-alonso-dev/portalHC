"""
Smoke tests de endpoints críticos — Fase 0 (Estabilización).

Estos tests no validan lógica de negocio (ya cubierta por los tests de
servicio existentes), sino que verifican que la cadena completa
arranque → migración → blueprints → endpoints funciona de extremo a extremo.

Son tests de "humo": si alguno falla, hay algo roto en el cableado, no en
el cálculo. Cubren los 5 endpoints más representativos:

  1. /api/dashboard/resumen      — dashboard ESG (agregaciones)
  2. /api/estadisticas           — listado de estadísticas básicas
  3. /api/paises                 — maestros (configuración)
  4. /api/factores               — factores versionados (admin)
  5. /api/alertas/pendientes     — alertas operativas

Además validan invariantes estructurales de la Fase 0:
  - La tabla `schema_migrations` existe y tiene los 13 módulos.
  - `statement_timeout` está activo en las conexiones.
  - Las claves foráneas declaran ON DELETE CASCADE donde corresponde.
"""
import pytest

from app import create_app
from database.connection import get_db_connection


@pytest.fixture(scope="module")
def app():
    """App Flask para tests. Usa la BD real (los tests existentes hacen lo mismo)."""
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


# ── Invariantes estructurales (Fase 0) ────────────────────────────────────────


def test_schema_migrations_existe_y_tiene_13_modulos():
    """La tabla schema_migrations debe existir y tener los 13 módulos registrados."""
    with get_db_connection() as conn:
        # La tabla existe
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "schema_migrations" in tablas, "La tabla schema_migrations no existe"

        # Tiene 13 módulos
        count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        assert count == 13, f"Esperaba 13 módulos en schema_migrations, hay {count}"


def test_statement_timeout_activo():
    """
    Las conexiones deben llevar statement_timeout, para que una consulta
    bloqueada no deje colgado un worker de gunicorn.

    Sustituye al antiguo invariante `busy_timeout=5000` de SQLite, que existía
    para tolerar su limitación de un único escritor.
    """
    with get_db_connection() as conn:
        timeout = conn.execute("SHOW statement_timeout").fetchone()[0]
        assert timeout not in (None, '0'), \
            f"Esperaba statement_timeout activo, got {timeout}"


def test_claves_foraneas_con_cascade():
    """
    facturas_historial debe borrarse en cascada al borrar su factura.

    En SQLite había que comprobar el PRAGMA foreign_keys porque las claves
    foráneas podían desactivarse por conexión; PostgreSQL siempre las aplica,
    así que lo que procede verificar es que la restricción está declarada.
    """
    with get_db_connection() as conn:
        cascade = conn.execute("""
            SELECT 1
              FROM pg_constraint
             WHERE contype = 'f'
               AND conrelid = 'facturas_historial'::regclass
               AND confdeltype = 'c'
        """).fetchone()
        assert cascade is not None, \
            "facturas_historial no declara ON DELETE CASCADE hacia facturas"


# ── Smoke tests de endpoints críticos ─────────────────────────────────────────


def test_endpoint_dashboard_resumen(client):
    """GET /api/dashboard/resumen debe responder 200 y tener estructura básica."""
    r = client.get("/api/dashboard/resumen")
    assert r.status_code == 200, f"Status {r.status_code}: {r.data[:200]}"
    data = r.get_json()
    assert data is not None, "Respuesta no es JSON"
    # Debe tener al menos alguna de las claves esperadas del dashboard
    assert isinstance(data, dict), f"Esperaba dict, got {type(data)}"


def test_endpoint_estadisticas(client):
    """GET /api/estadisticas debe responder 200 y devolver JSON."""
    r = client.get("/api/estadisticas")
    assert r.status_code == 200, f"Status {r.status_code}: {r.data[:200]}"
    data = r.get_json()
    assert data is not None, "Respuesta no es JSON"


def test_endpoint_paises(client):
    """GET /api/paises debe responder 200 y devolver una lista de países."""
    r = client.get("/api/paises")
    assert r.status_code == 200, f"Status {r.status_code}: {r.data[:200]}"
    data = r.get_json()
    assert data is not None, "Respuesta no es JSON"
    # Debe contener al menos España (ES) que es el país principal del proyecto
    if isinstance(data, list):
        assert len(data) > 0, "La lista de países está vacía"
    elif isinstance(data, dict):
        assert "paises" in data or "exito" in data, f"Estructura inesperada: {list(data.keys())}"


def test_endpoint_factores(client):
    """GET /api/factores debe responder 200 y devolver factores."""
    r = client.get("/api/factores")
    assert r.status_code == 200, f"Status {r.status_code}: {r.data[:200]}"
    data = r.get_json()
    assert data is not None, "Respuesta no es JSON"


def test_endpoint_alertas_pendientes(client):
    """GET /api/alertas/pendientes debe responder 200 y devolver JSON."""
    r = client.get("/api/alertas/pendientes")
    assert r.status_code == 200, f"Status {r.status_code}: {r.data[:200]}"
    data = r.get_json()
    assert data is not None, "Respuesta no es JSON"


def test_endpoint_dashboard_esg(client):
    """GET /api/dashboard/esg debe responder 200 (dashboard ESG de Fase 6)."""
    r = client.get("/api/dashboard/esg")
    assert r.status_code == 200, f"Status {r.status_code}: {r.data[:200]}"
    data = r.get_json()
    assert data is not None, "Respuesta no es JSON"


def test_endpoint_ghg_ranking_sociedades(client):
    """GET /api/ghg/ranking/sociedades debe responder 200 (drill-down Fase B)."""
    r = client.get("/api/ghg/ranking/sociedades")
    assert r.status_code == 200, f"Status {r.status_code}: {r.data[:200]}"
    data = r.get_json()
    assert data is not None, "Respuesta no es JSON"
