# ──────────────────────────────────────────────────────────────────────────
# Dockerfile — Portal de Datos Ambientales Hiberus
#
# Imagen basada en Python 3.13 (slim) con PaddleOCR + pdfplumber.
# Sirve la app con gunicorn (recomendado en producción frente a `python app.py`).
#
# La base de datos es PostgreSQL y vive en otro contenedor (servicio `db` de
# docker-compose), no dentro de esta imagen.
#
# Build:
#   docker build -t portal-hc-hiberus .
#
# Run (necesita un PostgreSQL accesible):
#   docker run --rm -p 5000:5000 \
#     -v portal_hc_data:/data \
#     -e DATABASE_URL=postgresql://portal:portal@host:5432/portal_hc \
#     -e ALLOW_ADMIN_MAESTROS=true \
#     portal-hc-hiberus
#
# Los PDFs se persisten en /data (montado como volumen).
# ──────────────────────────────────────────────────────────────────────────

FROM python:3.13-slim

# ── 1. Dependencias del sistema ──────────────────────────────────────────
# libgomp1 es requerido por PaddlePaddle. libgl1 y libglib2.0-0 por OpenCV
# (opencv-python-headless). Se mantienen al mínimo para reducir superficie.
# Se limpia apt al final para no dejar caché.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ── 2. Directorio de trabajo ──────────────────────────────────────────────
WORKDIR /app

# ── 3. Copiar e instalar dependencias primero (mejor cache de capas) ──────
# Si requirements.txt no cambia, esta capa se reutiliza y no reinstala
# PaddleOCR (~3 GB) en cada build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0

# ── 4. Copiar el código de la aplicación ──────────────────────────────────
COPY . .

# ── 5. Directorio de datos persistentes ──────────────────────────────────
# /data/uploads → PDFs subidos. Se monta como volumen desde docker-compose.
# La base de datos ya no vive aquí: está en el servicio PostgreSQL.
RUN mkdir -p /data/uploads
ENV UPLOAD_FOLDER=/data/uploads

# ── 6. Variables por defecto ─────────────────────────────────────────────
# DATABASE_URL apunta al servicio `db` de docker-compose. Sobreescribir con
# la URL real al desplegar contra un PostgreSQL externo.
ENV PORT=5000 \
    FLASK_DEBUG=false \
    DOCUMENTO_STORAGE=local \
    PADDLE_DISABLE_MKLDNN=true \
    DATABASE_URL=postgresql://portal:portal@db:5432/portal_hc

# ── 7. Healthcheck ────────────────────────────────────────────────────────
# Consulta el endpoint raíz (/) cada 30s. Si no responde en 5s, se marca
# unhealthy. Sirve para que docker-compose / orquestadores detecten caídas.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:${PORT}/', timeout=3)" || exit 1

# ── 8. Exponer puerto ────────────────────────────────────────────────────
EXPOSE 5000

# ── 9. Comando de arranque ───────────────────────────────────────────────
# --preload: ejecuta el módulo una vez antes de forkear workers. Así las
#   migraciones corren una sola vez y los workers heredan la BD ya lista
#   (recomendación de database/migrations.py).
# --workers=2: suficiente para uso interno; subir solo si hay más carga.
# --bind 0.0.0.0:porta: accesible desde fuera del contenedor.
# --timeout 120: PaddleOCR puede tardar >30s en el primer PDF escaneado.
CMD ["sh", "-c", "gunicorn --preload --workers=${GUNICORN_WORKERS:-2} --timeout 300 --bind 0.0.0.0:${PORT:-5000} app:app"]
