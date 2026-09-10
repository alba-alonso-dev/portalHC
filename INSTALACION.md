# Guía de instalación — Portal de Datos Ambientales Hiberus

Instalación local del portal. La aplicación es autocontenida: no requiere servidor de
base de datos, ni Docker, ni servicios externos.

---

## 1. Requisitos previos

| Requisito | Versión | Notas |
|---|---|---|
| Python | **3.13** | PaddleOCR soporta 3.9–3.13. El entorno de referencia usa 3.13.14 |
| Espacio en disco | ~3 GB | PaddlePaddle y los modelos de PaddleOCR son pesados |
| Conexión a internet | Sí, en la instalación | Para `pip` y para descargar los modelos OCR en el primer uso |

**No se necesita Tesseract.** El OCR lo proporciona PaddleOCR, instalado vía `pip`.

Descarga de Python: <https://www.python.org/downloads/release/python-3130/>
(en Windows, marca **"Add Python to PATH"** durante la instalación).

Verificación:

```powershell
python --version
# Python 3.13.x
```

---

## 2. Instalación en Windows

### Opción A — Script automático (recomendado)

Desde la carpeta del proyecto:

```powershell
.\setup_windows.bat
```

El script:

1. Localiza Python 3.13 (en el `PATH` o en `%LOCALAPPDATA%\Programs\Python\Python313`).
2. Crea el entorno virtual `venv\` si no existe.
3. Actualiza `pip`.
4. Instala todo `requirements.txt`, incluido PaddleOCR.

### Opción B — Manual

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 3. Instalación en Linux / macOS

> **Aviso:** los pasos manuales siguientes están verificados. `setup_linux.sh`
> automatiza exactamente lo mismo si prefieres usarlo.

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` incluye `opencv-python-headless`, por lo que no hacen falta las
librerías gráficas del sistema para OpenCV.

---

## 4. Arranque

```powershell
# Windows
.\venv\Scripts\python.exe app.py
```

```bash
# Linux / macOS
source venv/bin/activate
python app.py
```

Salida esperada en consola:

```
============================================================
Portal de Datos Ambientales - Hiberus  (Fase 4)
============================================================
URL:   http://localhost:5000
BD:    facturas_hc.db
Debug: False
  Módulos: Dashboard ESG · Alertas · Informe GHG · Estimaciones avanzadas
============================================================
```

Abre **<http://localhost:5000>**.

Las migraciones de base de datos se ejecutan automáticamente al importar `app.py`,
tanto con `python app.py` como bajo un servidor WSGI. Son idempotentes: puedes
arrancar tantas veces como quieras sin dañar los datos existentes.

### Variables de entorno

| Variable | Por defecto | Efecto |
|---|---|---|
| `FLASK_DEBUG` | `false` | `true` activa el modo debug. Solo desarrollo local |
| `PORT` | `5000` | Puerto de escucha |
| `DOCUMENTO_STORAGE` | `local` | Backend de almacenamiento de PDFs. **Solo `local` es funcional**; `sharepoint` selecciona una implementación que todavía es un esqueleto y lanza `NotImplementedError` al guardar |
| `ALLOW_DEV_RESET` | `false` | Habilita `POST /api/dev/reset-datos` (borrado de datos transaccionales). Sin esta variable el endpoint responde `403` |
| `ALLOW_ADMIN_MAESTROS` | `false` | Habilita las operaciones de escritura sobre datos maestros (países, sedes, sociedades, comercializadoras, tipos de energía, suministros) desde la pestaña **Admin**. Sin esta variable los endpoints de lectura funcionan pero los de escritura responden `403` y la pestaña Admin se oculta del menú |

```powershell
$env:PORT = "8080"
.\venv\Scripts\python.exe app.py
```

La aplicación escucha en `0.0.0.0`, por lo que es accesible desde otras máquinas de la
red. Ten en cuenta que **el portal no tiene autenticación**: no lo expongas fuera de una
red de confianza.

---

## 5. Verificación de la instalación

1. La página carga en `http://localhost:5000` y se ven las 8 pestañas: *Cargar Facturas,
   Historial, Factores de Emisión, Recálculo, Estimaciones, Dashboard ESG, Alertas,
   Informe GHG*.
2. En *Cargar Facturas*, los desplegables de país y sede se rellenan (los sirven
   `/api/paises` y `/api/sedes/<pais>`).
3. La pestaña *Factores de Emisión* muestra factores por país y año.
4. Sube un PDF de factura eléctrica y comprueba que se extraen consumo, período y
   comercializadora, y que se calculan las emisiones.

> El **primer** PDF escaneado que proceses tardará bastante más de lo normal: PaddleOCR
> descarga sus modelos en ese momento. Los PDFs con capa de texto van por `pdfplumber`
> y no activan el OCR.

---

## 6. Configuración posterior

### Factores de emisión

`config.py` contiene `FACTORES_EMISION`, pero **solo se usa como semilla en la primera
migración**. Después, la fuente de verdad es la tabla `factores_emision` de la base de
datos. Para actualizar un factor usa la pestaña *Factores de Emisión* o la API
`/api/factores`, que crean una nueva versión y registran el cambio en
`factores_historial`. Tras publicar un factor nuevo, usa la pestaña *Recálculo* para
propagarlo al histórico.

### Sedes, países y comercializadoras

Viven en las tablas `paises`, `sedes` y `comercializadoras`. `config.py` mantiene los
catálogos `SEDES_PAISES` y `COMERCIALIZADORAS`, que se usan como semilla de las
migraciones. Añadir una sede nueva a un despliegue ya migrado requiere insertarla en la
base de datos.

### Umbral de revisión manual

`UMBRAL_REVISION = 0.75` en `config.py`. Por debajo de esa confianza OCR la factura se
marca para revisión manual. Los campos de `CAMPOS_CRITICOS_REVISION`
(`consumo`, `periodo`, `cups`, `sociedad`, `comercializadora`) fuerzan revisión por sí
solos si su confianza es baja.

### Plantillas de comercializadora

`config/plantillas_facturas/*.yaml` define reglas y zonas de extracción por
comercializadora (16 plantillas). Añadir un YAML nuevo permite afinar la extracción de
un emisor concreto sin tocar el código.

### Almacenamiento de documentos

Los PDFs se guardan bajo `uploads/`, organizados por ejercicio / país / sede. La ruta
raíz es `UPLOAD_FOLDER` en `config.py`. El acceso está abstraído por
`services/documento_service.py`, pensado para poder sustituirse por SharePoint más
adelante.

---

## 7. Resolución de problemas

### `python` no se reconoce como comando

Python no se instaló con "Add Python to PATH". Reinstálalo marcando esa opción, o
invoca el ejecutable por ruta completa:
`%LOCALAPPDATA%\Programs\Python\Python313\python.exe`.

### `setup_windows.bat` dice que no encuentra Python 3.13

El script solo acepta 3.13. Si tienes otra versión instalada, instala 3.13 o crea el
entorno virtual manualmente (sección 2, opción B) con una versión entre 3.9 y 3.13.

### `ModuleNotFoundError` al arrancar

Estás usando el intérprete del sistema en lugar del del entorno virtual. Arranca
siempre con `.\venv\Scripts\python.exe app.py` (Windows) o con el `venv` activado.

### El puerto 5000 está ocupado

```powershell
$env:PORT = "8080"
.\venv\Scripts\python.exe app.py
```

En macOS, el puerto 5000 lo suele ocupar AirPlay Receiver.

### La instalación de PaddlePaddle falla o tarda muchísimo

Son paquetes grandes. Asegúrate de haber actualizado `pip` antes
(`python -m pip install --upgrade pip`) y de tener espacio en disco suficiente.

### Error 413 al subir un PDF

El límite es de 50 MB por petición (`MAX_CONTENT_LENGTH` en `app.py`).

### La extracción devuelve datos vacíos o erróneos

Comprueba la confianza OCR de la factura en el historial. Si es un PDF escaneado de
mala calidad, quedará marcado para revisión manual, que es el comportamiento previsto.
Para una comercializadora recurrente, la vía correcta es añadir o ajustar su plantilla
en `config/plantillas_facturas/`.

### Quiero partir de una base de datos limpia

Existe `POST /api/dev/reset-datos`, expuesto en la interfaz mediante un modal. Es una
utilidad de desarrollo, **borra datos** y solo funciona con `ALLOW_DEV_RESET=true`;
vacía las tablas transaccionales y conserva los maestros (factores, países, sedes,
comercializadoras). Como alternativa, para empezar de cero por completo, detén la
aplicación y elimina `facturas_hc.db`: se recreará vacía en el siguiente arranque.
Haz copia de seguridad antes.

### Modo admin — editar datos maestros

La pestaña **Admin** permite crear, editar, activar/desactivar y borrar los datos
maestros del portal desde la interfaz:

- países (`paises`)
- sedes (`sedes`)
- sociedades (`sociedades`) — titular legal de cada punto de suministro
- comercializadoras (`comercializadoras`)
- tipos de energía (`tipos_energia`)
- suministros (`suministros`) — puntos de suministro (CUPS)

#### Modelo jerárquico

El portal modela la realidad del grupo Hiberus con esta jerarquía:

```
país → sede → suministro (CUPS) → sociedad (titular)
```

- Un **país** tiene varias **sedes** (p. ej. España → Asturias, Madrid, Bilbao…).
- Una **sede** puede tener varios **suministros** (CUPS), cada uno facturado a una
  **sociedad** distinta del grupo (p. ej. Asturias tiene CUPS de *Hiberus
  Tecnologías de la Información SL* y de *HIBERUS IT DEVELOPMENT SERVICES SL*).
- La **sociedad** es el titular legal del punto de suministro. El campo
  `facturas.sociedad` es solo un respaldo en texto libre; la clave de
  agrupación real es `suministros.sociedad_id` → `sociedades.id`.
- Si un suministro tiene facturas con sociedades distintas (caso excepcional),
  la migración lo deja sin vincular (`sociedad_id = NULL`) para revisión manual
  desde la pestaña Admin.

Por seguridad, las operaciones de escritura están deshabilitadas por defecto y la
pestaña se muestra en **solo lectura**. Para habilitar la edición, arranca con:

```powershell
$env:ALLOW_ADMIN_MAESTROS = "true"
.\venv\Scripts\python.exe app.py
```

Las operaciones de lectura (listar catálogos) funcionan siempre. Cada modificación
queda registrada en `audit_log` para mantener la trazabilidad. Igual que con
`ALLOW_DEV_RESET`, esta variable **solo debe activarse en entornos de confianza**
(y nunca en un despliegue expuesto), porque el portal no tiene autenticación.

---

## 8. Ejecutar las pruebas

`tests/` contiene dos ficheros (`test_campos_factura.py` y `test_plantillas.py`), pero
`pytest` **no** está en `requirements.txt` ni instalado en el entorno virtual. Para
ejecutarlas:

```powershell
.\venv\Scripts\python.exe -m pip install pytest
.\venv\Scripts\python.exe -m pytest tests\
```
