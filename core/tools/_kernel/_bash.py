"""Agent system shell command tooling.

⚠️ macOS only (sandbox-exec + Seatbelt sandbox).

Functions:
- bash:                     execute a bash command
- kill_specific_process:    kill a specific process

Key constraints:
- Always returns a JSON string (status: ok/error); execution exceptions are
  caught and returned as error responses, never raised
- Type safety: allow_network must be a bool (the string "false" is truthy and
  would unintentionally allow network); timeout must be an int/float > 0 (bool
  is a subclass of int, so exclude it explicitly); cmd/cwd must be strings
- Blacklist check comes first: commands matching the BLACKLIST_PATTERNS regex
  set are refused (the Seatbelt sandbox is the first line of defense, the
  blacklist is defense in depth)
- cwd must be a workspace subdirectory (path boundaries are normalized to
  prevent prefix-matching traps); if the workspace is not configured, fail
  immediately (a configuration error is raised, not returned as error JSON)
- Output truncation: stdout/stderr are capped at BASH_MAX_OUTPUT_CHARS chars
  per stream
- kill_specific_process is the safe escape hatch for the bash sandbox: Seatbelt
  rules only allow (allow signal (target self)), so bash cannot kill other
  processes; this tool operates outside the sandbox, only allows ports in the
  KILL_ALLOWED_PORTS whitelist, refuses the agent itself / PID 1 / system
  processes, and re-checks before killing to prevent PID reuse (TOCTOU)
- kill_specific_process signal strategy: SIGTERM for graceful termination,
  auto-escalate to SIGKILL if not exited within KILL_GRACE_SECONDS, then wait
  KILL_CONFIRM_SECONDS to confirm exit

Usage notes:
- Depends on the sandbox layer (sandbox/executor.py + sandbox/profile.py):
  allow_network=True uses the network profile (global read + workspace write +
  full network), False uses the air-gapped profile (no network)
- Subprocess environment isolation: strips agent environment variables such as
  VIRTUAL_ENV/PYTHONPATH and variables containing sensitive keywords, to
  prevent leakage into subprocesses
- On timeout, the whole process group (bash + all children) is SIGKILLed
- kill_specific_process relies on lsof/ps (bundled with macOS); the TOCTOU
  check requires two consistent lsof probes; in the extreme case of a rapidly
  restarting process it may conservatively refuse
"""

import asyncio
import json
import os
import re
import signal
import time

from core.tools._kernel.constants import (
    BASH_MAX_OUTPUT_CHARS,
    BLACKLIST_PATTERNS,
    KILL_ALLOWED_PORTS,
    KILL_CONFIRM_SECONDS,
    KILL_GRACE_SECONDS,
    KILL_POLL_INTERVAL,
    KILL_SYSTEM_PROCESS_NAMES,
)
from core.tools._kernel.sandbox.executor import arun as sandbox_run
from utils.settings import settings


async def bash(
    cmd: str,
    cwd: str = ".",
    timeout: int = 30,
    allow_network: bool = True,
) -> str:
    """Execute a shell command in the Seatbelt sandbox.

    ⚠️ macOS only (sandbox-exec + Seatbelt sandbox).

    Execution model: parameter validation, blacklist and path safety chain
    (pure CPU) stay on the event loop; the sandbox-exec subprocess is managed
    directly by the event loop (asyncio.create_subprocess_exec), so it does
    not occupy a thread-pool thread and can be cancelled (wait_for + whole
    group SIGKILL).

    Args:
        cmd: The shell command to execute.
        cwd: Working directory relative to the workspace (default '.').
        timeout: Timeout in seconds, after which the process is killed
            (default 30).
        allow_network: Whether to allow network access (default True).

    Returns:
        A JSON string with status/exit_code/stdout/stderr/elapsed time and
        the sandbox violation count.
    """
    # Param check: cmd must be a string
    if not isinstance(cmd, str):
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": "cmd must be a string.",
        }, ensure_ascii=False)

    # Param check: cmd must be a non-empty string
    if not cmd.strip():
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": "cmd must be a non-empty string.",
        }, ensure_ascii=False)

    # Param check: allow_network must be a boolean (the string "false" is truthy, would unintentionally allow network)
    if not isinstance(allow_network, bool):
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": "allow_network must be a boolean.",
        }, ensure_ascii=False)

    # Param check: timeout must be an int/float (bool is a subclass of int, exclude it explicitly)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": "timeout must be a number.",
        }, ensure_ascii=False)

    # Param check: timeout must be > 0
    if timeout <= 0:
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": f"timeout must be > 0, got {timeout}.",
        }, ensure_ascii=False)

    # Param check: cwd must be a string
    if not isinstance(cwd, str):
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": "cwd must be a string.",
        }, ensure_ascii=False)

    # Blacklist check against the security policy (cmd is confirmed to be a string)
    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, cmd):
            return json.dumps({
                "status": "error",
                "tool_name": "bash",
                "message": f"Command blocked by security policy: {cmd}",
            }, ensure_ascii=False)

    # Resolve the workspace; it MUST be configured — raise immediately if missing
    workspace = settings.workspace_dir
    if not workspace:
        raise RuntimeError("WORKSPACE_DIR is not configured, please set it up.")
    workspace = os.path.abspath(workspace)

    # Normalize the workspace root to exactly one trailing separator to prevent prefix-matching traps.
    safe_root = workspace.rstrip(os.sep) + os.sep

    # Ensure cwd is absolute and a workspace subdirectory, normalized via realpath.
    # Resolve multiple slashes and .. before the prefix check: a literal prefix
    # match on a user-supplied absolute path could escape via workspace///../../dir.
    if not os.path.isabs(cwd):
        cwd = os.path.join(safe_root, cwd)
    cwd = os.path.realpath(cwd)

    # Ensure cwd is a workspace subdirectory
    if not (cwd + os.sep).startswith(safe_root):
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": f"cwd '{cwd}' is outside the workspace.",
        }, ensure_ascii=False)

    # Ensure timeout > 0
    if timeout <= 0:
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": f"timeout must be > 0, got {timeout}.",
        }, ensure_ascii=False)

    # Record the start time for elapsed computation
    started = time.monotonic()

    # Execute the command (truly async: subprocess managed by the event loop, no thread pool)
    try:
        result = await sandbox_run(
            cmd=cmd,
            workspace=safe_root,
            cwd=cwd,
            timeout=timeout,
            allow_network=allow_network,
        )
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": f"Bash execution failed: {exc}",
        }, ensure_ascii=False)

    # Record the end time for elapsed computation
    elapsed = time.monotonic() - started

    # Output truncation: at most BASH_MAX_OUTPUT_CHARS chars per stream (truncation marker is uniform ASCII)
    stdout = result["stdout"].strip()
    stderr = result["stderr"].strip()
    stdout_show = stdout[:BASH_MAX_OUTPUT_CHARS] + (
        "..." if len(stdout) > BASH_MAX_OUTPUT_CHARS else "")
    stderr_show = stderr[:BASH_MAX_OUTPUT_CHARS] + (
        "..." if len(stderr) > BASH_MAX_OUTPUT_CHARS else "")

    # Build the return result
    return json.dumps({
        "status": "ok",
        "tool_name": "bash",
        "command": cmd,
        "exit_code": result["exit_code"],
        "stdout": stdout_show,
        "stderr": stderr_show,
        "timeout": result["timeout"],
        "sandbox_violations": result.get("sandbox_violations", 0),
        "elapsed": round(elapsed, 1),
    }, ensure_ascii=False)


async def _run_probe(args: list[str]) -> tuple[int, str]:
    """Run a short probe command (lsof/ps), returning (returncode, stdout).

    Reused by kill_specific_process for process probing: the subprocess is
    managed directly by the event loop (create_subprocess_exec), so it does
    not occupy a thread-pool thread; on timeout (>5s) the process is killed
    and reaped before raising TimeoutError, letting the caller decide the
    fallback semantics.

    Args:
        args: The probe command argv list (e.g. ["lsof", "-ti", "tcp:8000"]).

    Returns:
        (returncode, stdout text); stdout is decoded with utf-8 error tolerance.
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except TimeoutError:
        # wait_for already cancelled communicate; kill first, then reap, to avoid probe process leaks
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode, stdout_bytes.decode("utf-8", errors="replace")


async def _lsof_pids(port: int) -> list[int]:
    """Return the PIDs listening on the given TCP port (lsof exit code 1 = no match).

    Args:
        port: The TCP port to query.

    Returns:
        A list of PIDs; empty when lsof has no match or the output has no
        valid numbers. Probe timeout raises TimeoutError, caught by the
        caller and turned into an error response.
    """
    returncode, stdout = await _run_probe(["lsof", "-ti", f"tcp:{port}"])
    if returncode != 0:
        return []
    return [int(pid) for pid in stdout.split() if pid.strip().isdigit()]


async def _process_comm(pid: int) -> str:
    """Return the process name (ps comm field); empty string if missing or unreadable.

    Args:
        pid: The target process ID.

    Returns:
        The process name; empty string on probe failure (including timeout
        or a nonexistent process).
    """
    try:
        returncode, stdout = await _run_probe(["ps", "-p", str(pid), "-o", "comm="])
        if returncode == 0:
            return stdout.strip()
    except Exception:
        pass
    return ""


async def _pid_alive(pid: int) -> bool:
    """Check whether a process is alive (ps status field; zombie Z counts as exited).

    os.kill(pid, 0) must not be used for probing: after SIGKILL, a process
    whose parent has not reaped it remains as a zombie, and the 0-signal
    probe still reports it as present, falsely reporting "not exited".

    Args:
        pid: The target process ID.

    Returns:
        True if alive; conservatively treated as alive when the ps probe
        fails (a permission error fallback follows later).
    """
    try:
        returncode, stdout = await _run_probe(["ps", "-p", str(pid), "-o", "stat="])
        if returncode != 0:
            return False  # process does not exist
        stat = stdout.strip()
        return bool(stat) and "Z" not in stat
    except Exception:
        return True


async def _wait_exit(pid: int, seconds: float) -> bool:
    """Poll until the process exits, at most seconds; True if exited.

    Args:
        pid:      The target process ID.
        seconds:  Maximum wait time in seconds.

    Returns:
        True if exited; False if still alive after the timeout.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not await _pid_alive(pid):
            return True
        await asyncio.sleep(KILL_POLL_INTERVAL)
    return not await _pid_alive(pid)


async def kill_specific_process(port: int) -> str:
    """Kill the process listening on the given port (safe escape hatch from the bash sandbox).

    ⚠️ macOS only. The Seatbelt sandbox rules only allow (allow signal
    (target self)), so the bash tool cannot kill other processes — this tool
    operates directly outside the sandbox and is the only way to stop a dev
    server (npm run dev, uvicorn, etc.).

    Safety boundaries:
    - port must fall inside the KILL_ALLOWED_PORTS port-range whitelist
    - refuses to kill the agent itself (os.getpid()) and PID 1
    - refuses system processes (KILL_SYSTEM_PROCESS_NAMES)
    - TOCTOU protection: a second lsof check confirms the PID still listens
      on the port before killing, to prevent killing a reused PID

    Signal strategy: SIGTERM first for graceful termination; auto-escalate to
    SIGKILL if not exited within KILL_GRACE_SECONDS, then wait
    KILL_CONFIRM_SECONDS to confirm exit.

    Execution model: parameter validation and whitelist checks (pure CPU)
    stay on the event loop; lsof/ps probe subprocesses are managed directly
    by the event loop (create_subprocess_exec); exit polling uses
    asyncio.sleep, so no thread-pool threads are occupied.

    Args:
        port: The target port (1~65535).

    Returns:
        A JSON string with status/port/killed list (pid/name/signal_used/graceful).
    """
    # Param check: port must be an int (bool is a subclass of int, exclude it explicitly)
    if not isinstance(port, int) or isinstance(port, bool):
        return json.dumps({
            "status": "error",
            "tool_name": "kill_specific_process",
            "message": "port must be an integer.",
        }, ensure_ascii=False)

    # Param check: port must be in the valid port range
    if not 1 <= port <= 65535:
        return json.dumps({
            "status": "error",
            "tool_name": "kill_specific_process",
            "port": port,
            "message": f"port must be in 1..65535, got {port}.",
        }, ensure_ascii=False)

    # Port whitelist: only kill dev ports inside the KILL_ALLOWED_PORTS ranges
    if not any(lo <= port <= hi for lo, hi in KILL_ALLOWED_PORTS):
        return json.dumps({
            "status": "error",
            "tool_name": "kill_specific_process",
            "port": port,
            "message": f"Port {port} is not in the allowed ranges: {list(KILL_ALLOWED_PORTS)}.",
        }, ensure_ascii=False)

    # Locate the listening process (read-only operation outside the sandbox; lsof is bundled with macOS)
    try:
        pids = await _lsof_pids(port)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "tool_name": "kill_specific_process",
            "port": port,
            "message": f"Failed to find process on port {port}: {exc}",
        }, ensure_ascii=False)

    if not pids:
        return json.dumps({
            "status": "error",
            "tool_name": "kill_specific_process",
            "port": port,
            "message": f"No process listening on port {port}.",
        }, ensure_ascii=False)

    # Validate and kill each PID in turn (lsof may return multiple listeners)
    killed = []
    for pid in pids:
        # Self-protection: refuse to kill the agent itself or PID 1
        if pid == os.getpid() or pid == 1:
            return json.dumps({
                "status": "error",
                "tool_name": "kill_specific_process",
                "port": port,
                "message": f"Refusing to kill PID {pid} (agent itself or init).",
            }, ensure_ascii=False)

        name = await _process_comm(pid)
        if not name:
            return json.dumps({
                "status": "error",
                "tool_name": "kill_specific_process",
                "port": port,
                "message": f"Could not determine process name for PID {pid}; aborting.",
            }, ensure_ascii=False)

        # Refuse system processes (defense in depth; root-owned processes are usually blocked anyway by permission errors)
        if name in KILL_SYSTEM_PROCESS_NAMES:
            return json.dumps({
                "status": "error",
                "tool_name": "kill_specific_process",
                "port": port,
                "message": f"Refusing to kill system process '{name}' (PID {pid}).",
            }, ensure_ascii=False)

        # TOCTOU protection: re-check that the PID still listens on the port before killing (prevents killing a reused PID)
        try:
            current = await _lsof_pids(port)
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "tool_name": "kill_specific_process",
                "port": port,
                "message": f"TOCTOU re-check failed on port {port}: {exc}",
            }, ensure_ascii=False)
        if pid not in current:
            return json.dumps({
                "status": "error",
                "tool_name": "kill_specific_process",
                "port": port,
                "message": f"Refusing to kill PID {pid}: process identity changed between checks.",
            }, ensure_ascii=False)

        # Graceful SIGTERM; if the process already exited by itself, treat as success (race window)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            killed.append({"pid": pid, "name": name, "signal_used": "SIGTERM", "graceful": True})
            continue
        except PermissionError:
            return json.dumps({
                "status": "error",
                "tool_name": "kill_specific_process",
                "port": port,
                "message": f"Permission denied killing PID {pid} ({name}).",
            }, ensure_ascii=False)

        # Wait for graceful exit; escalate to SIGKILL if the timeout expires
        signal_used = "SIGTERM"
        graceful = True
        if not await _wait_exit(pid, KILL_GRACE_SECONDS):
            try:
                os.kill(pid, signal.SIGKILL)
                signal_used = "SIGKILL"
                graceful = False
            except ProcessLookupError:
                pass  # exited between SIGTERM and SIGKILL
            except PermissionError:
                return json.dumps({
                    "status": "error",
                    "tool_name": "kill_specific_process",
                    "port": port,
                    "message": f"Permission denied killing PID {pid} ({name}).",
                }, ensure_ascii=False)

        # Confirm exit after SIGKILL (uninterruptible state / zombie may linger)
        if not await _wait_exit(pid, KILL_CONFIRM_SECONDS):
            return json.dumps({
                "status": "error",
                "tool_name": "kill_specific_process",
                "port": port,
                "message": f"PID {pid} ({name}) did not exit after {signal_used} (uninterruptible state?).",
            }, ensure_ascii=False)

        killed.append({"pid": pid, "name": name, "signal_used": signal_used, "graceful": graceful})

    return json.dumps({
        "status": "ok",
        "tool_name": "kill_specific_process",
        "port": port,
        "killed": killed,
    }, ensure_ascii=False)
