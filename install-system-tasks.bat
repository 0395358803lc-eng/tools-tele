@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%backend\.venv\Scripts\python.exe"
set "SCRIPT=%ROOT%scripts\install_windows_tasks.py"

if not exist "%PY%" exit /b 10
%SystemRoot%\System32\whoami.exe /groups | %SystemRoot%\System32\findstr.exe /C:"S-1-16-12288" >nul
if not errorlevel 1 goto elevated

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command ^
  "$q=[char]34; $arg=$q+'%SCRIPT%'+$q; $p=Start-Process -FilePath '%PY%' -ArgumentList $arg,'--apply-system' -Verb RunAs -Wait -PassThru; exit $p.ExitCode"
exit /b %errorlevel%

:elevated
"%PY%" "%SCRIPT%" --apply-system
exit /b %errorlevel%
