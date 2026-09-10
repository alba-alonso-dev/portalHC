# Despliegue con Docker — Portal de Datos Ambientales Hiberus

Guía para publicar el portal en un servidor accesible al equipo, usando Docker
y Docker Compose. Así dejas de depender de tu máquina local.

> Requisitos previos en el servidor: **Docker** y **Docker Compose** instalados.
> No hace falta Python, venv ni PaddleOCR en el host: todo va dentro del contenedor.

---

## 1. Preparar la configuración

En la raíz del proyecto, copia el ejemplo de variables de entorno:

```powershell
Copy-Item .env.example .env
```

Edita `.env` y ajusta:

| Variable | Recomendado para demo | Notas |
|---|---|---|
| `HOST_PORT` | `5000` | Puerto visible en el servidor |
| `ALLOW_ADMIN_MAESTROS` | `false` | `true` solo si vas a editar maestros en la demo |
| `ALLOW_DEV_RESET` | `false` | Siempre `false` en entornos compartidos |
| `GUNICORN_WORKERS` | `2` | Suficiente para uso interno |

---

## 2. Construir y arrancar

Desde la raíz del proyecto (donde está el `Dockerfile`):

```powershell
docker compose up -d --build
```

La **primera vez** tarda varios minutos: descarga la imagen base de Python e
instala PaddleOCR y dependencias (~3 GB). Builds posteriores usan la caché de
capas y son mucho más rápidos.

Salida esperada:

```
✔ Container portal-hc-hiberus  Started
```

Verifica que responde:

```powershell
curl http://localhost:5000/
```

Abre el navegador en `http://localhost:5000` (o el `HOST_PORT` que hayas puesto).

---

## 3. Persistencia de datos

La base de datos (`facturas_hc.db`) y los PDFs subidos se guardan en el volumen
`portal_hc_data`, dentro del contenedor en `/data`. Esto significa:

- ✅ Los datos **sobreviven** a `docker compose down`, reinicios del servidor y
  reconstrucciones de la imagen.
- ❌ Los datos **se pierden** si haces `docker compose down -v` (el `-v` borra
  los volúmenes).

### Copia de seguridad de la BD

```powershell
# Backup puntual
docker compose exec portal cp /data/facturas_hc.db /data/facturas_hc.db.bak_$(date +%Y%m%d_%H%M%S)

# Copiar al host (ej. para respaldo externo)
docker compose cp portal:/data/facturas_hc.db ./backup_facturas.db
```

### Restaurar una BD existente

Si ya tienes un `facturas_hc.db` con datos en tu máquina y quieres cargarlo
en el contenedor:

```powershell
# 1. Asegúrate de que el contenedor está parado
docker compose down

# 2. Copia tu BD al volumen
docker compose run --rm --entrypoint cp portal \
    ./facturas_hc.db /data/facturas_hc.db

# 3. Arranca de nuevo
docker compose up -d
```

---

## 4. Migrar datos de tu máquina al contenedor

Si llevas meses trabajando con la app en local y quieres que el contenedor
use esa misma BD y PDFs:

```powershell
# 1. Para el servidor local si está corriendo
# 2. Levanta el contenedor por primera vez (crea el volumen vacío)
docker compose up -d
docker compose down

# 3. Copia la BD y la carpeta uploads al volumen
docker run --rm -v portal_hc_hiberus_portal_hc_data:/data `
    -v "${PWD}:/src" busybox `
    sh -c "cp /src/facturas_hc.db /data/ && cp -r /src/uploads/. /data/uploads/"

# 4. Arranca de nuevo
docker compose up -d
```

> Nota: el nombre exacto del volumen puede variar. Comprueba con
> `docker volume ls | findstr portal_hc`.

---

## 5. Comandos útiles

```powershell
# Ver logs en vivo
docker compose logs -f

# Ver estado del contenedor (y healthcheck)
docker compose ps

# Reiniciar
docker compose restart

# Parar (mantiene los datos)
docker compose down

# Parar y borrar los datos (¡cuidado!)
docker compose down -v

# Reconstruir tras cambiar código
docker compose up -d --build

# Entrar al contenedor (depuración)
docker compose exec portal bash

# Ejecutar una consulta en la BD
docker compose exec portal python -c "import sqlite3; print(sqlite3.connect('/data/facturas_hc.db').execute('select count(*) from facturas').fetchone())"
```

---

## 6. Despliegue en un servidor de red

Para que el equipo acceda desde sus máquinas, en el servidor:

1. Asegúrate de que el puerto (`HOST_PORT`, por defecto 5000) esté abierto en
   el firewall del servidor.
2. Arranca con `docker compose up -d --build`.
3. El equipo accede desde `http://<IP_DEL_SERVIDOR>:5000`.

> ⚠️ **Sin autenticación**: cualquier persona que alcance el puerto puede operar.
> No expongas el puerto a Internet. Limita el acceso a la red interna
> (VPN corporativa o red de oficina). La autenticación con Azure AD está
> planificada en la Fase 7 del roadmap.

---

## 7. Editar plantillas sin reconstruir

El `docker-compose.yml` monta `./config` como solo lectura dentro del contenedor.
Esto significa que si añades o editas una plantilla YAML en
`config/plantillas_facturas/`, **se ve inmediatamente** sin reconstruir la imagen:

```
config/plantillas_facturas/nueva_comercializadora.yaml
→ disponible en el contenedor en /app/config/plantillas_facturas/
```

Para cambios en código Python (services, routes, etc.) sí necesitas reconstruir:

```powershell
docker compose up -d --build
```

---

## 8. Estructura dentro del contenedor

```
/app/                    ← código de la aplicación (horneado en la imagen)
  app.py
  config.py
  routes/
  services/
  database/
  templates/
  static/
  config/
    plantillas_facturas/ ← montado desde el host (editables sin rebuild)
/data/                   ← volumen persistente (NO se pierde al hacer down)
  facturas_hc.db         ← base de datos SQLite
  uploads/               ← PDFs subidos organizados por YYYY/PAIS/SEDE/
```

---

## 9. Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `docker compose` no se reconoce | Instala Docker Desktop o Docker Compose v2 |
| El primer build tarda mucho (>10 min) | Es normal: PaddlePaddle pesa ~3 GB. Los siguientes builds usan caché |
| `Bind for 0.0.0.0:5000 failed: port already allocated` | Otro proceso usa el puerto. Cambia `HOST_PORT` en `.env` o libera el puerto |
| Healthcheck `unhealthy` los primeros 60s | Normal: `start_period=60s`. Si persiste, revisa `docker compose logs` |
| `database is locked` bajo concurrencia | SQLite es single-writer. Subir `GUNICORN_WORKERS` no ayuda; para más carga, el roadmap prevé PostgreSQL |
| No veo los PDFs que subí | Están en el volumen. Comprueba con `docker compose exec portal ls /data/uploads` |

---

## 10. Resumen rápido (cheat sheet)

```powershell
# Configurar (una sola vez)
Copy-Item .env.example .env

# Arrancar
docker compose up -d --build

# Ver si está vivo
docker compose ps
curl http://localhost:5000/

# Logs
docker compose logs -f

# Parar (mantiene datos)
docker compose down
```
