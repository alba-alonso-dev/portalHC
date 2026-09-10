# Instalación rápida (Windows)

Versión abreviada para poner el portal en marcha en unos minutos.
Para la guía completa —Linux/macOS, configuración y resolución de problemas— consulta
[`INSTALACION.md`](INSTALACION.md).

---

## Paso 1 — Python 3.13

Descarga e instala **Python 3.13** desde
<https://www.python.org/downloads/release/python-3130/>, marcando **"Add Python to PATH"**.

```powershell
python --version
# Python 3.13.x
```

PaddleOCR soporta Python 3.9–3.13. **No hace falta Tesseract**: el OCR se instala con `pip`.

---

## Paso 2 — Instalar dependencias

Desde la carpeta del proyecto:

```powershell
.\setup_windows.bat
```

Crea el entorno virtual `venv\` e instala Flask, pdfplumber, PaddleOCR, pandas, openpyxl
y el resto de `requirements.txt`. Tarda varios minutos y descarga cerca de 3 GB.

---

## Paso 3 — Arrancar

```powershell
.\venv\Scripts\python.exe app.py
```

Consola esperada:

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

Las migraciones de base de datos se aplican solas al arrancar.

---

## Paso 4 — Abrir el portal

<http://localhost:5000>

Deberías ver la cabecera *Portal de Datos Ambientales* y las 8 pestañas:
**Cargar Facturas · Historial · Factores de Emisión · Recálculo · Estimaciones ·
Dashboard ESG · Alertas · Informe GHG**.

---

## Paso 5 — Procesar una factura de prueba

1. Pestaña **Cargar Facturas**.
2. Selecciona país y sede.
3. Sube el PDF de una factura eléctrica (máximo 50 MB).
4. Al terminar, el portal muestra los datos extraídos —consumo, período,
   comercializadora, factor aplicado y emisiones en tCO₂e— e indica si la factura
   requiere revisión manual.
5. Compruébala en la pestaña **Historial**.

La fórmula aplicada es `tCO₂e = consumo_MWh × factor_kgCO₂/MWh ÷ 1000`, con el factor
vigente del país y año de la factura.

> El primer PDF **escaneado** tarda bastante más: PaddleOCR descarga sus modelos en ese
> momento. Los PDFs con capa de texto se procesan con `pdfplumber` y no lanzan el OCR.

---

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `python` no se reconoce | Reinstala Python marcando "Add Python to PATH" |
| El script no encuentra Python 3.13 | Instala 3.13, o crea el venv a mano (ver `INSTALACION.md` §2) |
| `ModuleNotFoundError` | Arranca con `.\venv\Scripts\python.exe app.py`, no con `python app.py` |
| Puerto 5000 ocupado | `$env:PORT = "8080"` antes de arrancar |
| Error 413 al subir | El PDF supera los 50 MB |

El resto de casos está en [`INSTALACION.md`](INSTALACION.md) §7.
