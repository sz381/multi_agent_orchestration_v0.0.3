"""Test helper module

Provided functions:
- read_json: Reads a JSON string and returns a JSON object
- make_file: Creates a text file with the given line count and line length, returning the file path
- make_indexed_file: Creates a file whose lines carry line numbers, for verifying line/content correspondence
- make_text_file: Creates a text file with the given content (parent directories are created automatically)
- start_http_server: Starts an HTTP probe server on a random port at 127.0.0.1 (used by bash network-allowed cases)
- start_port_listener: Starts a real TCP-listening subprocess in the whitelisted port range (used by kill_specific_process end-to-end)
- _wait_port_free: Polls until a port is no longer listened on (port-release assertions in kill end-to-end cases)
- _idle_port: Picks a free port in the whitelisted range (kill cases with no process listening)
- _pid_exists: Checks whether a process exists for the PID (timeout whole-group termination verification)
- rels: Converts a list of absolute paths into a set of relative paths (based on the realpath-normalized workspace root)
- _phase: Builds a standard phase dict (unified data generation for the three plan-tool tests)
- _ok_phases: Builds count legal phases with no duplicates
- _plan2: Standard two-phase plan (p1/p2)
- _plan3: Standard three-phase plan (p1/p2/p3)
- _task: Builds a standard task dict (unified data generation for fanout_subagents tests)
- _ok_tasks: Builds count legal tasks with no duplicates

Usage notes:
- This module only holds test helpers; it contains no test cases
"""

import asyncio
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.tools._kernel.constants import KILL_ALLOWED_PORTS
from core.tools._kernel import _bash


def read_json(raw: str) -> dict:
    return json.loads(raw)


def make_file(
    workspace, 
    name: str, 
    line_count: int, 
    line_len: int = 21, 
    subdir: str | None = None
):
    path = (workspace / subdir if subdir else workspace) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    line = "x" * (line_len - 1) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(line_count):
            f.write(line)
    return path


def make_text_file(workspace, name: str, content: str):
    path = workspace / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def start_http_server():
    class _ProbeHandler(BaseHTTPRequestHandler):

        def do_GET(self):
            body = b"sandbox-http-ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _ProbeHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port, server


def start_port_listener(mode: str = "graceful"):
    script = (
        "import signal, socket, sys, time\n"
        "mode = sys.argv[1]\n"
        "s = socket.socket()\n"
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        's.bind(("127.0.0.1", int(sys.argv[2])))\n'
        "s.listen(1)\n"
        'if mode == "graceful":\n'
        "    def _exit(*_): sys.exit(0)\n"
        "    signal.signal(signal.SIGTERM, _exit)\n"
        "else:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "while True:\n"
        "    time.sleep(1)\n"
    )
    lo, hi = KILL_ALLOWED_PORTS[0]
    port = None
    for _ in range(30):
        candidate = random.randint(lo, hi)
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
                port = candidate
                break
            except OSError:
                continue
    if port is None:
        raise RuntimeError(f"no idle port in {lo}..{hi}")

    proc = subprocess.Popen([sys.executable, "-c", script, mode, str(port)])
    deadline = time.time() + 5
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"listener exited early: rc={proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return proc, port
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise RuntimeError("listener did not become ready in 5s")


async def _wait_port_free(port: int, seconds: float = 3) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not await _bash._lsof_pids(port):
            return True
        await asyncio.sleep(0.1)
    return False


def _idle_port() -> int:
    lo, hi = KILL_ALLOWED_PORTS[0]
    for _ in range(30):
        candidate = random.randint(lo, hi)
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
                return candidate
            except OSError:
                continue
    raise RuntimeError(f"no idle port in {lo}..{hi}")


def _pid_exists(pid: int) -> bool:
    result = subprocess.run(
        ["ps", "-p", str(pid)], capture_output=True, text=True, timeout=5
    )
    return result.returncode == 0


def make_indexed_file(workspace, name: str, line_count: int):
    path = workspace / name
    with open(path, "w", encoding="utf-8") as f:
        for i in range(1, line_count + 1):
            f.write(f"line-{i}\n")
    return path


def rels(workspace, files: list[str]) -> set[str]:
    abs_ws = os.path.realpath(str(workspace))
    return {os.path.relpath(f, abs_ws) for f in files}


def _phase(**overrides):
    phase = {
        "phase_id": "p1",
        "phase_name": "阶段一",
        "phase_status": "pending",
        "phase_description": "描述一",
    }
    phase.update(overrides)
    return phase


def _ok_phases(count):
    return [_phase(phase_id=f"p{i}") for i in range(count)]


def _plan2():
    return [_phase(), _phase(phase_id="p2", phase_name="阶段二")]


def _plan3():
    return [_phase(), _phase(phase_id="p2", phase_name="阶段二"), _phase(phase_id="p3", phase_name="阶段三")]


def _task(**overrides):
    task = {
        "task_id": "t1",
        "task_name": "任务一",
        "task_description": "描述一",
        "task_completion_status": False,
        "subagent_id": "programmer_a",
        "subagent_name": "程序员甲",
    }
    task.update(overrides)
    return task


def _ok_tasks(count):
    prefixes = ["programmer", "reviewer", "researcher"]
    tasks = []
    for i in range(count):
        prefix = prefixes[i % len(prefixes)]
        tasks.append(_task(task_id=f"t{i}", subagent_id=f"{prefix}_{i}"))
    return tasks
