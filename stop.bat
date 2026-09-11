@echo off
chcp 65001 >nul
title Dừng Quản Lý Telegram Đa Tài Khoản
echo Đang dừng máy chủ trên cổng 8000...
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
  echo Đang dừng PID %%p
  taskkill /PID %%p /F >nul 2>nul
)
echo Hoàn tất.
timeout /t 2 >nul
