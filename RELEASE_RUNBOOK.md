# Release Runbook

## Release gate

A release is allowed only when all of these pass:

1. `npm ci` and `npm audit --audit-level=high`.
2. `pip check` and `pip-audit -r backend/requirements-lock.txt`.
3. Frontend production build.
4. Full Python regression suite.
5. Backend compile check.
6. Runtime secret exposure scan.
7. Backup + verify before database migration.
8. Strict production preflight after deployment.
9. `scripts/production_acceptance.py` after restart.

## Standard deployment

1. Create and verify a runtime backup.
2. Enable maintenance using `stop-public.bat`.
3. Apply Alembic migration from `backend/`.
4. Build frontend from the committed lockfile with `npm ci && npm run build`.
5. Run regression tests and security audits.
6. Start with `start-public.bat`.
7. Run strict preflight and production acceptance.
8. Confirm health version, Git SHA and Alembic revision.

## Rollback

Rollback is deliberately not one-click because database downgrades can destroy data.

1. Put the app into maintenance mode.
2. Identify the last known-good Git tag/commit and its Alembic revision.
3. If the failed release did not change schema, restore source/frontend to that Git tag and restart.
4. If schema changed, restore the verified pre-release PostgreSQL backup rather than blindly running `alembic downgrade`.
5. Restore the matching `.encryption.key` and tenant sessions only from the same backup set when required.
6. Run strict preflight and production acceptance before reopening public access.

Never restore `.env` from an archive; runtime secrets are managed separately.

## Versioning

- Semantic version: `APP_VERSION` / package version.
- Source identity: Git commit SHA from `/api/health`.
- Schema identity: Alembic revision from `/api/health`.
- Build timestamp: frontend static build timestamp.

## Branch policy

- `main`: last reviewed production line.
- `production/*`: release candidates and production baseline work.
- `develop` / feature branches: normal development.
- Do not force-push `main` or a production tag.
- Merge to `main` only after CI, backup, strict preflight and production acceptance pass.
- Dependency updates should arrive through Dependabot pull requests and pass the same CI gate.

## Windows unattended startup

For production, install the MTM scheduled tasks under the Windows `SYSTEM` account so the app starts before an interactive user signs in.

1. Run `install-system-tasks.bat` and approve the Windows UAC prompt.
2. The installer stages an isolated ngrok runtime under ignored `runtime/ngrok/` and restricts its ACL.
3. `MTM_Backend` and `MTM_Ngrok` use boot triggers; ngrok waits for backend readiness before opening the tunnel.
4. `MTM_Watchdog` runs every two minutes and uses a restart circuit breaker (3 attempts per 15 minutes).
5. Daily backup and maintenance tasks also run as `SYSTEM`.
6. Run `scripts/verify_windows_boot_mode.py` after installation and after a cold boot.

The legacy per-user Startup shortcut is removed by the SYSTEM installer to prevent duplicate processes.
