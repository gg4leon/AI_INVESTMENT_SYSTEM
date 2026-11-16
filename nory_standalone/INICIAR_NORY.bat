@echo off
setlocal
cd /d "%~dp0"
echo NORY 2.0 - DATOS PUBLICOS / CAPITAL Y OPERACIONES FICTICIOS
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo No se pudo crear el entorno. Instala Python 3.11 o superior y su lanzador py.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -c "from importlib.metadata import version; from pathlib import Path; assert all(version(n)==v for n,v in (line.split('==') for line in Path('requirements.txt').read_text().splitlines() if line and not line.startswith('#')))" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo No se pudieron instalar las dependencias. Revisa la conexion y ejecuta el comando indicado en README.md.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" run.py
if errorlevel 1 (
  echo Revisa el mensaje anterior y logs\nory.log.
  echo Si faltan dependencias: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
)
