@echo off
title NominaBoard - Servidor

echo.
echo  ============================================
echo   NominaBoard - Iniciando servidor de red
echo  ============================================
echo.

:: Obtener IP de red
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"192.168"') do (
    set IP=%%a
    goto :found
)
:found
set IP=%IP: =%

echo  La aplicacion estara disponible en:
echo.
echo    Desde esta PC:      http://localhost:8000/login.html
echo    Desde la red:       http://%IP%:8000/login.html
echo.
echo  Comparte el enlace de red con tus companeros.
echo  Presiona Ctrl+C para detener el servidor.
echo.

cd /d "%~dp0backend"
call "%~dp0.venv\Scripts\activate.bat"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

pause
