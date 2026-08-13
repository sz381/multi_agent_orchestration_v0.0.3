"""Agent 系统命令行工具实现

⚠️ 本模块仅支持 macOS（sandbox-exec + Seatbelt 沙箱）

提供函数：
- bash:                     执行 bash 命令
- kill_specific_process:    杀死特定进程

关键约束：
- 统一返回 JSON 字符串（status: ok/error），执行异常被兜底捕获不抛出
- 参数类型安全：allow_network 必须为 bool（字符串 "false" 是 truthy，会误放行网络）；
  timeout 必须为 int/float 且 > 0（bool 是 int 子类需显式排除）；cmd/cwd 必须为字符串
- 黑名单校验先行：命中 BLACKLIST_PATTERNS 正则集合的命令拒绝执行
  （Seatbelt 沙箱为第一道防线，黑名单为纵深防御）
- cwd 必须是工作区子目录（路径边界归一化防前缀匹配陷阱）；
  工作区未配置时立即报错（配置错误不返回 error JSON）
- 输出截断：stdout/stderr 单路最多返回 BASH_MAX_OUTPUT_CHARS 字符
- kill_specific_process 为 bash 沙箱的安全出口：Seatbelt 规则仅允许
  (allow signal (target self))，bash 无法杀其他进程；该工具在沙箱外
  直接操作，仅允许 KILL_ALLOWED_PORTS 白名单端口，拒绝 agent 自身/
  PID 1/系统进程，kill 前二次校验防 PID 复用（TOCTOU）
- kill_specific_process 信号策略：SIGTERM 优雅终止，KILL_GRACE_SECONDS
  秒未退出自动升级 SIGKILL，再等待 KILL_CONFIRM_SECONDS 确认退出

使用注意：
- 依赖 sandbox 层（sandbox/executor.py + sandbox/profile.py）：allow_network=True
  走网络模式（全局读 + 工作区写 + 全网络），False 走 air-gapped 模式（禁网）
- 子进程环境隔离：剔除 VIRTUAL_ENV/PYTHONPATH 等代理环境变量与含敏感关键字的
  环境变量，防止泄漏到子进程
- 超时后整组进程（bash + 所有子进程）被 SIGKILL 终止
- kill_specific_process 依赖 lsof/ps（macOS 自带）；TOCTOU 校验要求两次
  lsof 探测一致，进程反复重启的极端场景下可能保守误拒
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
    """在 Seatbelt 沙箱中执行 shell 命令。

    ⚠️ 本模块仅支持 macOS（sandbox-exec + Seatbelt 沙箱）。

    执行模型：参数校验、黑名单与路径安全链（纯 CPU）留在事件循环；
    sandbox-exec 子进程由事件循环直接管理（asyncio.create_subprocess_exec），
    不占用线程池线程且超时可取消（wait_for + 整组 SIGKILL）。

    参数：
        cmd：要执行的 shell 命令。
        cwd：相对于工作区的工作目录（默认为 '.'）。
        timeout：超时时间（秒），超过后自动终止（默认为 30）。
        allow_network：是否允许网络访问（默认为 True）。

    返回值：
        包含 status/exit_code/stdout/stderr/耗时以及沙箱违规信息的 JSON 字符串。
    """
    # 参数检查：cmd 必须是字符串
    if not isinstance(cmd, str):
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": "cmd must be a string.",
        }, ensure_ascii=False)

    # 参数检查：cmd 必须是非空字符串
    if not cmd.strip():
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": "cmd must be a non-empty string.",
        }, ensure_ascii=False)

    # 参数检查：allow_network 必须是布尔值（字符串 "false" 是 truthy，会误放行网络）
    if not isinstance(allow_network, bool):
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": "allow_network must be a boolean.",
        }, ensure_ascii=False)

    # 参数检查：timeout 必须是 int/float（bool 是 int 子类需显式排除）
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": "timeout must be a number.",
        }, ensure_ascii=False)

    # 参数检查：timeout 必须大于 0
    if timeout <= 0:
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": f"timeout must be > 0, got {timeout}.",
        }, ensure_ascii=False)

    # 参数检查：cwd 必须是字符串
    if not isinstance(cwd, str):
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": "cwd must be a string.",
        }, ensure_ascii=False)

    # 检查命令是否被安全策略阻止 - 黑名单校验（cmd 已确认为字符串）
    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, cmd):
            return json.dumps({
                "status": "error",
                "tool_name": "bash",
                "message": f"Command blocked by security policy: {cmd}",
            }, ensure_ascii=False)

    # 获取工作区目录，确保其存在并为绝对路径，注意！这是个极其严重的问题，工作区必须设置，如果未设置则必须立即报错！
    workspace = settings.workspace_dir
    if not workspace:
        raise RuntimeError("WORKSPACE_DIR is not configured, please set it up.")
    workspace = os.path.abspath(workspace)

    # 路径边界归一化，把工作区根统一成 恰好一个结尾分隔符 的格式，防止前缀匹配陷阱. 
    safe_root = workspace.rstrip(os.sep) + os.sep

    # 确保 cwd 是绝对路径，并且是工作区的子目录。realpath 归一化
    # 统一消解多斜杠与 .. 后再做前缀检查：若直接对用户传入的绝对路径
    # 做字面前缀匹配，workspace///../../某目录 可穿越到工作区外。
    if not os.path.isabs(cwd):
        cwd = os.path.join(safe_root, cwd)
    cwd = os.path.realpath(cwd)

    # 确保 cwd 是工作区的子目录
    if not (cwd + os.sep).startswith(safe_root):
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": f"cwd '{cwd}' is outside the workspace.",
        }, ensure_ascii=False)

    # 确保 timeout 大于 0
    if timeout <= 0:
        return json.dumps({
            "status": "error",
            "tool_name": "bash",
            "message": f"timeout must be > 0, got {timeout}.",
        }, ensure_ascii=False)

    # 记录开始时间，用于计算耗时
    started = time.monotonic()

    # 执行命令（真异步：子进程由事件循环管理，不占线程池）
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

    # 记录结束时间，用于计算耗时
    elapsed = time.monotonic() - started

    # 输出截断：单路最多 BASH_MAX_OUTPUT_CHARS 字符（截断标记统一 ASCII）
    stdout = result["stdout"].strip()
    stderr = result["stderr"].strip()
    stdout_show = stdout[:BASH_MAX_OUTPUT_CHARS] + (
        "..." if len(stdout) > BASH_MAX_OUTPUT_CHARS else "")
    stderr_show = stderr[:BASH_MAX_OUTPUT_CHARS] + (
        "..." if len(stderr) > BASH_MAX_OUTPUT_CHARS else "")

    # 构造返回结果
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
    """运行短时探测命令（lsof/ps），返回 (returncode, stdout)。

    供 kill_specific_process 的进程探测复用：子进程由事件循环直接管理
    （create_subprocess_exec），不占用线程池线程；超时（>5s）时先
    kill 收尸再抛 TimeoutError，由调用方决定降级语义。

    Args:
        args: 探测命令 argv 列表（如 ["lsof", "-ti", "tcp:8000"]）。

    Returns:
        (returncode, stdout 文本)；stdout 以 utf-8 容错解码。
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except TimeoutError:
        # wait_for 已取消 communicate，先终止再收尸，避免探测进程泄漏
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode, stdout_bytes.decode("utf-8", errors="replace")


async def _lsof_pids(port: int) -> list[int]:
    """返回监听指定 TCP 端口的 PID 列表（lsof 退出码 1 表示无匹配）。

    Args:
        port: 要查询的 TCP 端口。

    Returns:
        PID 列表；lsof 无匹配或输出无有效数字时为空列表。
        探测超时抛 TimeoutError，由调用方兜底转 error 响应。
    """
    returncode, stdout = await _run_probe(["lsof", "-ti", f"tcp:{port}"])
    if returncode != 0:
        return []
    return [int(pid) for pid in stdout.split() if pid.strip().isdigit()]


async def _process_comm(pid: int) -> str:
    """返回进程名（ps 的 comm 字段）；进程不存在或获取失败返回空串。

    Args:
        pid: 目标进程 ID。

    Returns:
        进程名；探测失败（含超时/进程不存在）返回空串。
    """
    try:
        returncode, stdout = await _run_probe(["ps", "-p", str(pid), "-o", "comm="])
        if returncode == 0:
            return stdout.strip()
    except Exception:
        pass
    return ""


async def _pid_alive(pid: int) -> bool:
    """检查进程是否存活（ps 状态字段；僵尸 Z 视为已退出）。

    不能用 os.kill(pid, 0) 探测：进程被 SIGKILL 后若父进程未 reap，
    会以僵尸态存在，0 信号探测仍返回存在，导致误报"未退出"。

    Args:
        pid: 目标进程 ID。

    Returns:
        True 表示存活；ps 探测失败时保守视为存活（后续有权限错误兜底）。
    """
    try:
        returncode, stdout = await _run_probe(["ps", "-p", str(pid), "-o", "stat="])
        if returncode != 0:
            return False  # 进程不存在
        stat = stdout.strip()
        return bool(stat) and "Z" not in stat
    except Exception:
        return True


async def _wait_exit(pid: int, seconds: float) -> bool:
    """轮询等待进程退出，最多 seconds 秒；已退出返回 True。

    Args:
        pid:     目标进程 ID。
        seconds: 最长等待秒数。

    Returns:
        True 表示已退出；超时仍存活返回 False。
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not await _pid_alive(pid):
            return True
        await asyncio.sleep(KILL_POLL_INTERVAL)
    return not await _pid_alive(pid)


async def kill_specific_process(port: int) -> str:
    """杀死监听指定端口的进程（bash 沙箱的安全出口）。

    ⚠️ 仅 macOS。Seatbelt 沙箱规则只允许 (allow signal (target self))，
    bash 工具无法杀死其他进程——本工具在沙箱外直接操作，是唯一能
    停止开发服务器（npm run dev、uvicorn 等）的入口。

    安全边界：
    - port 必须落在 KILL_ALLOWED_PORTS 端口段白名单内
    - 拒绝 kill agent 自身（os.getpid()）与 PID 1
    - 拒绝系统进程（KILL_SYSTEM_PROCESS_NAMES）
    - TOCTOU 防护：kill 前二次 lsof 确认 PID 仍监听该端口，防 PID 复用误杀

    信号策略：先 SIGTERM 优雅终止，KILL_GRACE_SECONDS 秒内未退出自动
    升级 SIGKILL，再等待 KILL_CONFIRM_SECONDS 确认退出。

    执行模型：参数校验与白名单检查（纯 CPU）留在事件循环；lsof/ps 探测
    子进程由事件循环直接管理（create_subprocess_exec），退出轮询用
    asyncio.sleep 异步休眠，不占用线程池线程。

    参数：
        port：目标端口（1~65535）。

    返回值：
        包含 status/port/killed 列表（pid/name/signal_used/graceful）的 JSON 字符串。
    """
    # 参数检查：port 必须是 int（bool 是 int 子类需显式排除）
    if not isinstance(port, int) or isinstance(port, bool):
        return json.dumps({
            "status": "error",
            "tool_name": "kill_specific_process",
            "message": "port must be an integer.",
        }, ensure_ascii=False)

    # 参数检查：port 必须在合法端口范围
    if not 1 <= port <= 65535:
        return json.dumps({
            "status": "error",
            "tool_name": "kill_specific_process",
            "port": port,
            "message": f"port must be in 1..65535, got {port}.",
        }, ensure_ascii=False)

    # 端口白名单：只允许杀 KILL_ALLOWED_PORTS 段内的开发端口
    if not any(lo <= port <= hi for lo, hi in KILL_ALLOWED_PORTS):
        return json.dumps({
            "status": "error",
            "tool_name": "kill_specific_process",
            "port": port,
            "message": f"Port {port} is not in the allowed ranges: {list(KILL_ALLOWED_PORTS)}.",
        }, ensure_ascii=False)

    # 定位监听进程（沙箱外只读操作，lsof 是 macOS 自带工具）
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

    # 逐 PID 校验并终止（lsof 可能返回多个监听者）
    killed = []
    for pid in pids:
        # 自保检查：拒绝 kill agent 自身与 PID 1
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

        # 系统进程拒绝（纵深防御；root 进程通常也会因权限不足被兜底拦截）
        if name in KILL_SYSTEM_PROCESS_NAMES:
            return json.dumps({
                "status": "error",
                "tool_name": "kill_specific_process",
                "port": port,
                "message": f"Refusing to kill system process '{name}' (PID {pid}).",
            }, ensure_ascii=False)

        # TOCTOU 防护：kill 前二次校验 PID 仍监听该端口（防 PID 复用误杀）
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

        # SIGTERM 优雅终止；进程已自行退出视为成功（窗口期）
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

        # 等待优雅退出；超时未退出则升级 SIGKILL 强制终止
        signal_used = "SIGTERM"
        graceful = True
        if not await _wait_exit(pid, KILL_GRACE_SECONDS):
            try:
                os.kill(pid, signal.SIGKILL)
                signal_used = "SIGKILL"
                graceful = False
            except ProcessLookupError:
                pass  # 已在 SIGTERM 与 SIGKILL 之间退出
            except PermissionError:
                return json.dumps({
                    "status": "error",
                    "tool_name": "kill_specific_process",
                    "port": port,
                    "message": f"Permission denied killing PID {pid} ({name}).",
                }, ensure_ascii=False)

        # SIGKILL 后确认退出（不可中断状态/僵尸可能残留）
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
