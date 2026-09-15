# Changelog

## 1.0.0 — Production baseline — 2026-09-15

- Supabase Auth + PostgreSQL production runtime.
- Multi-tenant ownership, anti-IDOR SQLAlchemy guard and RLS defense-in-depth.
- Encrypted Telegram sessions, Telegram API secrets, 2FA and proxy credentials.
- ADMIN dashboard, user lifecycle, force logout, quotas, audit and system health.
- Telegram account lifecycle, proxy primary/fallback, safe message retry and phone-check rebalance.
- CSV/XLS/XLSX preview, column mapping and authenticated exports.
- Automatic PostgreSQL backup/verify, retention, maintenance and restore tooling.
- Windows watchdog, graceful shutdown, fixed ngrok HTTPS domain and scheduled tasks.
- Rotating structured logs, request correlation, metrics and persistent operational alerts.
- Frontend route/module code splitting.
- Reproducible npm/Python dependency baselines and automated CI security checks.

### Database

- Alembic head: `1a2b3c4d5e6f`.

### Known operational limitation

- Windows services start automatically after the Admin user logs in. Running before login requires an elevated SYSTEM/Windows Service installation.
