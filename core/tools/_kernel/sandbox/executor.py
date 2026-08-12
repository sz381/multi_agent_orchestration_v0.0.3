"""macOS sandbox-exec + Seatbelt 沙箱命令执行器。

- 无降级回退：sandbox-exec 执行失败即报错（不尝试绕过沙箱）
- 输出上限 SANDBOX_MAX_OUTPUT_CHARS 截断（内存保护，与 _bash 层的显示截断解耦）
"""
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


def _exec(profile_path: str, cmd: str, cwd: str, timeout: int) -> dict:
    """用给定 profile 通过 sandbox-exec 执行命令。

    使用 Popen + start_new_session，超时后整个进程组（bash + 所有子进程）
    可被原子地 SIGKILL 终止。
    """
    # 防止代理的 venv 与 API key 泄漏进子进程：
    # 否则子进程继承 VIRTUAL_ENV 后会误用代理的 Python 环境，破坏所有依赖
    env = {k: v for k, v in os.environ.items() if k not in SANDBOX_ENV_STRIP and not _is_sensitive_env(k)}
    
    # 从 PATH 剔除代理的 .venv/bin；TMPDIR/HOME 默认指向 /tmp，
    # 防止子进程读取 ~/.gitconfig 等宿主配置
    env["PATH"] = _sandbox_path()
    env.setdefault("TMPDIR", "/tmp")
    env.setdefault("HOME", "/tmp")

    # macOS 的 /usr/bin/java 是 stub——Gradle/Maven 需要显式 JAVA_HOME
    if "JAVA_HOME" not in env:
        global _JAVA_HOME_CACHE
        if _JAVA_HOME_CACHE is None:
            _JAVA_HOME_CACHE = _find_java_home()
        if _JAVA_HOME_CACHE:
            env["JAVA_HOME"] = _JAVA_HOME_CACHE

    # pipefail：管道退出码取最右侧非零段（而非最后一段），
    # 防止 `cmd 2>&1 | tail -40` 用 tail 的退出码 0 掩盖真实失败
    args = ["sandbox-exec", "-f", profile_path, "bash", "-o", "pipefail", "-c", cmd]

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,  # 新会话 = 新进程组，便于干净地整组终止
    )

    try:
        stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        stderr, violations = _strip_sandbox_msgs(stderr)
        
    except subprocess.TimeoutExpired:
        # 终止整个进程组：bash + 所有子进程
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        return {"exit_code": None, "stdout": "", "stderr": "", "timeout": True, "sandbox_violations": 0}

    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timeout": False,
        "sandbox_violations": violations,
    }


def run(cmd: str, workspace: str, cwd: str = ".", timeout: int = 30, allow_network: bool = True) -> dict:
    """在 Seatbelt 沙箱中执行 bash 命令。

    Args:
        cmd: 要执行的 bash 命令。
        workspace: 项目根目录绝对路径。
        cwd: 工作目录（绝对路径）。
        timeout: 超时时间（秒），默认 30。
        allow_network: True 走网络 profile，False 走 air-gapped（禁网）。

    Returns:
        {"exit_code": int|None, "stdout": str, "stderr": str, "timeout": bool, "sandbox_violations": int}
    """
    profile_text = (
        generate_default(workspace=workspace)   
        if allow_network
        else generate_air_gapped(workspace=workspace)
    )

    # 将沙箱 profile 写入临时文件，执行后清理
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sb", delete=False) as pf:
        pf.write(profile_text)
        profile_path = pf.name

    try:
        result = _exec(profile_path, cmd, cwd, timeout)
    finally:
        try:
            os.unlink(profile_path)
        except OSError:
            pass

    # 截断输出
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
