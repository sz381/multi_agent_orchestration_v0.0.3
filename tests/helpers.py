"""测试工具模块

提供函数：
- read_json: 读取 JSON 字符串并返回 JSON 对象
- make_file: 生成指定行数与行长的文本文件，返回文件路径
- make_indexed_file: 生成每行内容带行号的文件，用于校验行号与内容对应
- make_text_file: 生成指定内容的文本文件（父目录自动创建）
- start_http_server: 在 127.0.0.1 随机端口启动 HTTP 探针服务器（bash 网络放行用例用）
- start_port_listener: 在白名单端口段内启动真实 TCP 监听子进程（kill_specific_process 端到端用）
- _wait_port_free: 轮询等待端口不再被监听（kill 端到端用例端口释放断言用）
- _idle_port: 挑一个白名单段内的空闲端口（kill 无进程监听用例用）
- _pid_exists: 检查 PID 对应的进程是否存在（超时整组终止验证用）
- rels: 将绝对路径列表转为相对路径集合（基于 realpath 归一化后的工作区根）
- _phase: 构造标准阶段字典（plan 三工具测试统一造数）
- _ok_phases: 构造 count 个互不重复的合法阶段
- _plan2: 标准两阶段计划（p1/p2）
- _plan3: 标准三阶段计划（p1/p2/p3）
- _task: 构造标准任务字典（fanout_subagents 测试统一造数）
- _ok_tasks: 构造 count 个互不重复的合法任务

使用注意：
- 本模块仅存放测试辅助函数，不包含测试用例
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


def read_json(raw: str) -> dict:
    """ 读取 JSON 字符串并返回 JSON 对象

    Args:
        raw: JSON 字符串。

    Returns:
        JSON 对象。
    """
    return json.loads(raw)


def make_file(
    workspace, 
    name: str, 
    line_count: int, 
    line_len: int = 21, 
    subdir: str | None = None
):
    """生成指定行数与行长的文本文件。

    每行内容为 line_len-1 个字符 'x' 加一个换行符，
    保证单行（含换行）恰好为 line_len 字节，便于精确控制文件大小。

    Args:
        workspace:       目标目录，通常为 pytest 的 tmp_path fixture 返回值。
        name:            文件名。
        line_count:      要生成的行数。
        line_len:        每行字节数（含换行符），默认 21。
        subdir:          可选子目录名，文件将创建在 workspace/subdir 下（不存在则自动创建）。

    Returns:
        生成文件的完整路径（pathlib.Path）。
    """
    path = (workspace / subdir if subdir else workspace) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    line = "x" * (line_len - 1) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(line_count):
            f.write(line)
    return path


def make_text_file(workspace, name: str, content: str):
    """生成指定内容的文本文件（父目录自动创建）。

    与 make_file / make_indexed_file 的确定性造数不同，本函数接受任意
    指定内容（含中文、多行、特殊字符），用于 str_replace 等写工具的
    精确内容断言场景。

    Args:
        workspace: 目标目录，通常为 pytest 的 tmp_path fixture 返回值。
        name:      文件名，可含子目录相对路径（如 "sub/a.py"）。
        content:   要写入的完整文本内容。

    Returns:
        生成文件的完整路径（pathlib.Path）。
    """
    path = workspace / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def start_http_server():
    """在 127.0.0.1 随机端口启动 HTTP 探针服务器。

    任何 GET 请求都返回固定内容 sandbox-http-ok，供 bash 网络放行用例
    （allow_network=True）验证沙箱网络模式真的放行；用 127.0.0.1 避免
    依赖外部网络，用随机端口避免端口冲突。

    Returns:
        (port, server)：port 为监听端口；server 为 HTTPServer 实例，
        用例结束后调用 server.shutdown() 关闭。
    """
    class _ProbeHandler(BaseHTTPRequestHandler):
        """探针处理器：任何 GET 请求都返回固定内容。"""

        def do_GET(self):
            body = b"sandbox-http-ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # 关闭默认访问日志，避免测试输出噪音

    server = HTTPServer(("127.0.0.1", 0), _ProbeHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port, server


def start_port_listener(mode: str = "graceful"):
    """在白名单端口段内启动真实 TCP 监听子进程（kill_specific_process 端到端用）。

    mode="graceful"：收到 SIGTERM 立即 sys.exit(0)（验证优雅终止路径）；
    mode="stubborn"：忽略 SIGTERM（验证 SIGKILL 升级路径）。

    端口选择：KILL_ALLOWED_PORTS 首段内随机 bind 探测（bind 成功即空闲），
    避免与开发环境端口冲突，也避免误杀他人进程。

    Returns:
        (proc, port)：Popen 实例与监听端口。用例结束必须兜底清理：
        if proc.poll() is None: proc.kill()；随后 proc.wait() reap。
    """
    from core.tools._kernel.constants import KILL_ALLOWED_PORTS

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
    # 等待端口可连接（子进程就绪）；子进程提前退出则立即失败
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
    """轮询等待端口不再被监听（TIME_WAIT 残留连接可能短暂干扰 lsof）。

    调用 kill_specific_process 后，进程退出与端口释放之间存在内核
    回收窗口（残留连接的 TIME_WAIT 会让 lsof 短暂仍报该端口），
    单次断言会 flaky，必须轮询。

    异步：依赖已 async 化的 _bash._lsof_pids，轮询用 asyncio.sleep
    不阻塞事件循环。

    Returns:
        端口在 seconds 秒内释放返回 True，超时返回 False。
    """
    from core.tools._kernel import _bash

    deadline = time.time() + seconds
    while time.time() < deadline:
        if not await _bash._lsof_pids(port):
            return True
        await asyncio.sleep(0.1)
    return False


def _idle_port() -> int:
    """挑一个白名单段内的空闲端口（bind 成功即空闲）后立即释放。

    用于 kill_specific_process 的"无进程监听"用例：选段内随机端口，
    bind 成功即证明当前无监听者，立即 close 后调用工具验证 No process
    listening（窗口极小，可接受）。

    Returns:
        空闲端口号；30 次尝试失败抛 RuntimeError。
    """
    from core.tools._kernel.constants import KILL_ALLOWED_PORTS

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
    """检查 PID 对应的进程是否存在（ps 退出码 0 即存在）。

    用于 bash 超时整组终止验证：killpg 后轮询组内子进程是否被连带
    终止。与 _bash._pid_alive 的语义不同：此处不区分僵尸态，只要
    ps 能查到即视为存在（验证目标是被终止而非仅变僵尸）。
    """
    result = subprocess.run(
        ["ps", "-p", str(pid)], capture_output=True, text=True, timeout=5
    )
    return result.returncode == 0


def make_indexed_file(workspace, name: str, line_count: int):
    """生成每行内容带行号的文件（第 i 行内容为 line-{i}）。

    与 make_file 的同质内容（全 x）不同，本函数用于验证读取结果中
    行号与内容的一一对应关系，内容错位类 bug 在此数据下必然暴露。

    Args:
        workspace:   目标目录，通常为 pytest 的 tmp_path fixture 返回值。
        name:        文件名。
        line_count:  要生成的行数。

    Returns:
        生成文件的完整路径（pathlib.Path）。
    """
    path = workspace / name
    with open(path, "w", encoding="utf-8") as f:
        for i in range(1, line_count + 1):
            f.write(f"line-{i}\n")
    return path


def rels(workspace, files: list[str]) -> set[str]:
    """将绝对路径列表转为相对路径集合（基于真实路径的工作区根）。

    工具（如 glob_tool）返回的是绝对路径，直接与期望列表对比时，
    根目录写法（如 macOS 的 /var 与 /private/var 符号链接差异）会
    导致断言脆弱；本函数先对工作区根做 realpath 归一化，再统一转成
    以根为基准的相对路径集合，断言只关注路径结构与文件名。

    Args:
        workspace: 工作区目录，通常为 pytest 的 tmp_path fixture 返回值。
        files:     工具返回的绝对路径列表（如 glob_tool 响应的 files 字段）。

    Returns:
        相对路径集合，元素不含工作区根前缀（如 {"a/b.py", "sub/data.txt"}）。
    """
    abs_ws = os.path.realpath(str(workspace))
    return {os.path.relpath(f, abs_ws) for f in files}


def _phase(**overrides):
    """构造标准阶段字典，overrides 覆盖默认字段。

    默认 phase_id="p1"/phase_name="阶段一"/phase_status="pending"/
    phase_description="描述一"，供 make/edit/delete 三工具测试统一造数。
    """
    phase = {
        "phase_id": "p1",
        "phase_name": "阶段一",
        "phase_status": "pending",
        "phase_description": "描述一",
    }
    phase.update(overrides)
    return phase


def _ok_phases(count):
    """构造 count 个互不重复的合法阶段。

    每个阶段 phase_id 依次为 p0/p1/...，其余字段取 _phase 默认值，
    用于上限边界（12）与超限（13）等批量造数场景。
    """
    return [_phase(phase_id=f"p{i}") for i in range(count)]


def _plan2():
    """标准两阶段计划（p1/p2）。

    供 edit_plan/delete_plan 的常规用例直接使用。
    """
    return [_phase(), _phase(phase_id="p2", phase_name="阶段二")]


def _plan3():
    """标准三阶段计划（p1/p2/p3）。

    供 edit_plan/delete_plan 的删除中间阶段、多阶段操作用例使用。
    """
    return [_phase(), _phase(phase_id="p2", phase_name="阶段二"), _phase(phase_id="p3", phase_name="阶段三")]


def _task(**overrides):
    """构造标准任务字典，overrides 覆盖默认字段。

    默认 task_id="t1"/task_name="任务一"/task_description="描述一"/
    task_completion_status=False/subagent_id="programmer_a"/
    subagent_name="程序员甲"，供 fanout_subagents 测试统一造数。
    """
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
    """构造 count 个互不重复的合法任务。

    每个任务 task_id 依次为 t0/t1/...，subagent_id 在三个合法前缀
    （programmer/reviewer/researcher）间轮换（如 programmer_0/reviewer_1/...），
    用于上限边界（20）与超限（21）等批量造数场景。
    """
    prefixes = ["programmer", "reviewer", "researcher"]
    tasks = []
    for i in range(count):
        prefix = prefixes[i % len(prefixes)]
        tasks.append(_task(task_id=f"t{i}", subagent_id=f"{prefix}_{i}"))
    return tasks
