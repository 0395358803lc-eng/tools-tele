@echo off
setlocal EnableDelayedExpansion
set "ROOT=%~dp0"
set "NGROK=%ROOT%runtime\ngrok\ngrok.exe"
set "NGROK_CONFIG=%ROOT%runtime\ngrok\ngrok.yml"
set "PUBLIC_URL=https://bony-issue-ramrod.ngrok-free.dev"

if exist "%ROOT%.maintenance" exit /b 0
%SystemRoot%\System32\tasklist.exe /FI "IMAGENAME eq ngrok.exe" | %SystemRoot%\System32\findstr.exe /I "ngrok.exe" >nul
if not errorlevel 1 exit /b 0

if not exist "%NGROK%" exit /b 20
if not exist "%NGROK_CONFIG%" exit /b 21

set "BACKEND_OK=0"
for /l %%i in (1,1,45) do (
  curl.exe -fsS http://127.0.0.1:8000/api/health/ready >nul 2>nul && (set "BACKEND_OK=1" & goto backend_ready)
  %SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command "Start-Sleep -Seconds 2"
)
:backend_ready
if not "!BACKEND_OK!"=="1" exit /b 22

"%NGROK%" http --config="%NGROK_CONFIG%" --url=%PUBLIC_URL% http://127.0.0.1:8000 --log=stdout
exit /b %errorlevel%
