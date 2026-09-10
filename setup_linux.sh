#!/bin/bash

# ========================================
# INSTALACIÓN PORTAL OCR - LINUX/MAC
# Portal de Gestión Huella de Carbono
# ========================================

echo ""
echo "========================================"
echo "INSTALACION: Portal OCR - Hiberus"
echo "========================================"
echo ""

# 1. Verificar Python
echo "[1/4] Verificando Python..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 no encontrado"
    echo "Instala con: sudo apt-get install python3 python3-pip (Linux)"
    echo "            brew install python3 (macOS)"
    exit 1
fi
python3 --version
echo "✅ Python detectado"
echo ""
echo "NOTA: PaddleOCR requiere Python 3.9-3.13."
echo ""

# 2. Crear entorno virtual (opcional pero recomendado)
echo "[2/4] Creando entorno virtual..."
python3 -m venv venv
source venv/bin/activate
echo "✅ Entorno virtual creado"
echo ""

# 3. Actualizar pip
echo "[3/4] Actualizando pip..."
pip install --upgrade pip
echo "✅ pip actualizado"
echo ""

# 4. Instalar dependencias Python (incluye PaddleOCR)
echo "[4/4] Instalando dependencias Python (PaddleOCR + Flask)..."
if ! pip install -r requirements.txt; then
    echo "❌ Error instalando dependencias"
    exit 1
fi
echo "✅ Dependencias instaladas (incluye PaddleOCR)"
echo ""

echo ""
echo "========================================"
echo "✅ INSTALACIÓN COMPLETADA"
echo "========================================"
echo ""
echo "PRÓXIMO PASO:"
echo "  Ejecuta: source venv/bin/activate && python app.py"
echo "  Abre en navegador: http://localhost:5000"
echo ""
echo "NOTA: Ya NO necesitas Tesseract. PaddleOCR se encarga del OCR."
echo ""
