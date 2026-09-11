# Multi TG Manager — Biên bản nghiệm thu kỹ thuật

Cập nhật: 2026-09-11

## Trạng thái nghiệm thu hiện tại

Codebase đã đạt điều kiện vận hành single-user/self-hosted sau các hạng mục hardening P0-P3 bên dưới. Việc publish production chỉ được coi là đạt khi môi trường deployment cung cấp PostgreSQL bền vững, secret cần thiết và kiểu chạy luôn hoạt động phù hợp với kết nối Telegram dài hạn.

## P0 hoàn tất — bảo mật và kiến trúc

- Đã loại bỏ source tree mô phỏng/legacy và thiết lập một nguồn frontend/backend duy nhất.
- Thay signed-cookie-only auth bằng application session có thể revoke và lưu SQL.
- Bổ sung rate-limit đăng nhập bền vững.
- Chuyển secret 2FA được ghi nhớ sang SQL mã hóa Fernet.
- Chuyển trạng thái xác thực Telethon sang `StringSession` mã hóa Fernet trong SQL; file `.session` chỉ còn dùng cho import/fallback.
- Loại bỏ hành vi tự động rời nhóm có tính phá hủy.
- Bổ sung cờ xác nhận rõ ràng cho thao tác hàng loạt nguy hiểm.
- Bổ sung kiểm tra origin/CSRF, SameSite cookie nghiêm ngặt và security header.
- Production CORS mặc định same-origin; localhost dev origin chỉ được thêm ngoài production, strict preflight từ chối dev origin trong production.
- Bổ sung giới hạn upload và kiểm tra toàn vẹn SQLite session.

## P1 hoàn tất — SQL và độ tin cậy

- Alembic là nguồn duy nhất quản lý schema và được chạy trước mỗi lần server khởi động theo đường chuẩn.
- SQLite được hỗ trợ cho phát triển local; PostgreSQL là đường production.
- Telegram ID dùng `BIGINT` tại các trường cần thiết.
- Bulk job và item theo từng tài khoản được lưu với trạng thái, số lần thử, kết quả, runner ID và heartbeat.
- Có thể quan sát yêu cầu hủy qua SQL; job stale được phục hồi thành `interrupted`.
- Chỉ các job có thể tái dựng an toàn mới cho Retry (`group_join`, `group_leave`, `group_leave_target`, `message_view`, `terminate_other_sessions`). Restart không tự phát lại hành động của người dùng.
- Job parameter lưu bền vững được sanitize tại biên SQL; message text/password/token/code được redacted.
- Vòng đời tài khoản dùng status rõ ràng và status history; xóa tài khoản dùng soft-delete.
- Kết quả Target Check được lưu SQL với API lịch sử/chi tiết.
- OTP/QR pending client tự hết hạn.
- Runtime settings được nạp lại từ SQL sau restart.
- Lỗi Telegram được phân loại thành authentication/network/FloodWait/permanent-action.

## P2 hoàn tất — UX và an toàn vận hành

- Đã bổ sung các trang Tác vụ, Nhật ký và Hệ thống.
- Target Checker hiển thị lịch sử đã lưu với số lượng có/không/bỏ qua/lỗi và chi tiết theo tài khoản mà không cần gọi lại Telegram.
- Dashboard hiển thị FloodWait countdown, reconnect attempts và lỗi đã sanitize; có bộ lọc FloodWait/Vấn đề.
- Audit server-side redaction bao phủ password, OTP/code, token, secret, hash và nội dung tin nhắn.
- CSV import hỗ trợ quoted separator, escaped quote, CRLF và newline trong trường.
- Object URL cho preview ảnh được revoke đúng cách.
- Loại bỏ các trường giả `is_online` / `last_seen` thay vì hiển thị dữ liệu không được cập nhật thật.

## P3 hoàn tất — recovery, observability và nghiệm thu

- Backup/restore runtime hỗ trợ SQLite và PostgreSQL, SHA-256 manifest, giải nén an toàn và pre-restore copy.
- Có `/api/health/live`, strict `/api/health/ready`, và `/api/system/status` được bảo vệ.
- Production readiness kiểm tra Alembic schema hiện tại, app auth, cấu hình Telegram API, encryption key và PostgreSQL bền vững khi `NODE_ENV=production`.
- Có request ID, log thời lượng request và security header mà không log body/query value nhạy cảm.
- Có script release verification và PostgreSQL integration tái sử dụng.
- `activate_production_database.py` có thể áp dụng Alembic, tùy chọn copy SQLite vào PostgreSQL target trống, xác minh row count, tạo backup đầu tiên và chạy DB preflight mà không in database URL.
- Có GitHub Actions workflow xác minh release.
- Production launcher chạy strict config preflight trước Alembic, sau migration xác minh PostgreSQL/schema head và chỉ chạy một Uvicorn worker.
- Log production xuất JSON stdout; metric kiểu Prometheus nội bộ có tại `/api/system/metrics` và được bảo vệ.

## Cổng xác minh

Chạy từ `artifacts/multi-tg-manager`:

```bash
python scripts/verify_release.py
python scripts/verify_runtime_acceptance.py
bash scripts/verify_postgres_integration.sh
python scripts/production_check.py
python scripts/activate_production_database.py --help
python scripts/verify_bulk_load.py --accounts 100 --concurrency 20
```

Kết quả nghiệm thu gần nhất:

- Python regression suite: 48/48 đạt.
- Frontend Vite production build: đạt.
- Workspace TypeScript typecheck: đạt.
- Kiểm tra tương thích dependency Python (`uv pip check`): đạt.
- Audit dependency frontend/workspace: không ghi nhận lỗ hổng đã biết trong lần kiểm tra gần nhất.
- Uvicorn runtime smoke test: đạt.
- Runtime acceptance có xác thực: đạt cho login cookie, bảo vệ System/metrics, chặn CSRF cross-site, revoke session và rate-limit đăng nhập bền vững.
- Concurrent liveness: 100/100 HTTP 200 với 20 worker kiểm tra.
- PostgreSQL integration tạm thời: 10/10 giai đoạn đạt, gồm strict DB preflight, singleton advisory lock, scheduler 100 tài khoản và backup/restore.
- SQLite -> PostgreSQL typed migration: đạt cho BIGINT, boolean và JSON.
- PostgreSQL pool có giới hạn/cấu hình được (`DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=5`, timeout 30 giây, recycle 30 phút mặc định); SQLite không nhận tùy chọn pool PostgreSQL.
- PostgreSQL advisory lock ngăn instance thứ hai khởi động trên cùng production database; việc nhả lock được regression-test.
- Strict production preflight coi Replit Autoscale là blocker đối với workload Telethon dài hạn và yêu cầu `ENFORCE_SINGLE_INSTANCE=true`.
- Production readiness cũng fail nếu singleton guard bị tắt, kể cả khi Uvicorn chạy ngoài production launcher.
- Coverage của `.env.example` được regression-test với mọi trường `Settings` và từ chối giá trị trông giống secret thật.
- PostgreSQL backup -> verify -> restore: đạt, gồm cả dữ liệu load 100 tài khoản.
- Backup manifest báo đúng việc có/không chứa `backend/.env`; secret do nền tảng inject không được tự động đưa vào backup và `SECRETS_ENCRYPTION_KEY` phải backup riêng.
- SQLite bulk scheduler load: 100/100 thành công ở concurrency 20 trong lần đo đã ghi nhận.
- PostgreSQL bulk scheduler load: 100/100 thành công ở concurrency 20 trong các lần đo đã ghi nhận.
- Bulk action có `TG_RPC_TIMEOUT_SECONDS` (mặc định 45 giây); timeout được lưu thành `TimeoutError` thay vì treo job.
- API handler không streaming có `API_REQUEST_TIMEOUT_SECONDS` (mặc định 60 giây) và trả HTTP 504 kèm request-id/security header nếu bị treo.
- Refresh trạng thái nền chạy với `STATUS_CONCURRENCY` giới hạn (mặc định 10), tránh một account chậm làm tuần tự toàn bộ fleet.
- Startup 100 account được regression-test với bounded concurrency; account banned/deactivated/soft-deleted không tự khởi động.
- FloodWait persistence/expiry và reconnect counter được regression-test. Exponential reconnect backoff với jitter giới hạn tránh reconnect đồng loạt.
- Sai encryption key fail-closed cho cả Telegram session và 2FA secret.
- Generic API error không trả raw exception text; lỗi Telegram đã biết vẫn thân thiện với người dùng, chi tiết không biết chỉ ở server.
- Account API sanitize persisted operational error trước khi trả browser.
- Lifecycle auth/import và xóa GoneAccount history đều được audit mà không lưu OTP, 2FA password, QR token, session bytes hoặc API hash.
- Thay đổi read/backfill security message được audit bằng metadata/count, không lưu nội dung message.
- QR/OTP cleanup được regression-test: pending stale hết hạn, QR cancel không rò `CancelledError`, background startup session-sync được cancel/await lúc shutdown.
- Timestamp UTC backend dùng helper tương thích Python 3.13 thay cho `datetime.utcnow()` đã deprecated.

## Điều kiện còn phụ thuộc môi trường trước khi publish production

`scripts/production_check.py --strict` phải đạt trước release. Môi trường production phải bảo đảm:

1. PostgreSQL bền vững qua `DATABASE_URL`.
2. `APP_PASSWORD` mạnh.
3. Thông tin Telegram API hợp lệ.
4. Fernet `SECRETS_ENCRYPTION_KEY` hợp lệ và giữ ngoài Git.
5. `COOKIE_SECURE=true` cho HTTPS production.
6. `TRUST_PROXY_HEADERS=true` chỉ khi đứng sau reverse proxy HTTPS đáng tin cậy.
7. Kiểu deployment luôn hoạt động phù hợp với kết nối Telethon dài hạn, ví dụ Reserved VM trên Replit.

Không tạo credential production giả và không dùng PostgreSQL integration tạm thời làm production database.

## Sổ tay vận hành

Cấp phát production, migration PostgreSQL, quản lý encryption key, backup/restore và nghiệm thu disaster recovery được mô tả trong `PRODUCTION_RUNBOOK.md`.
