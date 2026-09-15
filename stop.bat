@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%backend\.venv\Scripts\python.exe"
echo Stopping server on port 8000 gracefully...
if exist "%PY%" (
  "%PY%" "%ROOT%scripts\graceful_stop.py" --port 8000 --timeout 20
) else (
  echo [LOI] Khong tim thay Python venv.
  exit /b 1
)
%SystemRoot%\System32\schtasks.exe /End /TN MTM_Backend >nul 2>nul
echo Done.
endlocal
exit /b 0
