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
