# CodeProof production deployment

This deploys the existing Vite frontend to Vercel and the existing FastAPI backend to Render. Use the existing Supabase project and database. Do not enable candidate code execution in the public API service.

## Required production settings

Configure values in the hosting provider dashboards; do not put secrets in this repository.

### Render backend

- `DATABASE_URL`: the existing production PostgreSQL connection URL.
- `SUPABASE_URL`: existing Supabase project URL.
- `SUPABASE_JWT_AUDIENCE`: `authenticated`.
- `SUPABASE_JWT_SECRET`: only if the project uses legacy HS256 JWTs; leave unset for JWKS verification.
- `CORS_ORIGINS`: JSON list containing the exact Vercel production origin, for example `["https://<assigned-vercel-hostname>"]`. Add a preview origin only if that preview must access production data.
- `AI_PROVIDER`: `openai` or `gemini`.
- `OPENAI_API_KEY` and `AI_MODEL`: required when `AI_PROVIDER=openai`.
- `GEMINI_API_KEY` and `GEMINI_MODEL`: required when `AI_PROVIDER=gemini`.
- `AI_TIMEOUT_SECONDS`: provider timeout, normally `30`.
- `GEMINI_TIMEOUT_SECONDS`: candidate assistant timeout, normally `25`.
- `FOLLOW_UP_QUESTION_COUNT`: integer from `1` to `5`; defaults to `3`.
- `CODE_EXECUTION_ENABLED`: `false`.

The frontend uses only public Supabase configuration. Never add an AI credential, JWT signing secret, service role key, database URL, or runner credential to a `VITE_` variable.

### Vercel frontend

- `VITE_API_BASE_URL`: assigned Render API origin, with no `/api/v1` suffix.
- `VITE_SUPABASE_URL`: existing Supabase project URL.
- `VITE_SUPABASE_PUBLISHABLE_KEY`: Supabase publishable/anon key.

## Vercel setup

1. Create a Vercel project from the reviewed GitHub repository and set **Root Directory** to `frontend`.
2. Use the Vite preset, install command `npm ci`, build command `npm run build`, and output directory `dist`.
3. Add the three `VITE_` settings above for Production. Add Preview values only if preview deployments should use a non-production API; do not point an untrusted preview build at production candidate data.
4. Deploy and copy the hostname assigned by Vercel. `frontend/vercel.json` rewrites SPA paths to `index.html`, so direct links to client routes load the app.
5. Add the exact production Vercel origin to Render's `CORS_ORIGINS` value before testing authenticated requests.

## Render setup

1. Create a Blueprint from the reviewed repository using `render.yaml`, or create the backend web service manually with root directory `backend`.
2. The backend build command is `pip install -r requirements.txt`; the start command is `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. The health check is `/api/v1/health/database`.
3. Set the production environment variables listed above in the Render dashboard. Set `CORS_ORIGINS` after Vercel assigns its URL. Keep `CODE_EXECUTION_ENABLED=false`.
4. Confirm the service points to the existing Supabase/PostgreSQL project. Do not create or reset a database as part of deployment.
5. `render.yaml` runs `alembic upgrade head` as a pre-deploy step. Confirm the Render service can reach the existing database and take the provider's normal database backup before deploying a schema change.
6. Wait for the database health check to pass, then copy the assigned Render service origin into Vercel's `VITE_API_BASE_URL` and redeploy the frontend.

## Database migration

The new migration is `b7c8d9e0f1a2_add_follow_up_interviews.py`. Render applies it before starting a deployment. For a controlled manual run from the repository root, configure the same backend environment and run:

```powershell
cd backend
alembic upgrade head
```

Do not edit or rerun historical migrations against an already migrated database. To inspect the migration plan first, run `alembic history` and `alembic current` with the production connection configured.

## Post-deploy smoke checks

1. `GET <Render origin>/api/v1/health/database` returns HTTP 200 and `database: connected`.
2. `GET <Render origin>/api/v1/health/auth` reports auth readiness without returning signing-key material.
3. Open the Vercel origin directly at `/`, refresh a nested SPA route, and confirm the app loads.
4. Sign in with candidate and evaluator accounts; verify the API health indicator and authenticated dashboard load.
5. Submit a test assessment using non-sensitive test content. Verify coding status remains separate from follow-up interview status.
6. Generate, save, resume, and submit the follow-up interview. Verify another candidate cannot read its data.
7. As the owning evaluator, review answers, save a private note, add a question, and confirm the candidate can answer it. Confirm a different evaluator cannot read the interview.
8. Confirm the candidate cannot see private evaluator notes and interview scoring does not alter the coding score.
9. Confirm the runner remains disabled and code submission reports execution unavailable rather than running in the API process.
10. Check browser network requests and deployment logs for accidental secret values; never copy secrets into issue reports or screenshots.

## Publishing reviewed changes

After reviewing the final diff and approving the proposed commit, run these commands from the repository root. Review the staged file list before committing and do not stage `.env`, local databases, candidate exports, or generated reports.

```powershell
git status --short
git diff --check
git add DEPLOYMENT.md .env.example backend/.env.example render.yaml frontend/vercel.json frontend/src/pages/DashboardExperience.tsx frontend/src/pages/EvaluatorResults.css frontend/src/services/api.ts frontend/vite.config.ts backend/app/api/follow_up_interviews.py backend/app/core/config.py backend/app/main.py backend/app/models.py backend/migrations/versions/b7c8d9e0f1a2_add_follow_up_interviews.py backend/tests/test_follow_up_interviews.py
git diff --cached --stat
git diff --cached
git commit -m "Add candidate follow-up interviews"
git push origin main
```

If the worktree contains additional user changes, stage only the paths approved for this feature and preserve those changes separately.
