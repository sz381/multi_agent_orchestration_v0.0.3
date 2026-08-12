"""kill_specific_process 全方面测试：参数校验、端口白名单、进程安全校验、信号策略与真实端到端。

测试项目：
- test_kill_rejects_non_int_port:               参数化验证非 int port 拒绝（None/float/str/list）
- test_kill_rejects_bool_port:                  验证 bool port 拒绝（bool 是 int 子类需显式排除）
- test_kill_rejects_out_of_range_port:          参数化验证 1..65535 范围外拒绝（0/-1/65536/2**20）
- test_kill_rejects_non_whitelist_port:         参数化验证端口段白名单外拒绝（含段端点外侧）
- test_kill_whitelist_boundaries_pass_check:    参数化验证白名单端点（3000/3100/...）放行至 lsof 阶段
- test_kill_no_process_on_port:                 真实验证无进程监听端口返回明确 error
- test_kill_lsof_error_graceful:                验证 lsof 异常兜底为 error 不裸炸
- test_kill_refuses_agent_self:                 验证拒绝 kill agent 自身（os.getpid()）
- test_kill_refuses_pid_one:                    验证拒绝 PID 1（init）
- test_kill_refuses_unresolvable_name:          验证进程名获取失败中止
- test_kill_refuses_system_process:             参数化验证系统进程名拒绝（纵深防御）
- test_kill_toctou_identity_changed:            验证 kill 前二次 lsof 发现 PID 身份变化拒绝
- test_kill_toctou_recheck_failure:             验证 TOCTOU 复检异常兜底
- test_kill_permission_denied:                  验证信号发送权限拒绝兜底
- test_kill_process_exited_in_race:             验证 SIGTERM 抛 ProcessLookupError 视为窗口期成功
- test_kill_escalates_to_sigkill:               验证 SIGTERM 超时自动升级 SIGKILL（信号顺序断言）
- test_kill_confirm_failure:                    验证 SIGKILL 后仍未退出返回 error
- test_kill_multiple_pids_all_success:          验证多 PID 监听同一端口全部终止
- test_kill_multiple_pids_abort_on_system:      验证多 PID 中任一系统进程则整体中止
- test_kill_error_contract_variants:            参数化验证 error 响应字段契约（类型错误无 port 字段）
- test_pid_alive_by_state:                      参数化验证僵尸 Z 视为退出（回归）、存活态判定
- test_pid_alive_missing_process:               验证 ps 无结果视为已退出
- test_pid_alive_probe_failure_conservative:    验证 ps 探测失败保守视为存活
- test_kill_real_process_graceful:              端到端：真实进程优雅退出（SIGTERM）+ 端口释放 + 二次调用 noop
- test_kill_real_process_escalates_sigkill:     端到端：真实进程忽略 SIGTERM 被 SIGKILL 升级
- test_kill_concurrent_distinct_ports:          并发杀两个不同端口进程全部成功

覆盖场景：
- 参数校验：类型（bool 是 int 子类的显式排除）、范围 1..65535、端口段白名单
  （端点含入：3000/3100/5000/5200/8000/8100；端点外 2999/3101 拒绝）
- 安全校验：自保（agent 自身/PID 1）、进程名不可解析、系统进程名 14 个集合
  的代表抽样（launchd/kernel_task/WindowServer）、TOCTOU 二次 lsof 身份变化
- 信号策略：SIGTERM 优雅 → KILL_GRACE_SECONDS 超时 → SIGKILL 强制 → KILL_CONFIRM_SECONDS
  确认，升级顺序 [SIGTERM, SIGKILL]；窗口期 ProcessLookupError 视为成功；
  权限拒绝/确认超时/复检异常全部兜底为结构化 error
- 多 PID：lsof 返回多个监听者（SO_REUSEPORT 场景）全杀或任一系统进程整体中止
  （注意：中止时已杀 PID 不报告，error 响应仅 status/port/message——半途语义锁定）
- 存活判定：ps 状态字段 Z（僵尸）视为退出（os.kill(pid,0) 误报回归）、
  ps 无结果视为退出、ps 探测失败保守视为存活
- 端到端：真实 TCP 监听子进程（白名单段内随机端口，bind 成功=空闲防误杀），
  断言 killed[0].pid 与子进程 PID 一致（防误杀他人）、退出码（优雅 0 / 强制 -9）、
  端口释放、杀后二次调用返回 No process listening

使用注意：
- 端到端用例真实杀进程：子进程是测试自身启动的监听器（helpers.start_port_listener），
  finally 兜底 kill + wait reap，失败不残留
- mock 用例中伪造 PID（9999/12345/9001）与真实 os.kill 组合：PID 不存在自然抛
  ProcessLookupError 走窗口期分支，无需 patch os.kill 即可覆盖成功路径；
  升级/权限/确认超时路径才 patch os.kill（monkeypatch 自动还原）
- 仅 macOS：kill_specific_process 依赖 lsof -ti tcp:port 与 ps 语义（与项目 sandbox 域一致）

测试用例数量：51
"""

import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.tools._kernel import _bash
from core.tools._kernel._bash import kill_specific_process
from tests.helpers import _idle_port, _wait_port_free, read_json, start_port_listener

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="kill_specific_process 依赖 macOS lsof/ps 语义"
)


class TestKillParameterValidation:
    """参数校验：类型、范围与端口白名单（纯逻辑，不触碰系统）。"""

    @pytest.mark.parametrize("bad_port", [None, 3.14, "3000", [3000]])
    def test_kill_rejects_non_int_port(self, bad_port):
        """非 int port（None/float/str/list）应拒绝：类型校验必须先于一切，
        None 会破坏 int 比较、字符串会进白名单比较出错，LLM 传参不可信。"""
        r = read_json(kill_specific_process(bad_port))
        assert r["status"] == "error"
        assert r["message"] == "port must be an integer."

    @pytest.mark.parametrize("bad_port", [True, False])
    def test_kill_rejects_bool_port(self, bad_port):
        """bool port 应拒绝：bool 是 int 子类，isinstance(True, int) 为真，
        不显式排除会把 True 当作端口 1 放行进白名单检查。"""
        r = read_json(kill_specific_process(bad_port))
        assert r["status"] == "error"
        assert r["message"] == "port must be an integer."

    @pytest.mark.parametrize("bad_port", [0, -1, 65536, 2**20])
    def test_kill_rejects_out_of_range_port(self, bad_port):
        """范围外 port（0/-1/65536/2**20）应拒绝：1..65535 是 TCP 端口合法域，
        越界值进 lsof 会得到荒谬查询（0 甚至可能命中系统 socket）。"""
        r = read_json(kill_specific_process(bad_port))
        assert r["status"] == "error"
        assert f"port must be in 1..65535, got {bad_port}." == r["message"]

    @pytest.mark.parametrize("bad_port", [2999, 3101, 4000, 6000, 9999, 65535])
    def test_kill_rejects_non_whitelist_port(self, bad_port):
        """白名单段外 port（含端点外侧 2999/3101 与常用但未授权端口）应拒绝：
        端口白名单是安全边界，只允许杀开发端口段内的进程。"""
        r = read_json(kill_specific_process(bad_port))
        assert r["status"] == "error"
        assert "not in the allowed ranges" in r["message"]

    @pytest.mark.parametrize("edge_port", (3000, 3100, 5000, 5200, 8000, 8100))
    def test_kill_whitelist_boundaries_pass_check(self, monkeypatch, edge_port):
        """白名单端点（3000/3100/5000/5200/8000/8100）应放行至 lsof 阶段：
        白名单是闭区间（含端点），若实现误用开区间会在这里暴露；
        mock lsof 为空避免碰真实端口（端点可能被开发服务占用）。"""
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [])
        r = read_json(kill_specific_process(edge_port))
        assert r["status"] == "error"
        assert "No process listening" in r["message"]

    def test_kill_no_process_on_port(self):
        """白名单段内无进程监听的端口应返回明确 error（真实 lsof 路径）：
        找不到进程是常见业务场景，error 而非崩溃。"""
        port = _idle_port()
        r = read_json(kill_specific_process(port))
        assert r["status"] == "error"
        assert f"No process listening on port {port}." == r["message"]

    def test_kill_lsof_error_graceful(self, monkeypatch):
        """lsof 探测抛异常应兜底为 error 不裸炸：系统命令失败属于环境问题，
        必须结构化返回让模型可读（与 bash executor 兜底同一策略）。"""
        def boom(port):
            raise RuntimeError("lsof is broken")

        monkeypatch.setattr(_bash, "_lsof_pids", boom)
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "error"
        assert "Failed to find process on port 3005" in r["message"]


class TestKillSafetyChecks:
    """安全校验：自保、进程名解析与系统进程拒绝（mock 定位阶段）。"""

    def test_kill_refuses_agent_self(self, monkeypatch):
        """监听端口的是 agent 自身时应拒绝：自杀会让整个服务崩溃，
        自保检查是 kill 工具的第一安全约束。"""
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [os.getpid()])
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "error"
        assert "Refusing to kill PID" in r["message"]

    def test_kill_refuses_pid_one(self, monkeypatch):
        """PID 1（init）应拒绝：init 是所有进程的祖先，误杀导致系统级故障。"""
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [1])
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "error"
        assert "Refusing to kill PID 1" in r["message"]

    def test_kill_refuses_unresolvable_name(self, monkeypatch):
        """进程名获取失败应中止：名字是系统进程判定的依据，
        名字不可知时宁可不杀（PID 可能已被回收，名字为空即存疑）。"""
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [12345])
        monkeypatch.setattr(_bash, "_process_comm", lambda pid: "")
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "error"
        assert "Could not determine process name for PID 12345" in r["message"]

    @pytest.mark.parametrize("sys_name", ["launchd", "kernel_task", "WindowServer"])
    def test_kill_refuses_system_process(self, monkeypatch, sys_name):
        """系统进程名应拒绝（纵深防御）：即使 PID 通过自保检查，
        名字在系统名单内也必须中止——root 权限下系统进程也能被杀，
        必须依赖名字名单而非仅依赖权限兜底。"""
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [12345])
        monkeypatch.setattr(_bash, "_process_comm", lambda pid: sys_name)
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "error"
        assert f"Refusing to kill system process '{sys_name}'" in r["message"]


class TestKillSignalStrategy:
    """信号策略：TOCTOU 复检、优雅/强制升级与确认超时（mock 信号路径）。"""

    def test_kill_toctou_identity_changed(self, monkeypatch):
        """kill 前二次 lsof 发现 PID 不再监听应拒绝：PID 可能在两次检查间
        被回收复用，直接杀会误杀无辜进程——TOCTOU 防护是防误杀关键。"""
        calls = {"n": 0}

        def fake_lsof(port):
            calls["n"] += 1
            return [9999] if calls["n"] == 1 else []

        monkeypatch.setattr(_bash, "_lsof_pids", fake_lsof)
        monkeypatch.setattr(_bash, "_process_comm", lambda pid: "testapp")
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "error"
        assert "process identity changed between checks" in r["message"]

    def test_kill_toctou_recheck_failure(self, monkeypatch):
        """TOCTOU 复检抛异常应兜底为 error：复检失败意味着无法确认身份，
        保守拒绝而不是冒险发送信号。"""
        calls = {"n": 0}

        def fake_lsof(port):
            calls["n"] += 1
            if calls["n"] == 1:
                return [9999]
            raise RuntimeError("lsof vanished")

        monkeypatch.setattr(_bash, "_lsof_pids", fake_lsof)
        monkeypatch.setattr(_bash, "_process_comm", lambda pid: "testapp")
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "error"
        assert "TOCTOU re-check failed" in r["message"]

    def test_kill_permission_denied(self, monkeypatch):
        """信号发送权限不足应兜底为 error：非 root 杀他人进程被内核拒绝，
        返回结构化错误而非裸抛 PermissionError。"""
        def boom(pid, sig):
            raise PermissionError(13, "Operation not permitted")

        monkeypatch.setattr(os, "kill", boom)
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [9999])
        monkeypatch.setattr(_bash, "_process_comm", lambda pid: "testapp")
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "error"
        assert "Permission denied killing PID 9999" in r["message"]

    def test_kill_process_exited_in_race(self, monkeypatch):
        """SIGTERM 抛 ProcessLookupError（进程恰好在信号前自行退出）应视为
        成功：目标已死即达成目的，graceful=True 标记窗口期语义。"""
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [9999])
        monkeypatch.setattr(_bash, "_process_comm", lambda pid: "testapp")
        # 不 patch os.kill：PID 9999 不存在，真实调用自然抛 ProcessLookupError
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "ok"
        assert r["killed"] == [{
            "pid": 9999, "name": "testapp",
            "signal_used": "SIGTERM", "graceful": True,
        }]

    def test_kill_escalates_to_sigkill(self, monkeypatch):
        """SIGTERM 在宽限期内未退出应自动升级 SIGKILL：信号顺序必须为
        [SIGTERM, SIGKILL]，graceful=False 标记强制终止（升级策略锁定）。"""
        signals = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append(sig))
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [9999])
        monkeypatch.setattr(_bash, "_process_comm", lambda pid: "testapp")
        wait_calls = {"n": 0}

        def fake_wait(pid, seconds):
            wait_calls["n"] += 1
            return wait_calls["n"] >= 2  # 第一次 False（触发升级），第二次 True

        monkeypatch.setattr(_bash, "_wait_exit", fake_wait)
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "ok"
        assert signals == [signal.SIGTERM, signal.SIGKILL]
        assert r["killed"][0]["signal_used"] == "SIGKILL"
        assert r["killed"][0]["graceful"] is False

    def test_kill_confirm_failure(self, monkeypatch):
        """SIGKILL 后仍在确认期内未退出应返回 error：不可中断状态（D 态）
        连 SIGKILL 也杀不掉，必须显式失败而非假报成功。"""
        monkeypatch.setattr(os, "kill", lambda pid, sig: None)
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [9999])
        monkeypatch.setattr(_bash, "_process_comm", lambda pid: "testapp")
        monkeypatch.setattr(_bash, "_wait_exit", lambda pid, seconds: False)
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "error"
        assert "did not exit after SIGKILL" in r["message"]

    def test_kill_multiple_pids_all_success(self, monkeypatch):
        """同一端口多个监听者（SO_REUSEPORT）应全部终止：
        lsof 返回列表，循环逐 PID 处理，killed 包含全部。"""
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [9001, 9002])
        monkeypatch.setattr(_bash, "_process_comm", lambda pid: f"app{pid}")
        # 不 patch os.kill：9001/9002 不存在 → 窗口期路径，双杀成功
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "ok"
        assert len(r["killed"]) == 2
        assert {k["pid"] for k in r["killed"]} == {9001, 9002}
        assert all(k["graceful"] for k in r["killed"])

    def test_kill_multiple_pids_abort_on_system(self, monkeypatch):
        """多 PID 中任一为系统进程应整体中止：循环中途发现系统进程立即
        return error（半途语义：error 响应不携带 killed，已处理 PID 不报告）。"""
        monkeypatch.setattr(_bash, "_lsof_pids", lambda port: [9001, 9002])

        def fake_comm(pid):
            return "testapp" if pid == 9001 else "launchd"

        monkeypatch.setattr(_bash, "_process_comm", fake_comm)
        r = read_json(kill_specific_process(3005))
        assert r["status"] == "error"
        assert "system process 'launchd'" in r["message"]
        assert "killed" not in r  # 半途语义锁定：error 不携带 killed

    @pytest.mark.parametrize("port_arg,expect_port_field", [
        ("str_port", False),  # 类型错误分支：无 port 字段
        (0, True),            # 范围错误分支：有 port 字段
        (4000, True),         # 白名单错误分支：有 port 字段
    ])
    def test_kill_error_contract_variants(self, monkeypatch, port_arg, expect_port_field):
        """error 响应字段契约：类型错误仅 {status, tool_name, message}；
        范围/白名单业务错误携带 port 审计字段——字段集差异是响应契约的一部分，
        模型侧解析依赖固定字段集。"""
        if port_arg == "str_port":
            r = read_json(kill_specific_process("3000"))
        else:
            r = read_json(kill_specific_process(port_arg))
        assert r["status"] == "error"
        assert r["tool_name"] == "kill_specific_process"
        assert ("port" in r) is expect_port_field


class TestPidAliveUnit:
    """存活判定单测：僵尸进程与探测失败的边界语义（ps 状态字段）。"""

    @pytest.mark.parametrize("stat,expected", [
        ("S", True), ("R", True), ("T", True),   # 正常存活态
        ("Z", False),                            # 僵尸视为退出（回归）
        ("", False),                             # 空状态视为不存在
    ])
    def test_pid_alive_by_state(self, monkeypatch, stat, expected):
        """ps 状态字段判定：Z（僵尸）必须视为已退出——进程被 SIGKILL 后若
        父进程未 reap 会以僵尸存在，os.kill(pid, 0) 仍报存活导致误报
        "未退出"（历史 bug 回归）。"""
        class FakeResult:
            returncode = 0
            stdout = stat

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeResult())
        assert _bash._pid_alive(12345) is expected

    def test_pid_alive_missing_process(self, monkeypatch):
        """ps 返回非零退出码（进程不存在）应视为已退出。"""
        class FakeResult:
            returncode = 1
            stdout = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeResult())
        assert _bash._pid_alive(12345) is False

    def test_pid_alive_probe_failure_conservative(self, monkeypatch):
        """ps 探测抛异常应保守视为存活：探测失败不能误判"已退出"，
        否则 _wait_exit 会提前放行，把未死的进程当成功杀掉。"""
        def boom(*a, **k):
            raise OSError("ps is broken")

        monkeypatch.setattr(subprocess, "run", boom)
        assert _bash._pid_alive(12345) is True


class TestKillRealProcess:
    """端到端：真实监听进程 + 真实信号（核心价值，验证整条链路）。"""

    def test_kill_real_process_graceful(self):
        """真实优雅终止：监听进程收到 SIGTERM 立即退出（退出码 0），
        killed[0].pid 必须与子进程 PID 一致（防误杀他人进程的关键断言），
        杀后端口释放、二次调用返回 No process listening（幂等语义）。"""
        proc, port = start_port_listener("graceful")
        try:
            r = read_json(kill_specific_process(port))
            assert r["status"] == "ok"
            assert r["tool_name"] == "kill_specific_process"
            assert r["port"] == port
            assert len(r["killed"]) == 1
            assert r["killed"][0]["pid"] == proc.pid  # 杀的是我们起的进程
            assert r["killed"][0]["name"]  # 进程名非空（ps 真实解析）
            assert r["killed"][0]["signal_used"] == "SIGTERM"
            assert r["killed"][0]["graceful"] is True
            assert proc.wait(timeout=5) == 0  # 优雅退出码 0
            assert _wait_port_free(port), "kill 后端口应释放"

            # 重复调用：进程已死 → 明确 error（幂等，不误报成功）
            again = read_json(kill_specific_process(port))
            assert again["status"] == "error"
            assert "No process listening" in again["message"]
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    def test_kill_real_process_escalates_sigkill(self, monkeypatch):
        """真实强制升级：监听进程忽略 SIGTERM，宽限期（monkeypatch 缩短为
        0.5s 加速）后必须被 SIGKILL 强制终止，退出码 -9、graceful=False。"""
        monkeypatch.setattr(_bash, "KILL_GRACE_SECONDS", 0.5)
        proc, port = start_port_listener("stubborn")
        try:
            r = read_json(kill_specific_process(port))
            assert r["status"] == "ok"
            assert r["killed"][0]["pid"] == proc.pid
            assert r["killed"][0]["signal_used"] == "SIGKILL"
            assert r["killed"][0]["graceful"] is False
            assert proc.wait(timeout=5) == -signal.SIGKILL
            assert _wait_port_free(port), "SIGKILL 后端口应释放"
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    def test_kill_concurrent_distinct_ports(self):
        """并发杀两个不同端口的真实进程应全部成功：kill 无共享可变状态，
        互不干扰（并发安全是工具可被编排层并发的保证）。"""
        proc1, port1 = start_port_listener("graceful")
        proc2, port2 = start_port_listener("graceful")
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(kill_specific_process, [port1, port2]))
            for raw, proc, port in zip(results, (proc1, proc2), (port1, port2)):
                r = read_json(raw)
                assert r["status"] == "ok"
                assert r["killed"][0]["pid"] == proc.pid
                assert proc.wait(timeout=5) == 0
                assert _wait_port_free(port)
        finally:
            for proc in (proc1, proc2):
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
