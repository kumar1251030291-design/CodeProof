"""Opt-in integration checks requiring a built codeproof-runner image and Docker engine."""

import os
import json
import subprocess

import pytest

from app.core import execution
from app.core.config import settings

pytestmark = pytest.mark.skipif(
    os.getenv("CODEPROOF_RUNNER_INTEGRATION") != "1",
    reason="Set CODEPROOF_RUNNER_INTEGRATION=1 after building the isolated runner image",
)


def test_python_and_c_run_in_sandbox_and_cannot_reach_secrets_or_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "code_execution_enabled", True)
    python = execution.run_case(
        "python",
        "import os, socket\nprint('DATABASE_URL' in os.environ, 'SUPABASE_URL' in os.environ)\ns=socket.socket(); s.settimeout(.2)\ntry: s.connect(('1.1.1.1', 80)); print('network')\nexcept OSError: print('isolated')",
        "",
        timeout_seconds=8,
    )
    assert python.status == "completed"
    assert "False False" in python.output and "isolated" in python.output

    c_program = '#include <stdio.h>\nint main(void) { int n; if (scanf("%d", &n) != 1) return 1; printf("%d\\n", n + 1); return 0; }'
    c_result = execution.run_case("c", c_program, "4\n", timeout_seconds=8)
    assert c_result.status == "completed" and c_result.output.strip() == "5"


def test_timeout_and_output_limits_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "code_execution_enabled", True)
    timeout = execution.run_case("python", "while True: pass", "", timeout_seconds=8)
    assert timeout.status == "timeout"
    output = execution.run_case("python", "print('x' * 50000)", "", timeout_seconds=8)
    assert output.status == "resource_limit"
    runtime = execution.run_case("python", "raise SystemExit(2)", "", timeout_seconds=8)
    assert runtime.status == "runtime_error"
    compile_error = execution.run_case("c", "int main( {", "", timeout_seconds=8)
    assert compile_error.status == "compile_error"


def test_disposable_container_has_no_mounts_secrets_or_elevated_privileges() -> None:
    container_id = execution._create_container()
    try:
        inspected = subprocess.run(
            ["docker", "inspect", container_id], capture_output=True, text=True, check=True
        )
        config = json.loads(inspected.stdout)[0]
        assert config["Mounts"] == []
        assert not any(name in " ".join(config["Config"]["Env"]) for name in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_JWT_SECRET"))
        assert config["HostConfig"]["NetworkMode"] == "none"
        assert config["HostConfig"]["AutoRemove"] is True
        assert config["HostConfig"]["ReadonlyRootfs"] is True
        assert config["HostConfig"]["CapDrop"] == ["ALL"]
        assert config["HostConfig"]["Memory"] == 128 * 1024 * 1024
        assert config["HostConfig"]["PidsLimit"] == 32
        assert config["Config"]["User"] == "10001:10001"
        assert "no-new-privileges:true" in config["HostConfig"]["SecurityOpt"]
    finally:
        execution._remove_container(container_id)
