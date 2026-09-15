@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%backend\.venv\Scripts\python.exe"

if exist "%ROOT%.maintenance" exit /b 0
%SystemRoot%\System32\netstat.exe -aon | %SystemRoot%\System32\findstr.exe ":8000" | %SystemRoot%\System32\findstr.exe "LISTENING" >nul
if not errorlevel 1 exit /b 0

cd /d "%ROOT%"
if not exist "%PY%" exit /b 10
"%PY%" "%ROOT%scripts\production_check.py" --strict --check-db
if errorlevel 1 exit /b 11

cd /d "%ROOT%backend"
"%PY%" -m alembic upgrade head
if errorlevel 1 exit /b 12
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
exit /b %errorlevel%
