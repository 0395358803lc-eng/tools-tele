@echo off
setlocal
set "ROOT=%~dp0"
set "NGROK=C:\Users\Admin\AppData\Local\Microsoft\WindowsApps\ngrok.exe"
set "PUBLIC_URL=https://bony-issue-ramrod.ngrok-free.dev"

if exist "%ROOT%.maintenance" exit /b 0
%SystemRoot%\System32\tasklist.exe /FI "IMAGENAME eq ngrok.exe" | %SystemRoot%\System32\findstr.exe /I "ngrok.exe" >nul
if not errorlevel 1 exit /b 0

if not exist "%NGROK%" exit /b 20
"%NGROK%" http --url=%PUBLIC_URL% http://127.0.0.1:8000 --log=stdout
exit /b %errorlevel%
