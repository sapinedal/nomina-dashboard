@echo off
REM Lanzador en segundo plano de NominaBoard (arranque automatico).
REM Escucha en 0.0.0.0 para que sea accesible desde toda la red local.
cd /d "%~dp0backend"
call "%~dp0.venv\Scripts\activate.bat"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
