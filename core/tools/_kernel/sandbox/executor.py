"""macOS sandbox-exec + Seatbelt sandbox command executor.

- No fallback: if sandbox-exec fails, report an error (never try to bypass the sandbox)
- Output capped at SANDBOX_MAX_OUTPUT_CHARS (memory protection, decoupled from the _bash layer's display truncation)
"""

import asyncio
import os
import signal
import subprocess
import tempfile

from core.tools._kernel.constants import (
    SANDBOX_ENV_STRIP,
    SANDBOX_MAX_OUTPUT_CHARS,
    SANDBOX_SENSITIVE_ENV_KEYWORDS,
)
from core.tools._kernel.sandbox.profile import generate_air_gapped, generate_default

# Project root — used to strip the agent's own .venv from the subprocess PATH
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

# JAVA_HOME probe result cache (probed only once)
_JAVA_HOME_CACHE: str | None = None


def _is_sensitive_env(key: str) -> bool:
    """Return whether an env var name looks like sensitive credentials (API key/token, etc.)."""
    upper = key.upper()
    return any(pattern in upper for pattern in SANDBOX_SENSITIVE_ENV_KEYWORDS)


def _find_java_home() -> str | None:
    """Probe JAVA_HOME (when not set in the environment).

    macOS's /usr/bin/java is a stub; Gradle/Maven need an explicit JAVA_HOME.
    """
    try:
        result = subprocess.run(
            ["/usr/libexec/java_home"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _sandbox_path() -> str:
    """Strip the agent's own .venv/bin from the host PATH; pass everything else through unchanged."""
    host_path = os.environ.get("PATH", "")
    entries = []
    for entry in host_path.split(":"):
        entry = entry.strip()
        if not entry:
            continue
        if entry.startswith(_PROJECT_ROOT):
            continue
        entries.append(entry)
    return ":".join(entries) if entries else "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


def _strip_sandbox_msgs(stderr: str) -> tuple[str, int]:
    """Filter macOS Seatbelt violation log lines from stderr.

    Returns:
        The cleaned stderr and the number of removed violation lines.
    """
    lines = stderr.splitlines()
    kept = []
    violations = 0
    for line in lines:
        if (
            line.startswith("Sandbox:")
            or "Operation not permitted" in line
            or "Permission denied" in line
        ):
            violations += 1
        else:
            kept.append(line)
    return ("\n".join(kept), violations)


async def _exec_async(profile_path: str, cmd: str, cwd: str, timeout: int) -> dict:
    """Execute a command asynchronously via sandbox-exec with the given profile (truly async _exec).

    Semantics are identical to _exec: start_new_session creates an independent
    process group, and on timeout the whole group (bash + all children) is
    SIGKILLed; the difference is that the subprocess is managed directly by
    the event loop (create_subprocess_exec + wait_for), so no thread-pool
    thread is occupied, and it is cancellable.

    Args:
        profile_path: Path to the temporary Seatbelt profile file.
        cmd: The bash command to execute.
        cwd: Working directory (absolute path).
        timeout: Timeout in seconds, after which the whole group is SIGKILLed.

    Returns:
        {"exit_code": int|None, "stdout": str, "stderr": str,
         "timeout": bool, "sandbox_violations": int}, contract identical to _exec.
    """
    # Environment setup identical to _exec: strip the agent venv and sensitive
    # credentials, remove .venv from PATH, and redirect TMPDIR/HOME to /tmp
    # (prevents subprocesses from composing host config paths from $HOME)
    env = {k: v for k, v in os.environ.items() if k not in SANDBOX_ENV_STRIP and not _is_sensitive_env(k)}
    env["PATH"] = _sandbox_path()
    env["TMPDIR"] = "/tmp"
    env["HOME"] = "/tmp"

    # macOS's /usr/bin/java is a stub — Gradle/Maven need an explicit JAVA_HOME;
    # the first probe is a synchronous subprocess.run (up to 5s), offloaded to
    # a thread pool to avoid blocking the event loop; it happens only once
    if "JAVA_HOME" not in env:
        global _JAVA_HOME_CACHE
        if _JAVA_HOME_CACHE is None:
            _JAVA_HOME_CACHE = await asyncio.to_thread(_find_java_home)
        if _JAVA_HOME_CACHE:
            env["JAVA_HOME"] = _JAVA_HOME_CACHE

    # pipefail: the pipeline exit code is the rightmost non-zero segment (not
    # the last one), preventing `cmd 2>&1 | tail -40` from masking a real
    # failure with tail's exit code 0
    args = ["sandbox-exec", "-f", profile_path, "bash", "-o", "pipefail", "-c", cmd]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,  # new session = new process group, for a clean whole-group kill
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        exit_code = proc.returncode
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        stderr, violations = _strip_sandbox_msgs(stderr)

    except TimeoutError:
        # Kill the whole process group: bash + all children (same as _exec);
        # wait_for already cancelled communicate on timeout, so kill then wait to reap
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        return {"exit_code": None, "stdout": "", "stderr": "", "timeout": True, "sandbox_violations": 0}

    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timeout": False,
        "sandbox_violations": violations,
    }


async def arun(cmd: str, workspace: str, cwd: str = ".", timeout: int = 30, allow_network: bool = True) -> dict:
    """Execute a bash command asynchronously in the Seatbelt sandbox (truly async run).

    Semantics are identical to run: generate profile -> temp file -> execute ->
    clean up -> truncate; the difference is that the subprocess is managed
    directly by the event loop (_exec_async), so no thread-pool thread is
    occupied.

    Args:
        cmd: The bash command to execute.
        workspace: Absolute path of the project root.
        cwd: Working directory (absolute path).
        timeout: Timeout in seconds (default 30).
        allow_network: True uses the network profile, False uses the
            air-gapped one (no network).

    Returns:
        {"exit_code": int|None, "stdout": str, "stderr": str,
         "timeout": bool, "sandbox_violations": int}
    """
    profile_text = (
        generate_default(workspace=workspace)
        if allow_network
        else generate_air_gapped(workspace=workspace)
    )

    # Write the sandbox profile to a temp file, cleaned up after execution (micro-sized file, kept on the event loop)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sb", delete=False) as pf:
        pf.write(profile_text)
        profile_path = pf.name

    try:
        result = await _exec_async(profile_path, cmd, cwd, timeout)
    finally:
        try:
            os.unlink(profile_path)
        except OSError:
            pass

    # Truncate output (same as run)
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    if len(stdout) > SANDBOX_MAX_OUTPUT_CHARS:
        stdout = stdout[:SANDBOX_MAX_OUTPUT_CHARS] + f"\n... (stdout truncated, showing {SANDBOX_MAX_OUTPUT_CHARS} chars)"
    if len(stderr) > SANDBOX_MAX_OUTPUT_CHARS:
        stderr = stderr[:SANDBOX_MAX_OUTPUT_CHARS] + f"\n... (stderr truncated, showing {SANDBOX_MAX_OUTPUT_CHARS} chars)"

    return {
        "exit_code": result["exit_code"],
        "stdout": stdout,
        "stderr": stderr,
        "timeout": result.get("timeout", False),
        "sandbox_violations": result.get("sandbox_violations", 0),
    }
