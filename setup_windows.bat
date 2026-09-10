@echo off
REM ========================================
REM INSTALACIÓN PORTAL OCR - WINDOWS
REM Portal de Gestión Huella de Carbono
REM Requiere: Python 3.13 instalado
REM ========================================

cls
echo.
echo ========================================
echo INSTALACION: Portal OCR - Hiberus
echo ========================================
echo.

REM 1. Buscar Python 3.13
echo [1/4] Buscando Python 3.13...
set PYTHON_PATH=
where python >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do (
        echo     Encontrado: Python %%v
        echo %%v | findstr /B "3.13" >nul
        if not errorlevel 1 (
            set PYTHON_PATH=python
        )
    )
)

if "%PYTHON_PATH%"=="" (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
        set PYTHON_PATH=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
    )
)

if "%PYTHON_PATH%"=="" (
    echo ❌ Python 3.13 no encontrado.
    echo    PaddleOCR requiere Python 3.9-3.13
    echo    Descargar desde: https://www.python.org/downloads/release/python-3130/
    pause
    exit /b 1
)
echo ✅ Python 3.13 detectado: %PYTHON_PATH%
echo.

REM 2. Crear entorno virtual
echo [2/4] Creando entorno virtual...
if not exist "venv" (
    "%PYTHON_PATH%" -m venv venv
    echo ✅ Entorno virtual creado
) else (
    echo ✅ Entorno virtual ya existe
)
echo.

REM 3. Actualizar pip
echo [3/4] Actualizando pip...
.\venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
echo ✅ pip actualizado
echo.

REM 4. Instalar dependencias
echo [4/4] Instalando dependencias (PaddleOCR + Flask)...
.\venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo ❌ Error instalando dependencias
    pause
    exit /b 1
)
echo ✅ Dependencias instaladas (incluye PaddleOCR)
echo.

echo.
echo ========================================
echo ✅ INSTALACIÓN COMPLETADA
echo ========================================
echo.
echo PRÓXIMO PASO:
echo   Ejecuta: .\venv\Scripts\python.exe app.py
echo   Abre en navegador: http://localhost:5000
echo.
echo NOTA: Ya NO necesitas Tesseract. PaddleOCR se encarga del OCR.
echo.
pause
