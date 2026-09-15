@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%backend\.venv\Scripts\python.exe"

%SystemRoot%\System32\whoami.exe /groups | %SystemRoot%\System32\findstr.exe /C:"S-1-16-12288" >nul
if not errorlevel 1 goto elevated
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command "$p=Start-Process -FilePath '%~f0' -Verb RunAs -Wait -PassThru; exit $p.ExitCode"
exit /b %errorlevel%

:elevated
echo maintenance>%ROOT%.maintenance
echo [public] Maintenance mode ON.
%SystemRoot%\System32\schtasks.exe /End /TN MTM_Ngrok >nul 2>nul
%SystemRoot%\System32\taskkill.exe /IM ngrok.exe /F >nul 2>nul

if exist "%PY%" "%PY%" "%ROOT%scripts\graceful_stop.py" --port 8000 --timeout 20
if errorlevel 1 %SystemRoot%\System32\schtasks.exe /End /TN MTM_Backend >nul 2>nul

echo [public] Backend/ngrok stopped. Watchdog will not restart while .maintenance exists.
endlocal
exit /b 0