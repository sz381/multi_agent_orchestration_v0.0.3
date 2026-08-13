"""macOS sandbox-exec + Seatbelt 沙箱命令执行器。

- 无降级回退：sandbox-exec 执行失败即报错（不尝试绕过沙箱）
- 输出上限 SANDBOX_MAX_OUTPUT_CHARS 截断（内存保护，与 _bash 层的显示截断解耦）
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

# 项目根目录——用于从子进程 PATH 中剔除代理自身的 .venv
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

# JAVA_HOME 探测结果缓存（只探测一次）
_JAVA_HOME_CACHE: str | None = None


def _is_sensitive_env(key: str) -> bool:
    """判断环境变量名是否像敏感凭据（API key/token 等）。"""
    upper = key.upper()
    return any(pattern in upper for pattern in SANDBOX_SENSITIVE_ENV_KEYWORDS)


def _find_java_home() -> str | None:
    """探测 JAVA_HOME（环境未设置时）。

    macOS 的 /usr/bin/java 是 stub，Gradle/Maven 需要显式 JAVA_HOME。
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
    """宿主 PATH 剔除代理自身的 .venv/bin，其余原样透传。"""
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
    """从 stderr 中过滤 macOS Seatbelt 违规日志行。

    Returns:
        清洗后的 stderr 与移除的违规行数量。
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
    """用给定 profile 通过 sandbox-exec 异步执行命令（真异步版 _exec）。

    与 _exec 语义完全一致：start_new_session 建独立进程组，超时后整组
    （bash + 所有子进程）SIGKILL；差异在于子进程由事件循环直接管理
    （create_subprocess_exec + wait_for），不占用线程池线程，且可取消。

    Args:
        profile_path: Seatbelt profile 临时文件路径。
        cmd: 要执行的 bash 命令。
        cwd: 工作目录（绝对路径）。
        timeout: 超时时间（秒），超过后整组 SIGKILL。

    Returns:
        {"exit_code": int|None, "stdout": str, "stderr": str,
         "timeout": bool, "sandbox_violations": int}，契约与 _exec 一致。
    """
    # 环境准备与 _exec 完全一致：剔除代理 venv 与敏感凭据，PATH 去 .venv，
    # TMPDIR/HOME 重定向到 /tmp（防止子进程按 $HOME 拼接读取宿主配置）
    env = {k: v for k, v in os.environ.items() if k not in SANDBOX_ENV_STRIP and not _is_sensitive_env(k)}
    env["PATH"] = _sandbox_path()
    env["TMPDIR"] = "/tmp"
    env["HOME"] = "/tmp"

    # macOS 的 /usr/bin/java 是 stub——Gradle/Maven 需要显式 JAVA_HOME；
    # 首次探测是同步 subprocess.run（最多 5s），丢线程池避免阻塞事件循环，只发生一次
    if "JAVA_HOME" not in env:
        global _JAVA_HOME_CACHE
        if _JAVA_HOME_CACHE is None:
            _JAVA_HOME_CACHE = await asyncio.to_thread(_find_java_home)
        if _JAVA_HOME_CACHE:
            env["JAVA_HOME"] = _JAVA_HOME_CACHE

    # pipefail：管道退出码取最右侧非零段（而非最后一段），
    # 防止 `cmd 2>&1 | tail -40` 用 tail 的退出码 0 掩盖真实失败
    args = ["sandbox-exec", "-f", profile_path, "bash", "-o", "pipefail", "-c", cmd]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,  # 新会话 = 新进程组，便于干净地整组终止
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
        # 终止整个进程组：bash + 所有子进程（与 _exec 一致）；
        # wait_for 超时已取消 communicate，kill 后 wait 收尸
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
    """在 Seatbelt 沙箱中异步执行 bash 命令（真异步版 run）。

    语义与 run 完全一致：profile 生成 → 临时文件 → 执行 → 清理 → 截断；
    差异在于子进程由事件循环直接管理（_exec_async），不占用线程池线程。

    Args:
        cmd: 要执行的 bash 命令。
        workspace: 项目根目录绝对路径。
        cwd: 工作目录（绝对路径）。
        timeout: 超时时间（秒），默认 30。
        allow_network: True 走网络 profile，False 走 air-gapped（禁网）。

    Returns:
        {"exit_code": int|None, "stdout": str, "stderr": str,
         "timeout": bool, "sandbox_violations": int}
    """
    profile_text = (
        generate_default(workspace=workspace)
        if allow_network
        else generate_air_gapped(workspace=workspace)
    )

    # 将沙箱 profile 写入临时文件，执行后清理（微秒级小文件，留在事件循环）
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

    # 截断输出（与 run 一致）
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
