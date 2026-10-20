"""Bounded Docker runner orchestration. Candidate code runs only in disposable containers."""

import json
import subprocess
import threading
import time
from dataclasses import dataclass

from app.core.config import settings

_slots = threading.BoundedSemaphore(max(1, settings.code_runner_max_concurrency))
_MAX_SOURCE = 100_000
_MAX_STDIN = 65_536
MAX_TEST_CASES = 20
_MAX_ATTEMPT_SECONDS = 30.0


@dataclass(frozen=True)
class CaseExecution:
    status: str
    output: str
    duration_ms: int


class RunnerUnavailable(RuntimeError):
    pass


def _docker(*args: str, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RunnerUnavailable("Isolated execution service is unavailable") from None


def _ensure_runner_image() -> None:
    result = _docker("image", "inspect", settings.code_runner_image)
    if result.returncode != 0:
        raise RunnerUnavailable("Isolated execution image is unavailable")


def _create_container() -> str:
    result = _docker(
        "create", "--interactive", "--rm", "--network", "none", "--read-only",
        "--user", "10001:10001", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true", "--pids-limit", "32",
        "--memory", "128m", "--memory-swap", "128m", "--cpus", "0.5",
        "--ulimit", "cpu=3:3", "--ulimit", "fsize=1048576:1048576",
        "--ulimit", "core=0:0", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=8m",
        "--tmpfs", "/workspace:rw,nosuid,nodev,exec,size=16m,mode=1777",
        "--log-driver", "none", settings.code_runner_image,
    )
    container_id = result.stdout.strip()
    if result.returncode != 0 or not container_id or len(container_id) > 128:
        raise RunnerUnavailable("Could not create an isolated execution container")
    return container_id


def _remove_container(container_id: str) -> None:
    # The ID comes directly from `docker create`, never from a request.
    _docker("rm", "--force", container_id)


def run_case(language: str, source: str, input_data: str, *, timeout_seconds: float) -> CaseExecution:
    """Execute one test case; only its input and candidate source enter the sandbox."""
    if not settings.code_execution_enabled:
        raise RunnerUnavailable("Code execution is disabled by backend configuration")
    if language not in {"python", "c"}:
        raise ValueError("Unsupported execution language")
    source_size = len(source.encode("utf-8"))
    input_size = len(input_data.encode("utf-8"))
    if source_size == 0 or source_size > _MAX_SOURCE or input_size > _MAX_STDIN:
        raise ValueError("Submission exceeds the execution limits")
    if not _slots.acquire(blocking=False):
        raise RunnerUnavailable("Execution capacity is busy; retry later")
    container_id: str | None = None
    started = time.monotonic()
    try:
        _ensure_runner_image()
        container_id = _create_container()
        payload = json.dumps({"language": language, "source": source, "stdin": input_data}).encode("utf-8")
        process = subprocess.Popen(
            ["docker", "start", "--attach", "--interactive", container_id],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = process.communicate(payload, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            _docker("kill", container_id)
            return CaseExecution("timeout", "Execution exceeded the time limit.", int((time.monotonic() - started) * 1000))
        if process.returncode == 137:
            return CaseExecution("resource_limit", "Execution exceeded a resource limit.", int((time.monotonic() - started) * 1000))
        if process.returncode != 0:
            raise RunnerUnavailable("Isolated execution failed")
        if len(stdout) > 40_000:
            return CaseExecution("resource_limit", "Execution output exceeded the limit.", int((time.monotonic() - started) * 1000))
        try:
            result = json.loads(stdout)
            status = result["status"]
            output = result.get("output", "")
            if status not in {"completed", "compile_error", "runtime_error", "timeout", "resource_limit", "failed"}:
                raise ValueError
            if not isinstance(output, str):
                raise ValueError
        except (ValueError, KeyError, json.JSONDecodeError):
            raise RunnerUnavailable("Isolated execution returned an invalid response") from None
        if status == "failed":
            status = "runtime_error"
        return CaseExecution(status, output[:32_768], int((time.monotonic() - started) * 1000))
    finally:
        if container_id:
            _remove_container(container_id)
        _slots.release()


def run_question(language: str, source: str, cases: list[tuple[str, str]]) -> tuple[list[dict[str, object]], int]:
    """Run every public and hidden case without returning case inputs or expected outputs."""
    if not cases or len(cases) > min(MAX_TEST_CASES, settings.code_runner_max_cases):
        raise ValueError("Question test-case count exceeds the execution limits")
    deadline = time.monotonic() + _MAX_ATTEMPT_SECONDS
    details: list[dict[str, object]] = []
    score_cases = 0
    for case_id, (input_data, expected_output) in enumerate(cases):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            details.append({"case_order": case_id, "status": "timeout", "passed": False})
            continue
        result = run_case(
            language, source, input_data,
            timeout_seconds=min(max(1.0, float(settings.code_runner_timeout_seconds)), 10.0, remaining),
        )
        passed = result.status == "completed" and result.output.strip() == expected_output.strip()
        score_cases += int(passed)
        details.append({
            "case_order": case_id,
            "status": result.status,
            "passed": passed,
            "duration_ms": result.duration_ms,
            "output": result.output if result.status != "completed" else "",
        })
        if result.status in {"compile_error", "runtime_error", "timeout", "resource_limit"}:
            # Compilation/runtime resource failures invalidate the remaining cases consistently.
            for remaining_order in range(case_id + 1, len(cases)):
                details.append({"case_order": remaining_order, "status": result.status, "passed": False, "duration_ms": 0, "output": result.output})
            break
    return details, score_cases
