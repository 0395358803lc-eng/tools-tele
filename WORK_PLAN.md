# Multi TG Manager — Kế hoạch công việc

Xác minh gần nhất: 2026-09-11  
Nhánh: `hardening-p0`

## P0 — Kiến trúc và trạng thái bền vững — HOÀN TẤT
- Đã loại bỏ scaffold mô phỏng/legacy gây nhầm lẫn và nguồn dữ liệu trùng lặp.
- Alembic là nguồn duy nhất quản lý schema; SQLite chỉ dùng local/dev, PostgreSQL là mục tiêu production.
- Telegram ID dùng `BIGINT` ở các vị trí cần thiết.
- Telegram `StringSession` và mật khẩu 2FA được mã hóa khi lưu trong SQL.
- Launcher production chạy migration trước khi phục vụ và xác minh Alembic head hiện tại.

## P1 — Độ tin cậy và vòng đời tác vụ — HOÀN TẤT
- Tác vụ hàng loạt và từng item được lưu trong SQL, hỗ trợ hủy, phục hồi trạng thái gián đoạn và chạy lại thủ công an toàn.
- FloodWait, lỗi vận hành, số lần reconnect và lịch sử health được lưu theo từng tài khoản.
- Đã có timeout cho bulk/API, giới hạn concurrency lúc startup/status và exponential reconnect backoff.
- Regression scheduler/load 100 tài khoản đạt trên SQLite và PostgreSQL.
- PostgreSQL advisory lock ngăn nhiều replica cùng điều khiển một tập tài khoản.

## P2 — Bảo mật và khả năng quan sát — HOÀN TẤT
- Phiên dashboard lưu SQL, rate-limit đăng nhập, kiểm tra CSRF/origin và security header đã được triển khai.
- Audit tự che credentials, OTP/2FA, nội dung tin nhắn và session secret.
- Coverage audit cho các route thay đổi dữ liệu được bảo vệ bằng regression test.
- Dashboard hiển thị health/FloodWait an toàn; lịch sử Target Check và các trang Tác vụ/Nhật ký/Hệ thống được lưu bền vững.
- Backup/restore có manifest kiểm tra toàn vẹn; mất khóa mã hóa sẽ fail-closed.

## P3 — Nghiệm thu tự động — HOÀN TẤT
- Bộ regression hiện tại: 48/48 test đạt.
- Nghiệm thu runtime cho auth/CSRF/session/rate-limit đạt.
- Frontend production build và TypeScript typecheck đạt.
- PostgreSQL integration: 10/10 giai đoạn đạt, gồm singleton lock, tải 100 tài khoản và backup/restore.
- Kiểm tra hygiene repo và tương thích dependency đạt.

## P4 — Cấp phát production và nghiệm thu thực tế — ĐÃ CHUẨN BỊ MỘT PHẦN
1. PostgreSQL production phải là cơ sở dữ liệu bền vững và được truyền qua `DATABASE_URL`.
2. `APP_PASSWORD` phải là mật khẩu mạnh và được đặt ngoài Git.
3. Thông tin Telegram API phải được cấu hình đúng trước khi chạy chức năng Telegram.
4. `SECRETS_ENCRYPTION_KEY` phải là Fernet key hợp lệ, lưu trong secret store và có bản sao offline an toàn.
5. Production HTTPS phải dùng `COOKIE_SECURE=true`.
6. Với Replit, chọn kiểu triển khai luôn hoạt động/Reserved VM thay vì Autoscale scale-to-zero.
7. Chỉ bật `TRUST_PROXY_HEADERS=true` khi đứng sau reverse proxy HTTPS đáng tin cậy.
8. Chạy `python scripts/production_check.py --strict --check-db` và yêu cầu không còn blocker.
9. Chỉ publish một instance; xác minh `/api/health/live` và `/api/health/ready`.
10. Chạy nghiệm thu không phá hủy, sau đó kiểm thử OTP/QR/2FA/session restore/reconnect/FloodWait bằng tài khoản Telegram do người dùng kiểm soát.
11. Nghiệm thu tải ở 20, 50 và 100 tài khoản, theo dõi FloodWait, CPU, RAM và kết nối PostgreSQL.
12. Thực hiện diễn tập backup/restore production với khóa mã hóa được giữ riêng.

Không dùng PostgreSQL integration tạm thời làm production, không commit secret và không bỏ qua strict preflight để làm deployment trông như đã sẵn sàng.
