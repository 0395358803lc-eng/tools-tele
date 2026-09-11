<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,8,15&height=180&section=header&text=Multi+TG+Manager&fontSize=50&fontColor=000000&fontAlignY=38&desc=Quan+ly+nhieu+tai+khoan+Telegram+tren+mot+giao+dien&descAlignY=58&descSize=14&animation=fadeIn" width="100%"/>

<div align="center">

![Cục bộ](https://img.shields.io/badge/C%E1%BB%A5c%20b%E1%BB%99-127.0.0.1-BFE7FF?style=for-the-badge&labelColor=1a1a1a)
![Backend](https://img.shields.io/badge/Backend-FastAPI-C8F7DC?style=for-the-badge&labelColor=1a1a1a)
![Frontend](https://img.shields.io/badge/Frontend-React+%2B+Vite-FFF0B8?style=for-the-badge&labelColor=1a1a1a)
![Máy tính](https://img.shields.io/badge/M%C3%A1y%20t%C3%ADnh-Windows+BAT-FFC7C7?style=for-the-badge&labelColor=1a1a1a)

</div>

<div align="center">
<i>Bảng điều khiển riêng tư để theo dõi trạng thái tài khoản, sửa hồ sơ, quản lý nhóm, tin nhắn, cảnh báo bảo mật và thao tác Telegram hàng loạt.</i>
</div>

---

## Tính năng

| Tính năng | Mô tả |
| --- | --- |
| Khởi động Windows một lần bấm | `start.bat` tạo môi trường Python, cài gói, build frontend và mở ứng dụng. |
| Máy chủ cục bộ | Chạy tại `127.0.0.1`, giao diện không bị công khai ra Internet khi dùng chế độ cục bộ. |
| Phiên Telegram | Dùng Telethon session được mã hóa và lưu trong SQL; tệp `.session` chỉ dùng để nhập hoặc dự phòng. |
| Công cụ hàng loạt | Đổi tên, bio, ảnh hồ sơ, tham gia/rời nhóm, thao tác tin nhắn và kiểm tra bảo mật hàng loạt. |
| Cổng mật khẩu | Đăng nhập dashboard bằng `APP_PASSWORD`, phiên đăng nhập có thể thu hồi và được lưu trong SQL với cookie same-site nghiêm ngặt. |

---

## Tải và chạy

```text
1. Cài Python 3.10+ từ https://python.org và chọn Add Python to PATH.
2. Cài Node.js 18+ từ https://nodejs.org.
3. Tải kho mã dưới dạng ZIP hoặc chạy: git clone https://github.com/0xnurrabby/multi-tg-manager.git
4. Mở thư mục dự án.
5. Nhấp đúp start.bat.
6. Điền backend\.env khi Notepad mở.
7. Lưu tệp, đóng Notepad rồi nhấp đúp start.bat lần nữa.
```

Ứng dụng mở tại `http://localhost:8000`.

---

## Cấu hình

Điền các giá trị sau trong `backend/.env`:

```env
TG_API_ID=your_api_id_from_my_telegram_org
TG_API_HASH=your_api_hash_from_my_telegram_org
APP_PASSWORD=change_me_to_a_long_password
SECRETS_ENCRYPTION_KEY=auto_generated_by_start_bat
SESSIONS_DIR=./sessions
DB_URL=sqlite+aiosqlite:///./app.db
# Production/Replit: đặt DATABASE_URL=postgresql://...
# Bắt buộc để mã hóa phiên Telegram và mật khẩu 2FA ghi nhớ trong SQL:
SECRETS_ENCRYPTION_KEY=<Fernet key>
```

Kiểm tra môi trường trên máy mới:

```powershell
python --version
node --version
```

---

## Cấu trúc dự án

```text
multi-tg-manager/
  start.bat                -> thiết lập lần đầu và khởi động máy chủ
  stop.bat                 -> dừng máy chủ cục bộ trên port 8000
  backend/                 -> FastAPI, mô hình SQL, Alembic, session và cấu hình môi trường
  backend/requirements.txt -> thư viện Python
  frontend/                -> giao diện React + Vite
  frontend/package.json    -> lệnh build/chạy frontend
```

---

## Production / Replit

Alembic là nguồn quản lý schema duy nhất. Mọi launcher được hỗ trợ đều chạy `alembic upgrade head` trước Uvicorn. Khi triển khai máy chủ, phải dùng PostgreSQL bền vững qua `DATABASE_URL`; không dùng filesystem tạm của deployment để lưu trạng thái runtime. Phiên Telegram và mật khẩu 2FA được mã hóa bằng `SECRETS_ENCRYPTION_KEY` trước khi ghi vào SQL.

Vì ứng dụng duy trì kết nối Telegram và listener dài hạn, hãy dùng một instance luôn bật kiểu Reserved VM/single-instance thay vì môi trường scale-to-zero. Các lệnh kiểm tra chính:

```bash
python scripts/production_check.py
python scripts/verify_release.py
# Trên máy có PostgreSQL binaries, chạy kiểm thử migration/backup thực tế:
bash scripts/verify_postgres_integration.sh
```

Sao lưu/khôi phục:

```bash
python scripts/backup_runtime.py --output backups/runtime.tar.gz
python scripts/restore_runtime.py backups/runtime.tar.gz --verify-only
# Dừng ứng dụng trước khi khôi phục thật:
python scripts/restore_runtime.py backups/runtime.tar.gz --force
```

`--include-env` chỉ đưa tệp `backend/.env` đang tồn tại vào bản sao lưu. Secret được nền tảng inject không tự động được lưu. Hãy sao lưu `SECRETS_ENCRYPTION_KEY` riêng và xem `PRODUCTION_RUNBOOK.md` để biết quy trình production/khôi phục sự cố.

## Lưu ý

- `backend/.env`, `backend/app.db` và `backend/sessions/*.session` là dữ liệu riêng tư. Hãy bảo vệ tệp session như mật khẩu.
- Đóng cửa sổ máy chủ hoặc chạy `stop.bat` để dừng ứng dụng.
- Chỉ quản lý các tài khoản bạn sở hữu hoặc được phép vận hành.

---

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,8,15&height=90&section=footer" width="100%"/>

<p align="center">
  <sub>Giấy phép MIT trừ khi có ghi chú khác. Tác giả gốc: <a href="https://github.com/0xnurrabby">0xnurrabby</a>.</sub>
</p>
