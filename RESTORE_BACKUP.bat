@echo off
setlocal
set "ROOT=%~dp0"
set /p "BACKUP=Backup folder name (from data\backups): "
if "%BACKUP%"=="" exit /b 1
cd /d "%ROOT%backend"
"%ROOT%backend\.venv\Scripts\python.exe" restore_backup.py "%BACKUP%"
if errorlevel 1 (
  echo Restore failed. The running app must be stopped first.
  pause
  exit /b 1
)
pause
