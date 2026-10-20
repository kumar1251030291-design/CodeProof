"""Single-test-case sandbox entrypoint; expected values never enter this container."""

import json
import os
import resource
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

MAX_SOURCE = 100_000
MAX_STDIN = 65_536
MAX_OUTPUT = 32_768
WORK = Path("/workspace")


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1_048_576, 1_048_576))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))


def _run(argv: list[str], stdin: bytes, timeout: float) -> tuple[str, bytes, int | None]:
    process = subprocess.Popen(
        argv,
        cwd=WORK,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "TMPDIR": "/tmp", "LANG": "C.UTF-8"},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        close_fds=True,
        start_new_session=True,
        preexec_fn=_limits,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        process.stdin.write(stdin)
        process.stdin.close()
    except BrokenPipeError:
        pass
    output = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    status = "completed"
    try:
        while process.poll() is None or selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fd, min(4096, MAX_OUTPUT + 1 - len(output)))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > MAX_OUTPUT:
                    status = "resource_limit"
                    break
            if status != "completed":
                break
        if status != "completed":
            os.killpg(process.pid, signal.SIGKILL)
        returncode = process.wait(timeout=1)
        if status == "completed" and returncode in {-signal.SIGKILL, -signal.SIGXCPU}:
            status = "resource_limit"
        elif status == "completed" and returncode != 0:
            status = "runtime_error"
        return status, bytes(output[:MAX_OUTPUT]), returncode
    finally:
        selector.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        process.stdout.close()


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(MAX_SOURCE + MAX_STDIN + 4096)
        request = json.loads(raw)
        language = request["language"]
        source = request["source"]
        stdin = request["stdin"]
        if language not in {"python", "c"} or not isinstance(source, str) or not isinstance(stdin, str):
            raise ValueError("invalid request")
        source_bytes = source.encode("utf-8")
        stdin_bytes = stdin.encode("utf-8")
        if not source_bytes or len(source_bytes) > MAX_SOURCE or len(stdin_bytes) > MAX_STDIN:
            raise ValueError("request exceeds limits")
        WORK.mkdir(mode=0o777, exist_ok=True)
        if language == "python":
            program = WORK / "solution.py"
            program.write_bytes(source_bytes)
            argv = ["python", "-I", str(program)]
        else:
            program = WORK / "solution.c"
            program.write_bytes(source_bytes)
            compile_status, compile_output, _ = _run(
                ["gcc", "-std=c11", "-O2", "-pipe", "-o", str(WORK / "solution"), str(program)],
                b"",
                3.0,
            )
            if compile_status != "completed":
                print(json.dumps({"status": "compile_error", "output": compile_output.decode("utf-8", "replace")[:MAX_OUTPUT]}))
                return
            argv = [str(WORK / "solution")]
        status, output, exit_code = _run(argv, stdin_bytes, 2.5)
        print(json.dumps({"status": status, "output": output.decode("utf-8", "replace"), "exit_code": exit_code}))
    except Exception:
        print(json.dumps({"status": "failed", "output": "Runner rejected the execution request."}))


if __name__ == "__main__":
    main()
