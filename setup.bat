@echo off
cd /d "%~dp0"
echo === TSR Downloader — Instalación ===
echo.
python -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements.txt
echo.
echo Instalación completa. Ejecuta 'start.bat' para iniciar.
pause
