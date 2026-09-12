# Sổ tay vận hành Production và Khôi phục sự cố

## 1. Điều kiện trước khi chạy production

Chỉ cho phép cấu hình production khi `python scripts/production_check.py --strict` thoát với mã 0. Sau migration, `python scripts/production_check.py --strict --check-db` cũng phải thoát 0 để chứng minh PostgreSQL kết nối được và schema đang ở Alembic head hiện tại.

Các giá trị runtime phải được cung cấp bên ngoài Git: `DATABASE_URL`, `APP_PASSWORD`, thông tin Telegram API, `SECRETS_ENCRYPTION_KEY`, và `COOKIE_SECURE=true`. Chỉ đặt `TRUST_PROXY_HEADERS=true` phía sau reverse proxy Replit/HTTPS đáng tin cậy. Giữ `ALLOWED_ORIGIN` trống khi deploy same-origin, trừ khi cần một production origin riêng.

Chỉ chạy một instance luôn hoạt động. Telegram client/listener có trạng thái; không dùng nhiều Uvicorn worker hoặc replica cho cùng tập tài khoản. Giữ `ENFORCE_SINGLE_INSTANCE=true`; PostgreSQL production dùng advisory lock để instance thứ hai fail startup thay vì tạo kết nối Telethon trùng lặp.

## 2. Triển khai PostgreSQL lần đầu

1. Cấp phát PostgreSQL bền vững và truyền `DATABASE_URL` vào runtime production.
2. Dừng app production trước khi migrate dữ liệu SQLite hiện có.
3. Lệnh kích hoạt ưu tiên: `python scripts/activate_production_database.py --copy-sqlite` sau khi `DATABASE_URL` đã có. Lệnh này áp dụng Alembic, kiểm tra schema, copy SQLite sang target PostgreSQL trống khi được yêu cầu, xác minh số dòng và tạo backup PostgreSQL đầu tiên mà không in URL database.
4. Nếu chỉ cần schema, bỏ `--copy-sqlite`. Sau khi hoàn tất toàn bộ cấu hình deployment, dùng `--strict-after` hoặc chạy riêng `python scripts/production_check.py --strict --check-db`.
5. Lệnh schema thủ công: `cd backend && python -m alembic upgrade head`.
6. Nếu chuyển từ SQLite, dry-run trước: `python scripts/migrate_sqlite_to_postgres.py --source backend/app.db --target "$DATABASE_URL" --dry-run`.
7. Chỉ copy thật vào PostgreSQL target trống, sau đó kiểm tra số dòng từng bảng và `alembic_version`.
8. Chạy `bash scripts/verify_postgres_integration.sh` trong môi trường maintenance/test, không chạy vào production database.

Alembic head dự kiến hiện tại là `91b8c7d6e5f4` cho tới khi có migration mới.

## 3. Quản lý khóa mã hóa

`SECRETS_ENCRYPTION_KEY` dùng để giải mã Telegram session và dữ liệu 2FA lưu trong SQL. Chỉ backup database là chưa đủ để khôi phục thảm họa.

Lưu Fernet key production trong secret store của nền tảng và giữ thêm một bản sao offline được bảo vệ. Không commit key, không đưa vào ticket/log và không rotate nếu chưa có kế hoạch re-encryption. Database phục hồi bằng sai key sẽ fail-closed và không giải mã được các bản ghi.

`backup_runtime.py --include-env` chỉ lấy file `backend/.env` thực sự tồn tại. Secret được nền tảng inject sẽ không tự động được đưa vào archive. Luôn kiểm tra trường `includes_env` trong output/manifest.

## 4. Quy trình backup

Với PostgreSQL production:

```bash
python scripts/backup_runtime.py --output /secure/mtm-runtime-$(date -u +%Y%m%dT%H%M%SZ).tar.gz
python scripts/restore_runtime.py /secure/<backup>.tar.gz --verify-only
```

Archive chứa PostgreSQL custom dump có kiểm tra toàn vẹn và các session artifact legacy còn tồn tại. Session/2FA đã mã hóa nằm trong database dump, nhưng Fernet key phải được backup riêng.

Giữ backup ngoài Git workspace, giới hạn quyền truy cập và sao chép sang lưu trữ bền vững. Không dùng filesystem tạm thời của deployment làm nơi backup duy nhất.

## 5. Quy trình restore

1. Dừng ứng dụng để không còn Telegram client hoặc DB writer hoạt động.
2. Xác minh archive trước: `python scripts/restore_runtime.py <archive> --verify-only`.
3. Cấp phát PostgreSQL target trống dành cho recovery.
4. Restore: `python scripts/restore_runtime.py <archive> --force --postgres-url "$RECOVERY_DATABASE_URL"`.
5. Cung cấp đúng `SECRETS_ENCRYPTION_KEY` production.
6. Cung cấp `APP_PASSWORD`, thông tin Telegram API, thiết lập cookie/proxy và `DATABASE_URL` đã restore.
7. Chạy `cd backend && python -m alembic current`; xác nhận đang ở head.
8. Chạy `python scripts/production_check.py --strict --check-db` và yêu cầu không có blocker.
9. Khởi động một Uvicorn worker, sau đó kiểm tra `/api/health/live` và `/api/health/ready`.
10. Xác minh khôi phục account/session trước khi cho phép thao tác hàng loạt.

## 6. Nghiệm thu sau khôi phục

Sau restore, xác minh đăng nhập dashboard, danh sách tài khoản, nạp Telegram session đã mã hóa, giải mã secret 2FA, các trang Tác vụ/Nhật ký/Hệ thống, lịch sử Target Check và readiness metrics. Kiểm thử end-to-end một tài khoản Telegram do người dùng kiểm soát trước khi khôi phục workload bình thường.

Nếu giải mã session báo ciphertext không giải mã được, không ghi đè bản ghi và không tạo key mới. Hãy phục hồi đúng Fernet key lịch sử.

## 7. Xác minh định kỳ

Trước release và sau thay đổi dependency/schema, chạy:

```bash
python scripts/verify_release.py
bash scripts/verify_postgres_integration.sh
python scripts/production_check.py --strict --check-db
```

Script PostgreSQL integration tạo instance test tạm thời và không được trỏ vào production. CI chạy release verification và một job riêng cho PostgreSQL migration/load/backup-restore.

## 8. Quy tắc xử lý sự cố

Nếu nghi ngờ lộ credential/session: dừng client của tài khoản bị ảnh hưởng, revoke Telegram session bằng ứng dụng Telegram chính thức, rotate thông tin đăng nhập dashboard, bảo toàn audit log và đánh giá riêng khả năng lộ Fernet key. Đổi Fernet key mà không re-encrypt dữ liệu cũ sẽ làm ciphertext hiện tại không đọc được.

Nếu database hỏng hoặc bị xóa nhầm: dừng writer trước, xác minh backup mới nhất, restore sang database recovery riêng, kiểm tra đạt rồi mới chuyển `DATABASE_URL`. Không restore trực tiếp đè lên bản production duy nhất trước khi recovery database được nghiệm thu.
