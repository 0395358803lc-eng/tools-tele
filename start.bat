@echo off
chcp 65001 >nul
title Quản Lý Telegram Đa Tài Khoản
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
if "!ROOT:~-1!"=="\" set "ROOT=!ROOT:~0,-1!"
cd /d "!ROOT!"

echo.
echo ============================================
echo   Quản Lý Telegram Đa Tài Khoản
echo   !ROOT!
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [LỖI] Không tìm thấy Python trong PATH.
  echo Cài Python 3.10+ từ https://python.org
  pause
  exit /b 1
)

set "VENV_PY=!ROOT!\backend\.venv\Scripts\python.exe"
if not exist "!VENV_PY!" (
  echo [thiết lập] Đang tạo môi trường ảo Python...
  python -m venv "!ROOT!\backend\.venv"
)

echo [kiểm tra] Đang xác minh gói Python...
"!VENV_PY!" -c "import fastapi, telethon, bcrypt, aiosqlite, alembic, cryptography" >nul 2>nul
set "DEPS_OK=!errorlevel!"
echo [kiểm tra] DEPS_OK=!DEPS_OK!

if not "!DEPS_OK!"=="0" (
  echo [thiết lập] Đang cài gói Python...
  "!VENV_PY!" -m pip install --upgrade pip
  "!VENV_PY!" -m pip install -r "!ROOT!\backend\requirements.txt"
  if errorlevel 1 (
    echo [LỖI] Cài đặt bằng pip thất bại.
    pause
    exit /b 1
  )
)

set "ENVFILE=!ROOT!\backend\.env"
set "ENVEXAMPLE=!ROOT!\backend\.env.example"
echo [kiểm tra] Đang tìm tệp env tại: !ENVFILE!

if not exist "!ENVFILE!" (
  echo [thiết lập] Đang tạo backend\.env từ .env.example...
  if not exist "!ENVEXAMPLE!" (
    echo [LỖI] Thiếu backend\.env.example.
    pause
    exit /b 1
  )
  copy /Y "!ENVEXAMPLE!" "!ENVFILE!" >nul
  "!VENV_PY!" -c "import re,pathlib,os; from cryptography.fernet import Fernet; p=pathlib.Path(os.environ['ENVFILE']); t=p.read_text(encoding='utf-8'); t=re.sub(r'SECRETS_ENCRYPTION_KEY=.*', 'SECRETS_ENCRYPTION_KEY='+Fernet.generate_key().decode(), t, count=1); p.write_text(t, encoding='utf-8')"
  echo.
  echo ============================================
  echo   LẦN CHẠY ĐẦU - hãy điền backend\.env
  echo ============================================
  echo   - TG_API_ID    ^(from https://my.telegram.org^)
  echo   - TG_API_HASH  ^(from https://my.telegram.org^)
  echo   - APP_PASSWORD ^(your login password^)
  echo.
  echo   Lưu Notepad, đóng lại rồi chạy start.bat lần nữa
  echo ============================================
  start "" notepad "!ENVFILE!"
  pause
  exit /b 0
) else (
  echo [kiểm tra] Đã tìm thấy backend\.env.
)

if not exist "!ROOT!\backend\static\index.html" (
  where node >nul 2>nul
  if errorlevel 1 (
    echo [LỖI] Không tìm thấy Node.js trong PATH. Cài Node 18+ từ https://nodejs.org
    pause
    exit /b 1
  )
  if not exist "!ROOT!\frontend\node_modules" (
    echo [thiết lập] Đang cài các gói frontend...
    pushd "!ROOT!\frontend"
    call npm install
    if errorlevel 1 (
      popd
      echo [LỖI] npm install thất bại.
      pause
      exit /b 1
    )
    popd
  )
  echo [build] Đang build frontend...
  pushd "!ROOT!\frontend"
  call npm run build
  if errorlevel 1 (
    popd
    echo [LỖI] Build frontend thất bại.
    pause
    exit /b 1
  )
  popd
)

echo.
echo ============================================
echo   Máy chủ: http://localhost:8000
echo   Đóng cửa sổ này để dừng máy chủ.
echo ============================================
echo.

start "" cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8000"

cd /d "!ROOT!\backend"
echo [cơ sở dữ liệu] Đang áp dụng migration...
"!VENV_PY!" -m alembic upgrade head
if errorlevel 1 (
  echo [LỖI] Migration cơ sở dữ liệu thất bại.
  pause
  exit /b 1
)
"!VENV_PY!" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo Máy chủ đã dừng.
pause
endlocal
