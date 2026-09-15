@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%backend\.venv\Scripts\python.exe"

echo maintenance>%ROOT%.maintenance
echo [public] Maintenance mode ON.
if exist "%PY%" "%PY%" "%ROOT%scripts\graceful_stop.py" --port 8000 --timeout 20
%SystemRoot%\System32\schtasks.exe /End /TN MTM_Backend >nul 2>nul
%SystemRoot%\System32\schtasks.exe /End /TN MTM_Ngrok >nul 2>nul
%SystemRoot%\System32\taskkill.exe /IM ngrok.exe /F >nul 2>nul

echo [public] Backend/ngrok stopped. Watchdog will not restart while .maintenance exists.
endlocal
exit /b 0
