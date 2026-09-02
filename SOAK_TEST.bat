@echo off
echo Multi TG Manager must already be running.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0soak_test.ps1" -Hours 8 -IntervalSeconds 30
if errorlevel 1 pause
