# Local isolated code runner

The FastAPI service never runs submitted code in-process. When enabled, it invokes the local Docker CLI to create a disposable `codeproof-runner:local` Linux container for each individual test case. The expected output stays in the API process and is never sent to the container. Candidate containers have no network, host mounts, Docker socket, application environment variables, or writable root filesystem. They run as UID 10001 with all Linux capabilities dropped, `no-new-privileges`, private IPC, memory/CPU/PID limits, bounded temporary files, and time/output limits. Python and C use fixed interpreter/compiler commands; no shell, compiler flags, package installation, or image choice comes from a request.

## Build and run locally (PowerShell)

From the repository root:

```powershell
docker build -t codeproof-runner:local .\backend\runner
$env:CODE_EXECUTION_ENABLED = 'true'
& .\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir .\backend --reload
```

The backend reads the ignored repository-root `.env`; the process environment value above overrides it. Keep `CODE_EXECUTION_ENABLED=false` until the image is built and Docker Desktop is using its Linux engine. The runner image and Docker daemon must be available to the backend OS account.

The default limits are a maximum of 2 concurrent case containers, 20 cases per question, 30 seconds per question batch, 8 seconds per case, 128 MiB memory, 0.5 CPU, 32 PIDs, 16 MiB writable workspace, and 32 KiB captured output. Lower these for local machines as needed; service code enforces a 10 second per-case ceiling and 20-case hard ceiling.

## Operational security limits

This is a local development foundation, not a claim of a formally audited sandbox. The trusted backend process needs Docker daemon access to create and remove containers; Docker daemon access is highly privileged and must never be exposed to candidates, browsers, or untrusted services. Candidate containers receive no daemon socket or bind mount. Docker Desktop's Linux VM, kernel, seccomp profile, and host configuration remain part of the trust boundary. Use a separate, least-privileged execution worker/host with patched kernels and monitoring before production use. The service rejects work when execution is disabled, the image/daemon is unavailable, or its bounded concurrency slots are full.

Each stored test-case input is passed to the program's standard input; trimmed standard output is compared with the expected output. No result is considered available until test cases finish. Compiler/runtime/timeout/resource-limit status is recorded per response; hidden inputs and expected outputs are never included in candidate response schemas. Candidate score is returned only when the assessment permits post-submission result visibility. Evaluator results are owner-scoped.

Opt-in Docker integration tests:

```powershell
$env:CODEPROOF_RUNNER_INTEGRATION = '1'
& .\backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider .\backend\tests\test_execution_integration.py
```
