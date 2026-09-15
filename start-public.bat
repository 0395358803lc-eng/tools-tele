@echo off
setlocal EnableDelayedExpansion
set "ROOT=%~dp0"
set "PUBLIC_URL=https://bony-issue-ramrod.ngrok-free.dev"

if exist "%ROOT%.maintenance" del /q "%ROOT%.maintenance" >nul 2>nul
echo [public] Maintenance mode OFF.
%SystemRoot%\System32\schtasks.exe /Run /TN MTM_Backend >nul 2>nul
set "LOCAL_OK=0"
for /l %%i in (1,1,25) do (
  curl.exe -fsS http://127.0.0.1:8000/api/health/ready >nul 2>nul && (set "LOCAL_OK=1" & goto backend_ready)
  powershell.exe -NoProfile -Command "Start-Sleep -Seconds 2"
)
:backend_ready
if not "!LOCAL_OK!"=="1" (echo [LOI] Backend khong san sang.& exit /b 1)

%SystemRoot%\System32\schtasks.exe /Run /TN MTM_Ngrok >nul 2>nul
set "PUBLIC_OK=0"
for /l %%i in (1,1,20) do (
  curl.exe -k -fsS "%PUBLIC_URL%/api/health/live" >nul 2>nul && (set "PUBLIC_OK=1" & goto public_ready)
  powershell.exe -NoProfile -Command "Start-Sleep -Seconds 2"
)
:public_ready
if not "!PUBLIC_OK!"=="1" (echo [LOI] Ngrok domain chua san sang.& exit /b 2)
echo [public] %PUBLIC_URL%
start "" "%PUBLIC_URL%"
endlocal
exit /b 0
