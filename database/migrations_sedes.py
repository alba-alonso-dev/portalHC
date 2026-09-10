"""
Migración de normalización de sedes.

Problema que resuelve
─────────────────────
`sedes` declara UNIQUE(pais_codigo, nombre), pero esa restricción compara los
nombres literalmente. `migrations_refactor._poblar_sedes()` siembra la tabla desde
dos orígenes distintos:

  1. `config.SEDES_PAISES`  → nombres correctos, con tilde  ("Almería", "Logroño")
  2. `SELECT DISTINCT sede FROM facturas` → lo que se haya guardado históricamente,
     que en algunos despliegues llegó sin tildes ("Almeria", "Logrono")

Como "Almeria" y "Almería" son literales distintos, el UNIQUE no los detecta y la
misma ubicación acaba representada por dos filas. Consecuencia: las agregaciones por
sede (dashboard, informe GHG, cobertura, estimaciones) reparten el consumo de una
misma sede entre dos registros.

Qué hace este módulo
────────────────────
  1. Agrupa las sedes por una clave insensible a tildes, mayúsculas y espacios.
  2. Elige un nombre canónico por grupo (preferentemente el de `config.SEDES_PAISES`).
  3. Repunta todas las referencias — `suministros.sede_id` y las columnas de texto
     `sede` del resto de tablas — hacia el registro canónico.
  4. Elimina las filas duplicadas sobrantes.

No toca `archivo_ruta` ni `carpeta_relativa`: son rutas físicas en disco y deben
seguir apuntando a las carpetas realmente existentes.

Es idempotente: si no hay duplicados, no hace nada.
"""

import logging
import unicodedata

from database.connection import (IntegrityError, OperationalError, Row,
                                 get_db_connection)
import config

logger = logging.getLogger(__name__)


# Tablas con una columna de texto `sede` que hay que repuntar al nombre canónico.
# (tabla, columna)
_TABLAS_SEDE_TEXTO = [
    ('facturas',           'sede'),
    ('documentos_indice',  'sede'),
    ('estimaciones',       'sede'),
    ('alertas',            'sede'),
    ('periodos_faltantes', 'sede'),
    ('objetivos_emision',  'sede'),
    ('lotes_recalculo',    'filtro_sede'),
]


def clave_sede(nombre: str) -> str:
    """
    Clave de comparación insensible a tildes, mayúsculas y espacios redundantes.

    "Almería" y "almeria " producen la misma clave, de modo que se reconocen como
    la misma sede aunque el UNIQUE literal de la tabla no lo haga.
    """
    if nombre is None:
        return ''
    descompuesto = unicodedata.normalize('NFKD', str(nombre))
    sin_tildes = ''.join(c for c in descompuesto if not unicodedata.combining(c))
    return ' '.join(sin_tildes.split()).casefold()


def _tabla_existe(conn, tabla: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
    ).fetchone() is not None


def _columna_existe(conn, tabla: str, columna: str) -> bool:
    cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{tabla}")')}
    return columna in cols


def _nombres_config() -> dict[tuple[str, str], str]:
    """
    Mapa {(pais, clave_sede): nombre_en_config} para poder preferir la grafía
    declarada en config.SEDES_PAISES como forma canónica.
    """
    canon: dict[tuple[str, str], str] = {}
    for pais, lista in getattr(config, 'SEDES_PAISES', {}).items():
        for nombre in lista:
            canon[(pais.upper(), clave_sede(nombre))] = nombre
    return canon


def _elegir_canonica(grupo: list[Row], pais: str,
                     canon_config: dict[tuple[str, str], str]) -> Row:
    """
    Devuelve la fila que debe sobrevivir dentro de un grupo de sedes duplicadas.

    Prioridad:
      1. La que coincide exactamente con el nombre declarado en config.SEDES_PAISES.
      2. La que conserva caracteres no ASCII (las tildes son la grafía correcta).
      3. La de menor id (la más antigua), como desempate determinista.
    """
    nombre_config = canon_config.get((pais, clave_sede(grupo[0]['nombre'])))
    if nombre_config:
        for fila in grupo:
            if fila['nombre'] == nombre_config:
                return fila

    con_tildes = [f for f in grupo if any(ord(c) > 127 for c in f['nombre'])]
    if con_tildes:
        return min(con_tildes, key=lambda f: f['id'])

    return min(grupo, key=lambda f: f['id'])


def _repuntar_suministros(conn, id_viejo: int, id_canonico: int) -> int:
    """
    Mueve los suministros de la sede duplicada a la canónica.

    `suministros` declara UNIQUE(sede_id, tipo_energia, referencia): si la sede
    canónica ya tiene un suministro equivalente, el de la duplicada es redundante y
    se elimina tras repuntar las facturas que lo referencian.
    """
    movidos = 0
    filas = conn.execute(
        'SELECT id, tipo_energia, referencia FROM suministros WHERE sede_id = ?',
        (id_viejo,)
    ).fetchall()

    for fila in filas:
        gemelo = conn.execute(
            '''SELECT id FROM suministros
               WHERE sede_id = ? AND tipo_energia = ?
                 AND referencia IS ?''',
            (id_canonico, fila['tipo_energia'], fila['referencia'])
        ).fetchone()

        if gemelo:
            # Ya existe el equivalente en la sede canónica: reapuntar las facturas
            # al suministro superviviente y descartar el duplicado.
            if _columna_existe(conn, 'facturas', 'suministro_id'):
                conn.execute(
                    'UPDATE facturas SET suministro_id = ? WHERE suministro_id = ?',
                    (gemelo['id'], fila['id'])
                )
            conn.execute('DELETE FROM suministros WHERE id = ?', (fila['id'],))
        else:
            conn.execute(
                'UPDATE suministros SET sede_id = ? WHERE id = ?',
                (id_canonico, fila['id'])
            )
            movidos += 1

    return movidos


def _repuntar_texto(conn, tabla: str, columna: str, pais: str,
                    nombre_viejo: str, nombre_canonico: str) -> int:
    """
    Renombra la sede en una columna de texto.

    Varias de estas tablas tienen restricciones UNIQUE que incluyen la sede
    (`periodos_faltantes`, `objetivos_emision`), por lo que el renombrado puede
    chocar con una fila que ya use el nombre canónico. En ese caso la fila
    duplicada se elimina: describe el mismo ámbito que la superviviente.
    """
    if not _tabla_existe(conn, tabla) or not _columna_existe(conn, tabla, columna):
        return 0

    filtro_pais = ''
    params_pais: tuple = ()
    if _columna_existe(conn, tabla, 'pais'):
        filtro_pais = ' AND pais = ?'
        params_pais = (pais,)

    # `ctid` es el identificador físico de fila de PostgreSQL, equivalente al
    # `rowid` de SQLite: sirve para direccionar filas en tablas que no declaran
    # clave primaria (varias de estas tablas maestras no la tienen).
    filas = conn.execute(
        f'SELECT ctid::text AS rid FROM "{tabla}" WHERE "{columna}" = ?{filtro_pais}',
        (nombre_viejo,) + params_pais
    ).fetchall()

    actualizadas = 0
    for fila in filas:
        try:
            # El savepoint es imprescindible: en PostgreSQL un error de
            # integridad aborta la transacción entera, y aquí necesitamos
            # seguir trabajando con la conexión para borrar la fila que chocó.
            with conn.transaction():
                conn.execute(
                    f'UPDATE "{tabla}" SET "{columna}" = ? WHERE ctid = ?::tid',
                    (nombre_canonico, fila['rid'])
                )
            actualizadas += 1
        except IntegrityError:
            conn.execute(f'DELETE FROM "{tabla}" WHERE ctid = ?::tid',
                         (fila['rid'],))
            logger.warning(
                "  %s: fila ctid=%s eliminada por colisión al normalizar '%s' → '%s'",
                tabla, fila['rid'], nombre_viejo, nombre_canonico
            )
    return actualizadas


def deduplicar_sedes() -> int:
    """
    Fusiona las sedes que solo se diferencian en tildes, mayúsculas o espacios.

    Returns
    -------
    int
        Número de filas duplicadas eliminadas de `sedes`.
    """
    canon_config = _nombres_config()
    eliminadas = 0

    with get_db_connection() as conn:
        if not _tabla_existe(conn, 'sedes'):
            return 0

        filas = conn.execute(
            'SELECT id, pais_codigo, nombre FROM sedes'
        ).fetchall()

        grupos: dict[tuple[str, str], list[Row]] = {}
        for fila in filas:
            clave = (fila['pais_codigo'], clave_sede(fila['nombre']))
            grupos.setdefault(clave, []).append(fila)

        for (pais, _), grupo in grupos.items():
            if len(grupo) < 2:
                continue

            canonica = _elegir_canonica(grupo, pais, canon_config)
            duplicadas = [f for f in grupo if f['id'] != canonica['id']]

            logger.info(
                "  Sedes duplicadas en %s: %s → '%s'",
                pais,
                ', '.join(f"'{f['nombre']}'" for f in duplicadas),
                canonica['nombre'],
            )

            for dup in duplicadas:
                _repuntar_suministros(conn, dup['id'], canonica['id'])
                for tabla, columna in _TABLAS_SEDE_TEXTO:
                    _repuntar_texto(conn, tabla, columna, pais,
                                    dup['nombre'], canonica['nombre'])
                conn.execute('DELETE FROM sedes WHERE id = ?', (dup['id'],))
                eliminadas += 1

    return eliminadas


def ejecutar_migraciones_sedes():
    """Punto de entrada. Idempotente — seguro ejecutar múltiples veces."""
    logger.info("Normalización de sedes: iniciando...")
    eliminadas = deduplicar_sedes()
    if eliminadas:
        logger.info("  %d sede(s) duplicada(s) fusionada(s)", eliminadas)
    else:
        logger.info("  sin sedes duplicadas — nada que hacer")
    logger.info("Normalización de sedes completada")
