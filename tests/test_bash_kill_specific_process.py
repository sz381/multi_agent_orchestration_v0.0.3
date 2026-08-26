"""Comprehensive tests for kill_specific_process: parameter validation, the port whitelist, process safety checks, the signal policy and real end-to-end.

Test cases:
- test_kill_rejects_non_int_port:               parametrized: non-int port rejected (None/float/str/list)
- test_kill_rejects_bool_port:                  bool port rejected (bool is an int subclass and must be excluded explicitly)
- test_kill_rejects_out_of_range_port:          parametrized: outside 1..65535 rejected (0/-1/65536/2**20)
- test_kill_rejects_non_whitelist_port:         parametrized: outside the port-range whitelist rejected (including just outside the endpoints)
- test_kill_whitelist_boundaries_pass_check:    parametrized: whitelist endpoints (3000/3100/...) pass through to the lsof stage
- test_kill_no_process_on_port:                 real: no process listening on the port returns a clear error
- test_kill_lsof_error_graceful:                lsof exceptions fall back to error without crashing
- test_kill_refuses_agent_self:                 killing the agent itself is refused (os.getpid())
- test_kill_refuses_pid_one:                    PID 1 (init) is refused
- test_kill_refuses_unresolvable_name:          process-name lookup failure aborts
- test_kill_refuses_system_process:             parametrized: system process names refused (defense in depth)
- test_kill_toctou_identity_changed:            second lsof before kill finds a changed PID identity → refused
- test_kill_toctou_recheck_failure:             TOCTOU re-check exception falls back
- test_kill_permission_denied:                  signal-send permission denial falls back
- test_kill_process_exited_in_race:             SIGTERM raising ProcessLookupError is treated as success in the race window
- test_kill_escalates_to_sigkill:               SIGTERM timeout auto-escalates to SIGKILL (signal-order assertions)
- test_kill_confirm_failure:                    still not exited after SIGKILL returns error
- test_kill_multiple_pids_all_success:          multiple PIDs listening on one port are all terminated
- test_kill_multiple_pids_abort_on_system:      any system process among multiple PIDs aborts the whole operation
- test_kill_error_contract_variants:            parametrized: error response field contract (type errors carry no port field)
- test_pid_alive_by_state:                      parametrized: zombie Z treated as exited (regression), alive-state detection
- test_pid_alive_missing_process:               ps with no results treated as exited
- test_pid_alive_probe_failure_conservative:    ps probe failure conservatively treated as alive
- test_kill_real_process_graceful:              end-to-end: real process graceful exit (SIGTERM) + port released + second call noop
- test_kill_real_process_escalates_sigkill:     end-to-end: real process ignoring SIGTERM is escalated to SIGKILL
- test_kill_concurrent_distinct_ports:          concurrently killing processes on two different ports all succeed

Covered scenarios:
- Parameter validation: types (bool as int subclass explicitly excluded), range 1..65535, port-range whitelist
  (endpoints included: 3000/3100/5000/5200/8000/8100; outside endpoints 2999/3101 rejected)
- Safety checks: self-protection (agent itself/PID 1), unresolvable process names, representative samples of the
  14 system-process names (launchd/kernel_task/WindowServer), TOCTOU second-lsof identity change
- Signal policy: SIGTERM graceful → KILL_GRACE_SECONDS timeout → SIGKILL forced → KILL_CONFIRM_SECONDS
  confirmation, escalation order [SIGTERM, SIGKILL]; ProcessLookupError in the race window treated as success;
  permission denial/confirmation timeout/re-check exceptions all fall back to structured error
- Multiple PIDs: lsof returning multiple listeners (SO_REUSEPORT scenario) kills all or aborts entirely on any
  system process (note: PIDs killed before the abort are not reported; the error response only has status/port/message — mid-way semantics locked)
- Liveness detection: ps status Z (zombie) treated as exited (os.kill(pid,0) false-positive regression),
  ps no result treated as exited, ps probe failure conservatively treated as alive
- End-to-end: real TCP-listening subprocess (random port in the whitelist range, bind success = free, prevents killing the wrong process),
  asserts killed[0].pid matches the subprocess PID (prevents killing others), exit codes (graceful 0 / forced -9),
  port released, second call after kill returns No process listening

Usage notes:
- All async: aligned with the kernel-layer tool async migration (kill_specific_process call sites all await;
  mocks use AsyncMock for async probe functions, stateful mocks are handwritten async def)
- End-to-end cases really kill processes: the subprocess is a listener started by the test itself (helpers.start_port_listener),
  with finally fallback kill + wait reap, no leftovers on failure
- Mock cases combine fabricated PIDs (9999/12345/9001) with real os.kill: a nonexistent PID naturally raises
  ProcessLookupError and takes the race-window branch, so the success path is covered without patching os.kill;
  only escalation/permission/confirmation-timeout paths patch os.kill (monkeypatch auto-restores)
- macOS only: kill_specific_process relies on lsof -ti tcp:port and ps semantics (consistent with the project's sandbox domain)
"""

import asyncio
import os
import signal
import sys
from unittest.mock import AsyncMock

import pytest

from core.tools._kernel import _bash
from core.tools._kernel._bash import kill_specific_process
from tests.helpers import _idle_port, _wait_port_free, read_json, start_port_listener

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="kill_specific_process 依赖 macOS lsof/ps 语义"
)


class TestKillParameterValidation:

    @pytest.mark.parametrize("bad_port", [None, 3.14, "3000", [3000]])
    @pytest.mark.asyncio
    async def test_kill_rejects_non_int_port(self, bad_port):
        r = read_json(await kill_specific_process(bad_port))
        assert r["status"] == "error"
        assert r["message"] == "port must be an integer."

    @pytest.mark.parametrize("bad_port", [True, False])
    @pytest.mark.asyncio
    async def test_kill_rejects_bool_port(self, bad_port):
        r = read_json(await kill_specific_process(bad_port))
        assert r["status"] == "error"
        assert r["message"] == "port must be an integer."

    @pytest.mark.parametrize("bad_port", [0, -1, 65536, 2**20])
    @pytest.mark.asyncio
    async def test_kill_rejects_out_of_range_port(self, bad_port):
        r = read_json(await kill_specific_process(bad_port))
        assert r["status"] == "error"
        assert f"port must be in 1..65535, got {bad_port}." == r["message"]

    @pytest.mark.parametrize("bad_port", [2999, 3101, 4000, 6000, 9999, 65535])
    @pytest.mark.asyncio
    async def test_kill_rejects_non_whitelist_port(self, bad_port):
        r = read_json(await kill_specific_process(bad_port))
        assert r["status"] == "error"
        assert "not in the allowed ranges" in r["message"]

    @pytest.mark.parametrize("edge_port", (3000, 3100, 5000, 5200, 8000, 8100))
    @pytest.mark.asyncio
    async def test_kill_whitelist_boundaries_pass_check(self, monkeypatch, edge_port):
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[]))
        r = read_json(await kill_specific_process(edge_port))
        assert r["status"] == "error"
        assert "No process listening" in r["message"]

    @pytest.mark.asyncio
    async def test_kill_no_process_on_port(self):
        port = _idle_port()
        r = read_json(await kill_specific_process(port))
        assert r["status"] == "error"
        assert f"No process listening on port {port}." == r["message"]

    @pytest.mark.asyncio
    async def test_kill_lsof_error_graceful(self, monkeypatch):
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(side_effect=RuntimeError("lsof is broken")))
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "error"
        assert "Failed to find process on port 3005" in r["message"]


class TestKillSafetyChecks:

    @pytest.mark.asyncio
    async def test_kill_refuses_agent_self(self, monkeypatch):
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[os.getpid()]))
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "error"
        assert "Refusing to kill PID" in r["message"]

    @pytest.mark.asyncio
    async def test_kill_refuses_pid_one(self, monkeypatch):
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[1]))
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "error"
        assert "Refusing to kill PID 1" in r["message"]

    @pytest.mark.asyncio
    async def test_kill_refuses_unresolvable_name(self, monkeypatch):
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[12345]))
        monkeypatch.setattr(_bash, "_process_comm", AsyncMock(return_value=""))
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "error"
        assert "Could not determine process name for PID 12345" in r["message"]

    @pytest.mark.parametrize("sys_name", ["launchd", "kernel_task", "WindowServer"])
    @pytest.mark.asyncio
    async def test_kill_refuses_system_process(self, monkeypatch, sys_name):
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[12345]))
        monkeypatch.setattr(_bash, "_process_comm", AsyncMock(return_value=sys_name))
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "error"
        assert f"Refusing to kill system process '{sys_name}'" in r["message"]


class TestKillSignalStrategy:

    @pytest.mark.asyncio
    async def test_kill_toctou_identity_changed(self, monkeypatch):
        calls = {"n": 0}

        async def fake_lsof(port):
            calls["n"] += 1
            return [9999] if calls["n"] == 1 else []

        monkeypatch.setattr(_bash, "_lsof_pids", fake_lsof)
        monkeypatch.setattr(_bash, "_process_comm", AsyncMock(return_value="testapp"))
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "error"
        assert "process identity changed between checks" in r["message"]

    @pytest.mark.asyncio
    async def test_kill_toctou_recheck_failure(self, monkeypatch):
        calls = {"n": 0}

        async def fake_lsof(port):
            calls["n"] += 1
            if calls["n"] == 1:
                return [9999]
            raise RuntimeError("lsof vanished")

        monkeypatch.setattr(_bash, "_lsof_pids", fake_lsof)
        monkeypatch.setattr(_bash, "_process_comm", AsyncMock(return_value="testapp"))
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "error"
        assert "TOCTOU re-check failed" in r["message"]

    @pytest.mark.asyncio
    async def test_kill_permission_denied(self, monkeypatch):
        def boom(pid, sig):
            raise PermissionError(13, "Operation not permitted")

        monkeypatch.setattr(os, "kill", boom)
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[9999]))
        monkeypatch.setattr(_bash, "_process_comm", AsyncMock(return_value="testapp"))
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "error"
        assert "Permission denied killing PID 9999" in r["message"]

    @pytest.mark.asyncio
    async def test_kill_process_exited_in_race(self, monkeypatch):
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[9999]))
        monkeypatch.setattr(_bash, "_process_comm", AsyncMock(return_value="testapp"))
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "ok"
        assert r["killed"] == [{
            "pid": 9999, "name": "testapp",
            "signal_used": "SIGTERM", "graceful": True,
        }]

    @pytest.mark.asyncio
    async def test_kill_escalates_to_sigkill(self, monkeypatch):
        signals = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append(sig))
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[9999]))
        monkeypatch.setattr(_bash, "_process_comm", AsyncMock(return_value="testapp"))
        wait_calls = {"n": 0}

        async def fake_wait(pid, seconds):
            wait_calls["n"] += 1
            return wait_calls["n"] >= 2

        monkeypatch.setattr(_bash, "_wait_exit", fake_wait)
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "ok"
        assert signals == [signal.SIGTERM, signal.SIGKILL]
        assert r["killed"][0]["signal_used"] == "SIGKILL"
        assert r["killed"][0]["graceful"] is False

    @pytest.mark.asyncio
    async def test_kill_confirm_failure(self, monkeypatch):
        monkeypatch.setattr(os, "kill", lambda pid, sig: None)
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[9999]))
        monkeypatch.setattr(_bash, "_process_comm", AsyncMock(return_value="testapp"))
        monkeypatch.setattr(_bash, "_wait_exit", AsyncMock(return_value=False))
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "error"
        assert "did not exit after SIGKILL" in r["message"]

    @pytest.mark.asyncio
    async def test_kill_multiple_pids_all_success(self, monkeypatch):
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[9001, 9002]))
        async def fake_comm(pid):
            return f"app{pid}"

        monkeypatch.setattr(_bash, "_process_comm", fake_comm)
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "ok"
        assert len(r["killed"]) == 2
        assert {k["pid"] for k in r["killed"]} == {9001, 9002}
        assert all(k["graceful"] for k in r["killed"])

    @pytest.mark.asyncio
    async def test_kill_multiple_pids_abort_on_system(self, monkeypatch):
        monkeypatch.setattr(_bash, "_lsof_pids", AsyncMock(return_value=[9001, 9002]))

        async def fake_comm(pid):
            return "testapp" if pid == 9001 else "launchd"

        monkeypatch.setattr(_bash, "_process_comm", fake_comm)
        r = read_json(await kill_specific_process(3005))
        assert r["status"] == "error"
        assert "system process 'launchd'" in r["message"]
        assert "killed" not in r 

    @pytest.mark.parametrize("port_arg,expect_port_field", [
        ("str_port", False), 
        (0, True),  
        (4000, True), 
    ])
    @pytest.mark.asyncio
    async def test_kill_error_contract_variants(self, monkeypatch, port_arg, expect_port_field):
        if port_arg == "str_port":
            r = read_json(await kill_specific_process("3000"))
        else:
            r = read_json(await kill_specific_process(port_arg))
        assert r["status"] == "error"
        assert r["tool_name"] == "kill_specific_process"
        assert ("port" in r) is expect_port_field


class TestPidAliveUnit:

    @pytest.mark.parametrize("stat,expected", [
        ("S", True), ("R", True), ("T", True),  
        ("Z", False),                         
        ("", False),                           
    ])
    @pytest.mark.asyncio
    async def test_pid_alive_by_state(self, monkeypatch, stat, expected):
        monkeypatch.setattr(_bash, "_run_probe", AsyncMock(return_value=(0, stat)))
        assert await _bash._pid_alive(12345) is expected

    @pytest.mark.asyncio
    async def test_pid_alive_missing_process(self, monkeypatch):
        monkeypatch.setattr(_bash, "_run_probe", AsyncMock(return_value=(1, "")))
        assert await _bash._pid_alive(12345) is False

    @pytest.mark.asyncio
    async def test_pid_alive_probe_failure_conservative(self, monkeypatch):
        monkeypatch.setattr(_bash, "_run_probe", AsyncMock(side_effect=OSError("ps is broken")))
        assert await _bash._pid_alive(12345) is True


class TestKillRealProcess:

    @pytest.mark.asyncio
    async def test_kill_real_process_graceful(self):
        proc, port = start_port_listener("graceful")
        try:
            r = read_json(await kill_specific_process(port))
            assert r["status"] == "ok"
            assert r["tool_name"] == "kill_specific_process"
            assert r["port"] == port
            assert len(r["killed"]) == 1
            assert r["killed"][0]["pid"] == proc.pid  
            assert r["killed"][0]["name"]
            assert r["killed"][0]["signal_used"] == "SIGTERM"
            assert r["killed"][0]["graceful"] is True
            assert proc.wait(timeout=5) == 0
            assert await _wait_port_free(port), "kill 后端口应释放"

            again = read_json(await kill_specific_process(port))
            assert again["status"] == "error"
            assert "No process listening" in again["message"]
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    @pytest.mark.asyncio
    async def test_kill_real_process_escalates_sigkill(self, monkeypatch):
        monkeypatch.setattr(_bash, "KILL_GRACE_SECONDS", 0.5)
        proc, port = start_port_listener("stubborn")
        try:
            r = read_json(await kill_specific_process(port))
            assert r["status"] == "ok"
            assert r["killed"][0]["pid"] == proc.pid
            assert r["killed"][0]["signal_used"] == "SIGKILL"
            assert r["killed"][0]["graceful"] is False
            assert proc.wait(timeout=5) == -signal.SIGKILL
            assert await _wait_port_free(port), "SIGKILL 后端口应释放"
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    @pytest.mark.asyncio
    async def test_kill_concurrent_distinct_ports(self):
        proc1, port1 = start_port_listener("graceful")
        proc2, port2 = start_port_listener("graceful")
        try:
            results = await asyncio.gather(
                kill_specific_process(port1), kill_specific_process(port2)
            )
            for raw, proc, port in zip(results, (proc1, proc2), (port1, port2)):
                r = read_json(raw)
                assert r["status"] == "ok"
                assert r["killed"][0]["pid"] == proc.pid
                assert proc.wait(timeout=5) == 0
                assert await _wait_port_free(port)
        finally:
            for proc in (proc1, proc2):
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
