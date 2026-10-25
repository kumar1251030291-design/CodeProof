# Authentication and database diagnosis

## What the current local configuration targets

The frontend has no `VITE_API_BASE_URL` in `frontend/.env.local`, so Vite uses its local default, `http://127.0.0.1:8000`. The root `.env` configures `DATABASE_URL` to local PostgreSQL at `127.0.0.1:5432`, database `codeproof`. Its `SUPABASE_URL` project reference matches the frontend Supabase Auth project. These checks read only URL scheme, host, database name, and project reference; credentials were not displayed.

During diagnosis, the local API returned HTTP 200 from `/health`, while `/api/v1/health/database` did not answer within three seconds. The `/api/v1/me` endpoint verifies the Supabase token, then queries and provisions `user_profiles` and `user_roles` in the configured PostgreSQL database. The database connection had no explicit timeout, and frontend `fetch` calls also had no timeout. A stalled DB connection therefore left the access check loading indefinitely.

The database inspected in the Supabase SQL editor is not the database currently configured for this local backend. The `CodeProof(id, created_at)` table is not part of the SQLAlchemy model or Alembic chain. Its presence or the absence of `alembic_version` there does not tell us whether the local `codeproof` database is migrated. No database URL was changed.

## Safe local checks

From the repository root, verify that Docker Compose's existing local Postgres service is running without printing credentials:

```powershell
docker compose ps db
```

If the local database is intentionally in use, start only that declared local service:

```powershell
docker compose up -d db
```

Then, from `backend`, inspect migration state. Both commands are read-only:

```powershell
python -m alembic history
python -m alembic current
```

The backend now bounds PostgreSQL connection and pool waits. If `current` reports a connection error, first confirm the target host and database name using a password-redacting check, plus DNS/network/SSL settings. Do not use `stamp head` or create tables manually.

## Schema and migration coverage

The Alembic chain creates the application tables for assessments, users and roles, questions and test cases, access grants and rate limits, attempts and responses, and follow-up interviews and questions. The revision chain has one head, `b7c8d9e0f1a2`, and its complete DDL renders offline. These migrations have not been applied to the inspected Supabase database or the configured local database as part of this diagnosis.

If the intended application database is Supabase Postgres, compare the exact project reference and database host with the intended project, confirm backups and access, then review `alembic current` and `alembic history` against that target. Only after that verification should an operator approve applying `python -m alembic upgrade head` from `backend`. This work does not authorize or perform that migration.

## Profile and evaluator provisioning

Every authenticated profile receives the candidate role by default. Evaluator role is granted only when the authenticated Supabase user UUID is in backend-only `EVALUATOR_USER_IDS`, configured as a JSON array such as `[]` or `["<approved-user-uuid>"]`. The frontend role selection cannot grant evaluator access. Legacy evaluator rows created by the old blanket role backfill are ignored unless the UUID is in this allowlist; no role rows are deleted. Candidate and evaluator records stay in the existing database, and this change does not alter table grants or RLS policies.
