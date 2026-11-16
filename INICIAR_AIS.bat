@echo off
setlocal
cd /d "%~dp0"
echo ================================================
echo     AIS Investment Terminal v0.6
echo     SOLO SIMULACION - SIN OPERACIONES REALES
echo ================================================
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m streamlit run streamlit_app.py
) else (
  python -m streamlit run streamlit_app.py
)
if errorlevel 1 (
  echo.
  echo Si Streamlit no esta instalado: python -m pip install -r requirements.txt
  pause
)
