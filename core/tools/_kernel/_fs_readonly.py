"""工作区只读文件系统工具实现

提供函数：
- view_file:        按行号读取文件内容，支持分段续读（单次最多 1MB）
- glob_tool:        按 glob 模式匹配查找文件，支持 ** 递归与 fnmatch 通配
- grep_tool:        正则搜索文件内容，支持三种输出模式与分页

关键约束：
- 所有工具统一返回 JSON 字符串（status: ok/error），不抛异常
  （唯一例外：workspace 未配置时抛 RuntimeError，属配置错误而非业务错误）
- 路径默认限制在工作区内：realpath 归一化 + 边界前缀检查，
  allow_external_reads=True 时方可越界访问；目录符号链接不跟随（防逃逸）
- 返回路径均为工作区内绝对路径（realpath 归一化），三工具契约一致
- EXCLUDE_DIRS / EXCLUDE_FILES 由 glob 与 grep 共享剪枝，既不返回也不进入
- 资源硬上限：MAX_READ_SIZE（单次读 1MB）、GLOB_MAX_RESULTS（200 结果）、
  GLOB_MAX_SCAN / GREP_MAX_FILES（5000 扫描上限）、GREP_MAX_FILE_SIZE（10MB 单文件）
- 二进制防护：读取前 NUL 字节嗅探（BINARY_SNIFF_BYTES），UTF-16/32 白名单放行；
  命中判定后 view_file 返回 error，grep 静默跳过（批量扫描语义）
- 超时熔断：正则单次匹配 REGEX_MATCH_TIMEOUT_SECONDS（防灾难性回溯），
  grep 整次搜索另有 GREP_TOTAL_TIMEOUT_SECONDS wall-clock 总预算

使用注意：
- view_file 大文件分段读取：用 offset=end_line+1 续读，直至 has_more=False
- glob_tool 需搜索排除目录内部时，将 dir_path 直接指向该目录即可
- grep_tool 的 glob_pattern 只匹配文件名（basename），不支持 ** 与路径分隔符，
  限定子目录请用 path 参数
- grep_tool 超时返回已收集的部分结果：timed_out_files 为单行超时熔断计数，
  search_timed_out=True 表示结果不完整（不是错误）
- 本模块只读；写操作请使用 _fs_mutate
"""

import os
import regex as re
import json
import fnmatch
import time

from core.tools._kernel.constants import (
    MAX_READ_SIZE,
    VIEW_FILE_MAX_SKIP_BYTES,
    BINARY_SNIFF_BYTES,
    EXCLUDE_DIRS,
    EXCLUDE_FILES,
    GLOB_MAX_RESULTS,
    GLOB_MAX_SCAN,
    GREP_MAX_FILES,
    GREP_MAX_FILE_SIZE,
    GREP_TOTAL_TIMEOUT_SECONDS,
    REGEX_MATCH_TIMEOUT_SECONDS,
)
from utils.settings import settings


def view_file(
    file_path: str,
    offset: int = 1,
    limit: int = 100,
    encoding: str = "utf-8",
    allow_external_reads: bool = False,
) -> str:
    """按行号读取文件内容，从指定行开始读取指定行数。

    支持大文件：每次读取最多 1MB 数据（按行截断），offset 可指向任意行，
    目标行之前的行会被跳过（跳过超过 VIEW_FILE_MAX_SKIP_BYTES 时仅提示、不中断），
    调用方可使用 offset=end_line+1 分段续读，直至 has_more=False。

    Args:
        file_path:              文件路径（工作区相对路径或绝对路径）。
        offset:                 起始显示行（从 1 开始，默认 1）。
        limit:                  最大返回行数（1-1000，默认 100）。
        encoding:               文件编码（默认 utf-8）。
        allow_external_reads:   是否允许读取工作区以外的文件。

    Returns:
        JSON 字符串。
        status 为 "ok" 时：path、read_lines、start_line、end_line、has_more、truncated、
                          lines（[{line_no, content}]），截断或跳过开销过大时附加 message 提示；
        status 为 "error" 时：仅 message。

    Notes:
        - has_more 为 True 表示文件仍有未返回的行（truncated 时恒为 True）
        - 分段续读：下次调用使用 offset=end_line+1
        - offset 超过文件总行数时返回 error；恰好指向末尾下一行时返回空结果
    """
    # 参数校验：file_path 参数不能为空
    if not file_path or not file_path.strip():
        return json.dumps({
            "status": "error",
            "message": "file_path must not be empty."
        }, ensure_ascii=False)

    # 参数校验：limit 参数必须是 1-1000 的整数（bool 是 int 子类，需排除）
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 1000:
        return json.dumps({
            "status": "error",
            "message": "limit must be an integer between 1 and 1000."
        }, ensure_ascii=False)

    # 参数校验：offset 参数必须是正整数
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 1:
        return json.dumps({
            "status": "error",
            "message": "offset must be a positive integer."
        }, ensure_ascii=False)

    # 获取工作区目录，确保其存在并为绝对路径，注意！这是个极其严重的问题，工作区必须设置，如果未设置则必须立即报错！
    workspace = settings.workspace_dir
    if not workspace:
        raise RuntimeError("WORKSPACE_DIR is not configured, please set it up.")
    workspace = os.path.abspath(workspace)

    # 在 abspath 基础上，递归解析所有符号链接，返回磁盘上的真实路径
    try:
        safe_root = os.path.realpath(workspace)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot resolve workspace: {exc}"
        }, ensure_ascii=False)

    # 家目录展开，如果 file_path 传入的是 ~ 或 ~用户名，例如：~/Desktop/foo.py --> /home/user/Desktop/foo.py
    file_path = os.path.expanduser(file_path)

    # 解析 file_path 参数传入的文件路径，确保其存在并为绝对路径
    try:
        if not os.path.isabs(file_path):
            file_path = os.path.realpath(os.path.join(safe_root, file_path))
        else:
            file_path = os.path.realpath(file_path)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Invalid path: {exc}"
        }, ensure_ascii=False)

    # 路径边界归一化，把工作区根统一成 恰好一个结尾分隔符 的格式，防止前缀匹配陷阱. 
    # 剥掉结尾所有分隔符：/Users/foo/// --> /Users/foo，再补恰好一个：--> /Users/foo/
    safe_root = safe_root.rstrip(os.sep) + os.sep

    # 路径越界检查，确保 file_path 在工作区目录下
    if not allow_external_reads and not file_path.startswith(safe_root):
        return json.dumps({
            "status": "error",
            "message": f"Access to '{file_path}' is denied."
        }, ensure_ascii=False)

    # 文件存在性检查，确保 file_path 指向的文件存在
    if not os.path.exists(file_path):
        return json.dumps({
            "status": "error",
            "message": f"File '{file_path}' does not exist."
        }, ensure_ascii=False)

    # 文件类型检查，确保 file_path 指向的不是目录
    if os.path.isdir(file_path):
        return json.dumps({
            "status": "error",
            "message": f"'{file_path}' is a directory."
        }, ensure_ascii=False)

    # 核心读取逻辑：跳过 offset-1 行后，按需读取直到 limit / EOF / 1MB 截断
    try:
        # 二进制嗅探：以二进制模式读取文件头部，检测 NUL 字节；
        # UTF-16/UTF-32 文本编码天然含 NUL，白名单放行
        with open(file_path, "rb") as f:
            head = f.read(BINARY_SNIFF_BYTES)
        if b"\x00" in head and not encoding.lower().startswith(("utf-16", "utf-32")):
            return json.dumps({
                "status": "error",
                "message": (
                    f"'{file_path}' appears to be a binary file. "
                    "If it is a text file, it may use an encoding "
                    "that contains NUL bytes (e.g. UTF-16)."
                )
            }, ensure_ascii=False)

        with open(file_path, "r", encoding=encoding) as f:
            messages: list[str] = []            # 用于存储提示信息，非致命错误会追加到此列表中
            skipped_lines = 0                   # 用于记录已跳过行数
            skipped_bytes = 0                   # 用于记录已跳过字节总量
            skip_warned = False                 # 用于记录是否已提示跳过开销过大

            # 先跳过 offset-1 行，确保从 offset 行开始读取
            while skipped_lines < offset - 1:
                # 读取一行
                line = f.readline()

                # EOF, 如果读取为空，表示文件提前结束
                if not line:
                    return json.dumps({
                        "status": "error",
                        "message": (
                            f"Start line {offset} exceeds total lines "
                            f"(file has only {skipped_lines} lines)."
                        )
                    }, ensure_ascii=False)
                    
                # 跳过当前行，增加已跳过行数和字节数
                skipped_lines += 1
                skipped_bytes += len(line.encode(encoding))

                # 如果跳过字节数超过阈值且未提示，则提示跳过开销过大
                if not skip_warned and skipped_bytes > VIEW_FILE_MAX_SKIP_BYTES:
                    skip_warned = True
                    messages.append(
                        f"Skipped > {VIEW_FILE_MAX_SKIP_BYTES // 1024 // 1024} MB to reach "
                        f"offset {offset}; reading remains available but expensive."
                    )

            # 从 offset 行开始读取，直到达到 limit、EOF 或累计超过 MAX_READ_SIZE
            lines: list[str] = []                # 用于存储读取的行
            bytes_read = 0                       # 用于记录已读字节数
            truncated = False                    # 用于记录是否截断

            # 循环读取，直到达到 limit 行数限制或文件结束
            while len(lines) < limit:
                # 读取一行，如果文件结束则跳出循环（EOF），表示文件内容提前结束
                line = f.readline()
                if not line:
                    break

                # 计算当前行的字节数，如果加上当前行的字节数超过 MAX_READ_SIZE，则截断并跳出循环
                line_bytes = len(line.encode(encoding))
                if bytes_read + line_bytes > MAX_READ_SIZE:
                    truncated = True
                    break

                # 将当前行添加到结果列表中，并增加已读字节数
                lines.append(line)
                bytes_read += line_bytes

            # 判定 has_more：截断时恒为 True；未截断且读满 limit 行时探测 EOF
            has_more = truncated
            if not truncated and len(lines) == limit:
                pos = f.tell()
                if f.read(1):
                    has_more = True
                f.seek(pos)

            # 如果没有读取到任何行：
            if not lines:
                if truncated:
                    messages.append(
                        f"Line at offset {offset} exceeds {MAX_READ_SIZE // 1024 // 1024} MB "
                        f"limit, cannot return any line. Use offset={offset + 1} to skip it."
                    )
                result = {
                    "status": "ok",
                    "path": file_path,
                    "read_lines": 0,
                    "start_line": offset,
                    "end_line": offset - 1,
                    "has_more": has_more,
                    "truncated": truncated,
                    "lines": [],
                }
                if messages:
                    result["message"] = " ".join(messages)
                return json.dumps(result, ensure_ascii=False)

            # 构建返回数据，包含文件路径、读取行数、起始行、结束行、是否截断、行内容列表
            start_line = offset
            end_line = offset + len(lines) - 1
            numbered_lines = [
                {"line_no": i, "content": line.rstrip("\n")}
                for i, line in enumerate(lines, start=start_line)
            ]
            result = {
                "status": "ok",
                "path": file_path,
                "read_lines": len(lines),
                "start_line": start_line,
                "end_line": end_line,
                "has_more": has_more,
                "truncated": truncated,
                "lines": numbered_lines,
            }
            if truncated:
                messages.append(
                    f"Read limited to {MAX_READ_SIZE // 1024 // 1024} MB "
                    f"(showing {len(lines)} lines). Use offset={end_line + 1} to continue."
                )
            if messages:
                result["message"] = " ".join(messages)
            return json.dumps(result, ensure_ascii=False)

    # 二次兜底检测，防止潜在发生的 race conditions 绕过之前的检测
    except FileNotFoundError:
        return json.dumps({
            "status": "error",
            "message": f"File '{file_path}' does not exist."
        }, ensure_ascii=False)
    except IsADirectoryError:
        return json.dumps({
            "status": "error",
            "message": f"'{file_path}' is a directory."
        }, ensure_ascii=False)
    except PermissionError:
        return json.dumps({
            "status": "error",
            "message": f"Permission denied: '{file_path}'."
        }, ensure_ascii=False)
    except UnicodeDecodeError:
        return json.dumps({
            "status": "error",
            "message": (
                f"{file_path} cannot be decoded as {encoding}. "
                f"Retry with encoding='gbk' or 'latin-1' if needed."
            )
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot read {file_path}: {exc}"
        }, ensure_ascii=False)


def _glob_walk(
    root: str,
    parts: list[str],
    results: list[str],
    limits: dict[str, int | bool],
) -> None:
    """glob 递归匹配引擎：按模式段逐层匹配目录条目。

    每层递归消费 parts 的一段：
    - 普通段：fnmatch 匹配当前目录条目名，匹配的目录继续递归剩余段
    - ** 段：跨任意层——先尝试零层（跳过 **），再对每个子目录继续完整模式
    - EXCLUDE_DIRS / EXCLUDE_FILES 在递归与记录时剪枝
    - limits 跨递归共享：total 累计匹配数，stop 熔断后所有在途调用立即返回

    Args:
        root:       当前扫描目录的绝对路径。
        parts:      剩余待匹配的模式段（如 ["**", "*.py"]）。
        results:    共享的结果列表，匹配路径追加于此（受 GLOB_MAX_RESULTS 截断）。
        limits:     共享的计数与熔断标志（{"total": 匹配数, "stop": 是否熔断}）。

    Returns:
        None，结果写入 results，熔断状态写入 limits。
    """
    # 熔断检查：每一层递归进来先看"是否已经喊停"。
    # limits["total"] 是共享的，某层的某个分支把计数顶到 5000 后设置 stop = True，
    # 但递归树上还有一堆已经在半路的调用——它们进来第一件事就是看到 stop，立刻返回。
    if limits["stop"]:
        return

    # parts 为空：所有模式段都消费完了，当前目录路径就是完整匹配，记录后返回。
    if not parts:
        limits["total"] += 1
        if len(results) < GLOB_MAX_RESULTS:
            results.append(root)
        if limits["total"] >= GLOB_MAX_SCAN:
            limits["stop"] = True
        return

    # 列出当前目录所有条目（文件+子目录）。
    # list() 包一下是因为 scandir 返回迭代器，而 ** 分支需要多次遍历（先零层再一层），
    # 迭代器只能走一遍，必须先固化成 list。
    try:
        entries = list(os.scandir(root))
    except OSError:
        # 权限不足或目录被删的目录静默跳过：搜索工具遇到不可读目录应继续搜别处，
        # 而不是中断整个搜索。
        return

    # head 是当前 parts 第一层需要匹配的字段，tail 是剩余的 parts
    # example: parts: ["a", "b", "c"]	  head: "a"	    tails: ["b", "c"]
    head, *tail = parts

    # ** 的语义是"跨任意层"：同时尝试匹配零层（跳过 **）和一层或多层（递归子目录）。
    if head == "**":
        # 匹配零层：** 视为不存在，直接用剩余模式匹配当前目录。
        # tail 为空时此处会记录 root 自身（目录本身）；一层循环对目录只递归不记录，
        # 因此每个目录恰好被记录一次，无重复。
        _glob_walk(root, tail, results, limits)
        if limits["stop"]:
            return

        # 匹配一层或多层：子目录继续完整模式递归；文件仅在模式到此结束时直接记录
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in EXCLUDE_DIRS:
                    _glob_walk(entry.path, parts, results, limits)
            elif not tail:
                # ** 直接匹配到文件本身（模式到 ** 就结束了）
                if entry.name in EXCLUDE_FILES:
                    continue
                limits["total"] += 1
                if len(results) < GLOB_MAX_RESULTS:
                    results.append(entry.path)
                if limits["total"] >= GLOB_MAX_SCAN:
                    limits["stop"] = True

            if limits["stop"]:
                break
    else:
        # 普通分段：fnmatch 匹配当前层条目名
        for entry in entries:
            if not fnmatch.fnmatch(entry.name, head):
                continue

            # 还有剩余段：匹配到的必须是目录（且不在排除列表）才能继续递归
            if tail:
                if entry.is_dir(follow_symlinks=False) and entry.name not in EXCLUDE_DIRS:
                    _glob_walk(entry.path, tail, results, limits)
            else:
                # 模式到此结束：排除文件与排除目录，其余记录为匹配结果
                if entry.name in EXCLUDE_FILES:
                    continue
                if entry.is_dir(follow_symlinks=False) and entry.name in EXCLUDE_DIRS:
                    continue

                limits["total"] += 1
                if len(results) < GLOB_MAX_RESULTS:
                    results.append(entry.path)
                if limits["total"] >= GLOB_MAX_SCAN:
                    limits["stop"] = True

            if limits["stop"]:
                break


def glob_tool(
    pattern: str,
    dir_path: str = ".",
    allow_external_reads: bool = False,
) -> str:
    """按 glob 模式匹配查找文件，返回匹配的文件路径列表。

    模式必须为相对路径，支持 fnmatch 通配（*、?、[seq]）与 ** 递归匹配子目录；
    扫描时自动剪枝排除目录与排除文件（EXCLUDE_DIRS / EXCLUDE_FILES），
    结果数量与扫描总量分别受 GLOB_MAX_RESULTS / GLOB_MAX_SCAN 硬上限保护。

    Args:
        pattern:                glob 模式（如 **/*.py、src/*.py），** 表示跨任意层目录。
        dir_path:               搜索目录（默认 '.'，即工作区根，可指定工作区内子目录）。
        allow_external_reads:   是否允许搜索工作区以外的目录。

    Returns:
        JSON 字符串。status 为 "ok" 时：pattern、count（总匹配数）、
        files（匹配的文件路径列表）、truncated（是否因达到上限被截断），
        message 汇总匹配数量；status 为 "error" 时：仅 message。

    Notes:
        - ** 通常与其他段配合（如 **/*.py）；裸 ** 匹配全部文件与目录
        - 排除目录（.git、.venv、node_modules 等）既不返回也不进入，
          若需搜索其内部，将 dir_path 直接指向该目录即可
        - files 最多返回 GLOB_MAX_RESULTS 个，总匹配数超过时 truncated=True
    """
    # 如果要匹配的模式为空，则返回错误，参数错误
    if not pattern or not pattern.strip():
        return json.dumps({
            "status": "error",
            "message": "pattern must not be empty."
        }, ensure_ascii=False)

    # 拒绝绝对路径模式
    if os.path.isabs(pattern):
        return json.dumps({
            "status": "error",
            "message": "pattern must be relative, absolute paths are not allowed."
        }, ensure_ascii=False)

    # 拒绝路径穿越组件
    if ".." in pattern.split(os.sep):
        return json.dumps({
            "status": "error",
            "message": "pattern must not contain '..' components."
        }, ensure_ascii=False)

    # 如果目录路径为空，则返回错误，参数错误
    if not dir_path or not dir_path.strip():
        return json.dumps({
            "status": "error",
            "message": "dir_path must not be empty."
        }, ensure_ascii=False)

    # 获取工作区目录，确保其存在并为绝对路径，注意！这是个极其严重的问题，工作区必须设置，如果未设置则必须立即报错！
    workspace = settings.workspace_dir
    if not workspace:
        raise RuntimeError("WORKSPACE_DIR is not configured, please set it up.")
    workspace = os.path.abspath(workspace)

    # 在 abspath 基础上，递归解析所有符号链接，返回磁盘上的真实路径
    try:
        safe_root = os.path.realpath(workspace)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot resolve workspace: {exc}"
        }, ensure_ascii=False)

    # 展开用户主目录
    dir_path = os.path.expanduser(dir_path)

    # 拼接 workspace + dir_path 找到搜索目录 `search_dir`
    try:
        if not os.path.isabs(dir_path):
            search_dir = os.path.realpath(os.path.join(safe_root, dir_path))
        else:
            search_dir = os.path.realpath(dir_path)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Invalid path: {exc}"
        }, ensure_ascii=False)

    # 路径边界归一化：工作区根统一为恰好一个结尾分隔符，防止前缀匹配陷阱
    safe_root = safe_root.rstrip(os.sep) + os.sep

    # 如果在没有 allow_external_reads 的时候，搜索目录不在工作区范围内，则返回错误，访问被拒绝
    if not allow_external_reads and not (search_dir + os.sep).startswith(safe_root):
        return json.dumps({
            "status": "error",
            "message": f"Access to '{dir_path}' is denied."
        }, ensure_ascii=False)

    # 如果搜索目录不存在，则返回错误，目录不存在
    if not os.path.isdir(search_dir):
        return json.dumps({
            "status": "error",
            "message": f"'{search_dir}' is not a directory."
        }, ensure_ascii=False)

    # 为 glob 递归匹配引擎 准备 匹配模式段
    # example: **/*.py -> ['**', '*.py'], orchestration/tools/*.py -> ["orchestration", "tools", "*.py"]
    parts = [p for p in pattern.split("/") if p]

    # 匹配模式段 空检测
    if not parts:
        return json.dumps({
            "status": "error",
            "message": "pattern must not be empty."
        }, ensure_ascii=False)

    # 这里为什么要用 list 和 Dict 呢？
    #     因为 _glob_walk 是递归的，递归的每一层都想要修改同一个结果列表和同一个计数器。
    #        - int、str 是不可变的——传给函数的是副本，改了自己那层，别的层看不见
    #        - list、dict 是可变的——传的是同一个对象的引用，任何一层往里 append，所有层都能看到
    #     所以：
    #        - file_matches（list）：所有层往这里追加匹配结果
    #        - limits（dict）：所有层共享扫描计数和"是否熔断"标志
    #     这个 limits 是跨递归共享的可变状态，这就是为什么用 dict 而不是直接传两个 int——传 int 的话，
    #     子层改了 total，父层完全不知道。
    file_matches: list[str] = []               # 匹配的文件路径列表
    limits = {"total": 0, "stop": False}       # 匹配结果数量限制

    try:
        _glob_walk(search_dir, parts, file_matches, limits)
    except RecursionError:
        # python 递归默认深度大约 1k 层，如果超限，返回给 LLM。应该不会有人去套 这么多文件夹吧。。。
        return json.dumps({
            "status": "error",
            "message": "Scan failed: directory tree is too deep."
        }, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Scan failed: {exc}"
        }, ensure_ascii=False)

    # 统计匹配结果数量，包含被截断的数量，以及是否被截断的标志，最后返回 JSON 字符串
    total = min(limits["total"], GLOB_MAX_SCAN)
    file_matches.sort()
    truncated = total >= GLOB_MAX_SCAN or len(file_matches) >= GLOB_MAX_RESULTS
    return json.dumps({
        "status": "ok",
        "message": f"Found {total} files matching '{pattern}'" + (" (truncated)" if truncated else ""),
        "pattern": pattern,
        "count": total,
        "files": file_matches,
        "truncated": truncated,
    }, ensure_ascii=False)


def grep_tool(
    pattern: str,
    path: str = ".",
    glob_pattern: str | None = None,
    output_mode: str = "files_with_matches",
    context_lines: int = 2,
    head_limit: int = 200,
    offset: int = 0,
    case_sensitive: bool = True,
    multiline: bool = False,
    encoding: str = "utf-8",
    allow_external_reads: bool = False,
) -> str:
    """用正则表达式搜索文件内容。

    Args:
        pattern:                要搜索的正则表达式。
        path:                   要搜索的文件或目录（默认 '.'，即工作区根）。
        glob_pattern:           搜索前按文件名过滤（glob 模式）。
        output_mode:            输出模式，取值 ``files_with_matches``、``content`` 或 ``count``。
        context_lines:          每个匹配前后附带的上下文行数（0-10）。
        head_limit:             最大结果数（0-1000，0 表示不限）。
        offset:                 跳过前 N 个结果。
        case_sensitive:         是否区分大小写（默认 True）。
        multiline:              是否让 ``.`` 匹配换行符（默认 False）。
        encoding:               文件编码（默认 utf-8）。
        allow_external_reads:   是否允许搜索工作区以外的目录。

    Returns:
        包含匹配、计数与分页信息的 JSON。
        files（files_with_matches）与 results 的键（count/content）均为绝对路径，
        与 view_file / glob_tool 保持一致。

    Notes:
        - 整次搜索受总时长预算限制（GREP_TOTAL_TIMEOUT_SECONDS），超时后返回已收集的
          部分结果，search_timed_out 为 True 表示结果不完整
        - 单行正则超时（REGEX_MATCH_TIMEOUT_SECONDS）会熔断该文件，计入 timed_out_files
    """
    # required 参数检查：如果要匹配的模式为空，则返回错误，参数错误
    if not pattern or not pattern.strip():
        return json.dumps({
            "status": "error",
            "message": "pattern must not be empty."
        }, ensure_ascii=False)

    # required 参数检查：如果要搜索的路径为空，则返回错误，参数错误
    if not path or not path.strip():
        return json.dumps({
            "status": "error",
            "message": "path must not be empty."
        }, ensure_ascii=False)

    # optional 参数检查：glob 模式 必须要为空或非空字符串
    if isinstance(glob_pattern, str) and not glob_pattern.strip():
        return json.dumps({
            "status": "error",
            "message": "glob_pattern must not be empty."
        }, ensure_ascii=False)

    # 注意：grep_tool 函数中的 glob_pattern 只是用来减少匹配范围的，不支持复杂的功能 例如 ** 这种
    # '**' 在 fnmatch（匹配 basename）中与 '*' 等价，没有任何递归语义，直接拒绝避免误导
    if isinstance(glob_pattern, str) and "**" in glob_pattern.split("/"):
        return json.dumps({
            "status": "error",
            "message": (
                "glob_pattern does not support '**' (it matches file names only, "
                "'**' is equivalent to '*'). For recursive searches use glob_tool."
            )
        }, ensure_ascii=False)

    # glob_pattern 只匹配文件名（basename），拒绝绝对路径与路径穿越组件：
    # 带 '/' 的模式对 basename 永远匹配不到任何文件，提前报错避免空结果困惑
    if isinstance(glob_pattern, str):
        if os.path.isabs(glob_pattern):
            return json.dumps({
                "status": "error",
                "message": (
                    "glob_pattern must be relative (matches file names only), "
                    "absolute paths are not allowed."
                )
            }, ensure_ascii=False)
        if ".." in glob_pattern.split(os.sep):
            return json.dumps({
                "status": "error",
                "message": (
                    "glob_pattern must not contain '..' components "
                    "(matches file names only)."
                )
            }, ensure_ascii=False)
        # 兜底：普通相对路径模式（如 "src/*.py"）同样永远匹配不到 basename，
        # 提示用 path 参数限定目录，而不是在 glob_pattern 里写路径
        if "/" in glob_pattern:
            return json.dumps({
                "status": "error",
                "message": (
                    "glob_pattern matches file names only; path separators are not allowed. "
                    "To scope the search to a subdirectory, use the path parameter."
                )
            }, ensure_ascii=False)

    # optional 参数检查：输出模式 必须要在这三个范围之内
    if output_mode not in ("files_with_matches", "content", "count"):
        return json.dumps({
            "status": "error",
            "message": f"Unknown output_mode: '{output_mode}'. Available: files_with_matches | content | count"
        }, ensure_ascii=False)
        
    # optional 参数检查：上下文行数 必须是 0-10 的整数
    # 注意：bool 是 int 的子类，True < 10 成立，必须显式排除
    if (not isinstance(context_lines, int) or isinstance(context_lines, bool)
            or context_lines < 0 or context_lines > 10):
        return json.dumps({
            "status": "error",
            "message": "context_lines must be an integer between 0 and 10."
        }, ensure_ascii=False)
        
    # optional 参数检查：结果限制 必须是 0-1000 的整数（0 表示不限，bool 需排除）
    if (not isinstance(head_limit, int) or isinstance(head_limit, bool)
            or head_limit < 0 or head_limit > 1000):
        return json.dumps({
            "status": "error",
            "message": "head_limit must be an integer between 0 and 1000."
        }, ensure_ascii=False)
        
    # optional 参数检查：跳过偏移量 必须是非负整数（bool 需排除）
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return json.dumps({
            "status": "error",
            "message": "offset must be a non-negative integer."
        }, ensure_ascii=False)

    # 正则合法性校验：提前编译一次供主体逻辑复用（多文件搜索无需每文件重编）。
    # 注意 multiline 的语义是“让 . 匹配换行符”，对应 re.DOTALL 而非 re.MULTILINE；
    # case_sensitive=False 时忽略大小写。
    try:
        flags = 0
        if not case_sensitive:
            flags |= re.IGNORECASE
        if multiline:
            flags |= re.DOTALL
        re_compiled = re.compile(pattern, flags)
    except re.error as exc:
        return json.dumps({
            "status": "error",
            "message": f"Invalid regex pattern: {exc}"
        }, ensure_ascii=False)

    # 获取工作区目录，确保其存在并为绝对路径，注意！这是个极其严重的问题，工作区必须设置，如果未设置则必须立即报错！
    workspace = settings.workspace_dir
    if not workspace:
        raise RuntimeError("WORKSPACE_DIR is not configured, please set it up.")
    workspace = os.path.abspath(workspace)

    # 在 abspath 基础上，递归解析所有符号链接，返回磁盘上的真实路径
    try:
        safe_root = os.path.realpath(workspace)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot resolve workspace: {exc}"
        }, ensure_ascii=False)

    # 展开用户主目录
    path = os.path.expanduser(path)

    # 拼接 workspace + path 找到搜索路径 `real_path`
    try:
        if not os.path.isabs(path):
            real_path = os.path.realpath(os.path.join(safe_root, path))
        else:
            real_path = os.path.realpath(path)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Invalid path: {exc}"
        }, ensure_ascii=False)

    # 路径边界归一化，把工作区根统一成 恰好一个结尾分隔符 的格式，防止前缀匹配陷阱. 
    safe_root = safe_root.rstrip(os.sep) + os.sep

    # 路径越界检查，确保 file_path 在工作区目录下
    if not allow_external_reads and not (real_path + os.sep).startswith(safe_root):
        return json.dumps({
            "status": "error",
            "message": f"Access to '{path}' is denied."
        }, ensure_ascii=False)

    # 路径存在性检查：path 可以是文件或目录，只查存在，类型分叉由主体逻辑处理
    if not os.path.exists(real_path):
        return json.dumps({
            "status": "error",
            "message": f"'{real_path}' does not exist."
        }, ensure_ascii=False)

    # 文件收集阶段
    # 在做真正的 正则匹配 之前，先把 “要收集哪些文件” 的清单列出来
    # 用户传 path
    # ├─ path 是单个文件 ──→ files = [该文件]（跳过遍历）
    # └─ path 是目录 ──────→ os.walk 全树遍历 + 多层过滤 → files 列表
    #                             ↓
    #                     然后逐个文件读内容、跑正则（本段之后的代码）
    # 为什么要分两个阶段？
    #    - 因为过滤（排除目录、文件名、上限）必须在"读文件内容"之前完成——否则会读一堆根本不搜的文件，浪费大量 IO。
    files = []                              # 用于收集文件
    files_truncated = False                 # 用于判断是否文件收集的数量超过 GREP_MAX_FILES 最大结果数

    # 总时长预算：整次调用（收集 + 搜索）的 wall-clock 硬上限，用单调时钟（不受系统时间调整影响）；
    # 超时后返回已收集的部分结果并标记 search_timed_out，而不是报错
    _deadline = time.monotonic() + GREP_TOTAL_TIMEOUT_SECONDS
    search_timed_out = False

    if os.path.isfile(real_path):
        files.append(real_path)
    else:
        try:
            # 遍历 real_path 目录，获取所有文件和子目录
            for dirpath, dirnames, filenames in os.walk(real_path):
                # 总时长预算检查：大目录树遍历也会吃预算，超时立即停止收集
                if time.monotonic() > _deadline:
                    search_timed_out = True
                    break
                # 过滤掉排除的目录
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

                # 对于每个文件名来说
                for fname in filenames:
                    # 过滤掉排除的文件名
                    if fname in EXCLUDE_FILES:
                        continue
                    # 如果文件数量达到最大限制，则截断并跳出循环
                    if len(files) >= GREP_MAX_FILES:
                        files_truncated = True
                        break
                    
                    # 构建完整路径
                    full_path = os.path.join(dirpath, fname)
                    # 如果有 glob 模式，则按文件名（basename）过滤
                    # 注意不能用 rel（含路径段）匹配：fnmatch 的 '*' 跨 '/'，且无通配符的
                    # 精确模式（如 "b.py"）会被路径段破坏，导致子目录同名文件被静默滤掉
                    if glob_pattern and not fnmatch.fnmatch(os.path.basename(full_path), glob_pattern):
                        continue
                    # 添加 当前文件的 full_path 到 files[] 列表中
                    files.append(full_path)
                    
                # 如果文件收集数量达到最大限制，则跳出循环
                if files_truncated:
                    break
        # 捕获目录遍历错误
        except OSError as exc:
            if not files:
                return json.dumps({
                    "status": "error",
                    "message": f"Cannot traverse directory: {exc}"
                }, ensure_ascii=False)

    # 搜索执行阶段
    # 拿着上一段收集好的 files 清单，逐个文件读取、跑正则、收集匹配
    skipped_large_files: list[str] = []             # 超过 GREP_MAX_FILE_SIZE 被跳过的文件（响应里报告）
    timed_out_files: list[str] = []                 # 正则超时被中断的文件（响应里报告）
    file_matches: list[dict] = []                   # 匹配结果：每条 {file, line_num, line_text}
    _content_cache: dict[str, str] = {}             # 内容缓存：{文件路径: 文件内容}

    # 对于 files 列表中 每一个文件来说
    for file_path in files:
        # 搜索超时熔断：预算耗尽后立即停止处理剩余文件
        if search_timed_out:
            break
        try:
            # 之前检查过了为什么还要查？
            # 1. TOCTOU 竞态：文件列表是遍历时收集的，但读取发生在遍历之后。中间如果文件被替换成指向外部的符号链接，
            #                   收集时的沙箱检查就失效了——"检查时安全，使用时危险"。读取前再查一次，把竞态窗口关死。
            # 2. 单文件分支漏检：上一段代码 os.path.isfile(real_path) 时直接 files.append，
            #                   没经过沙箱检查——收集阶段只查了 isfile。所以这里的复查也兜住了单文件路径。
            # 沙箱检查：确保文件在工作区目录下，并且工作区根目录不能为空，切勿越界
            if not allow_external_reads and not os.path.realpath(file_path).startswith(safe_root):
                continue

            # 跳过大于 GREP_MAX_FILE_SIZE 的文件
            if os.path.getsize(file_path) > GREP_MAX_FILE_SIZE:
                skipped_large_files.append(file_path)
                continue
            
            # 二进制嗅探：与 view_file 同一策略，检测头部 NUL 字节；
            # UTF-16/UTF-32 文本编码天然含 NUL，白名单放行。
            # grep 是批量扫描，二进制命中视为“读不了”，静默跳过（与解码失败同一语义）
            with open(file_path, "rb") as f:
                head = f.read(BINARY_SNIFF_BYTES)
            if b"\x00" in head and not encoding.lower().startswith(("utf-16", "utf-32")):
                continue

            # 读取文件内容
            with open(file_path, "r", encoding=encoding) as f:
                file_content = f.read()

        # 这里 静默跳过，如果遇到无法解码的文件
        except UnicodeDecodeError:
            continue
        # 这里 静默跳过，如果遇到无法读取的文件
        except OSError:
            continue
        # 意外异常兜底：regex 库可能抛非 TimeoutError 的异常（如嵌套过深的模式），
        # 单文件失败静默跳过，不裸炸整个搜索（与解码失败同一策略）
        except Exception:
            continue

        # 记下 处理这个文件前 的匹配总数
        _matches_before = len(file_matches)

        # 匹配多行的模式下，记录下所有匹配 在 file_matches 列表中
        if multiline:
            try:
                for _match_i, m in enumerate(re_compiled.finditer(
                        file_content, timeout=REGEX_MATCH_TIMEOUT_SECONDS), 1):
                    # 总时长预算：每 1024 个匹配查一次墙钟，超时熔断整个搜索（防止海量匹配累计耗时失控）
                    if _match_i % 1024 == 0 and time.monotonic() > _deadline:
                        search_timed_out = True
                        break
                    line_num = file_content[:m.start()].count("\n") + 1
                    # 取匹配起点所在行的完整文本：匹配可能从行中开始（如 'bar.*foo' 命中行中间），
                    # group(0) 的首行会丢掉行前缀，必须回源按行边界截取
                    line_start = file_content.rfind("\n", 0, m.start()) + 1
                    line_end = file_content.find("\n", m.start())
                    if line_end == -1:
                        line_end = len(file_content)
                    line_text = file_content[line_start:line_end]
                    file_matches.append({
                        "file": file_path,
                        "line_num": line_num,
                        "line_text": line_text.rstrip()
                    })
            #  正则超时熔断， 防止 灾难性回溯，
            # 就是 (a+)+$ 匹配 "aaaaaaaaaaaaaaaaaaaaaaaab" 这种输入时，回溯次数随输入长度指数爆炸，能让进程卡死几十分钟
            except TimeoutError:
                timed_out_files.append(file_path)
        else:
            lines = file_content.split("\n")

            # 遍历每一行，记录匹配结果
            for line_num, line_text in enumerate(lines, start=1):
                # 总时长预算：每 1024 行查一次墙钟（monotonic 单次 ~100ns，开销可忽略），
                # 超时熔断整个搜索——单行 2s 超时只防灾难性回溯，防不了海量正常行的累计耗时
                if line_num % 1024 == 0 and time.monotonic() > _deadline:
                    search_timed_out = True
                    break
                try:
                    if re_compiled.search(line_text, timeout=REGEX_MATCH_TIMEOUT_SECONDS):
                        file_matches.append({
                            "file": file_path,
                            "line_num": line_num,
                            "line_text": line_text.rstrip()
                        })
                # 防止 灾难性回溯
                except TimeoutError:
                    timed_out_files.append(file_path)
                    break
                        
        # 搜索超时：整次调用时间预算耗尽，停止处理剩余文件（返回已收集的部分结果）
        if search_timed_out:
            break

        # 只有 content 模式才消费内容缓存（其他模式只用 file/line_num/line_text），避免白存
        if output_mode == "content" and len(file_matches) > _matches_before:
            _content_cache[file_path] = file_content

    # 匹配总数（不是文件数）
    # 一个文件可能贡献多条匹配。它是后续所有逻辑的基准：
    # 分页（offset >= total_matches 判断）、截断计算（truncated = offset + len(page) < total_matches）、三种 output_mode 的输出。
    total_matches = len(file_matches)
    
    # 如果没有匹配结果，则返回空结果放在 返回体中
    if total_matches == 0:
        # 构建空结果消息 并最后返回
        msg = f"No matches for '{pattern}' in {len(files)} files"
        if files_truncated:
            msg += f" (file list truncated at {GREP_MAX_FILES})"
        if skipped_large_files:
            msg += f", {len(skipped_large_files)} large files skipped (>{GREP_MAX_FILE_SIZE // 1024 // 1024} MB)"
        if timed_out_files:
            msg += f", {len(timed_out_files)} files timed out"
        if search_timed_out:
            msg += ", search timed out, results may be incomplete"
        return json.dumps({
            "status": "ok",
            "output_mode": output_mode,
            "message": msg,
            "total_matches": 0,
            "total_files": 0,
            "files_scanned": len(files),
            "files_truncated": files_truncated,
            "skipped_large_files": len(skipped_large_files),
            "timed_out_files": len(timed_out_files),
            "search_timed_out": search_timed_out,
        }, ensure_ascii=False)

    # 如果分页参数超出范围，则返回错误
    if offset >= total_matches:
        return json.dumps({
            "status": "error",
            "message": f"offset {offset} exceeds total matches {total_matches}"
        }, ensure_ascii=False)
    
    # 结果渲染阶段
    # 搜索执行完（拿到 total_matches），现在把 file_matches 转成三种不同的视图返回给 LLM。
    page_matches = file_matches[offset:offset + head_limit] if head_limit > 0 else file_matches[offset:]
    truncated = (offset + len(page_matches)) < total_matches
    _page_file_set = {m["file"] for m in page_matches}
    _content_cache = {k: v for k, v in _content_cache.items() if k in _page_file_set}

    # output mode A: 只返回匹配的文件名
    if output_mode == "files_with_matches":
        # 去重保序
        visited_files_set: set[str] = set()
        unique_files_list: list[str] = []
        
        # 同一文件的多条匹配只保留第一次出现的位置
        for m in page_matches:
            if m["file"] not in visited_files_set:
                visited_files_set.add(m["file"])
                unique_files_list.append(m["file"])
                
        return json.dumps({
            "status": "ok",
            "output_mode": "files_with_matches",
            "files": unique_files_list,
            "total_files": len(unique_files_list),
            "total_matches": total_matches,
            "truncated": truncated,
            "files_scanned": len(files),
            "files_truncated": files_truncated,
            "skipped_large_files": len(skipped_large_files),
            "timed_out_files": len(timed_out_files),
            "search_timed_out": search_timed_out,
            "page": {"offset": offset, "limit": head_limit},
        }, ensure_ascii=False)

    # output mode B: 返回匹配的内容出现的文件名和次数
    if output_mode == "count":
        file_counts: dict[str, int] = {}
    
        for m in page_matches:
            fp = m["file"]
            file_counts[fp] = file_counts.get(fp, 0) + 1
            
        return json.dumps({
            "status": "ok",
            "output_mode": "count",
            "results": file_counts,
            "total_occurrences": sum(file_counts.values()),
            "total_files": len(file_counts),
            "total_matches": total_matches,
            "truncated": truncated,
            "files_scanned": len(files),
            "files_truncated": files_truncated,
            "skipped_large_files": len(skipped_large_files),
            "timed_out_files": len(timed_out_files),
            "search_timed_out": search_timed_out,
            "page": {"offset": offset, "limit": head_limit},
        }, ensure_ascii=False)

    # output mode C: 返回匹配的文件内容，以及匹配行前后的上下文
    if output_mode == "content":
        # 行缓存：同一文件可能有多条匹配，上下文渲染会反复取行，只读一次磁盘。
        # 取行优先级：先命中搜索阶段的 _content_cache（完整内容已在内存），miss 才回源读盘。
        _file_lines_cache: dict[str, list[str]] = {}

        def _get_lines(fp: str) -> list[str]:
            """按文件路径取行列表，带缓存；读取失败静默返回空列表。

            取行优先级：先查 _content_cache（搜索阶段已整读的文件），miss 时回源读盘；
            UnicodeDecodeError / OSError 视为“读不到”，返回空列表让调用方跳过该文件
            （与搜索阶段的静默跳过策略一致）。

            Args:
                fp: 文件的绝对路径。

            Returns:
                该文件按 "\n" 拆分的行列表；读取失败时为空列表。
            """
            if fp not in _file_lines_cache:
                if fp in _content_cache:
                    _file_lines_cache[fp] = _content_cache[fp].split("\n")
                else:
                    try:
                        with open(fp, "r", encoding=encoding) as f:
                            _file_lines_cache[fp] = f.readlines()
                    except (UnicodeDecodeError, OSError):
                        _file_lines_cache[fp] = []

            return _file_lines_cache[fp]

        # 按文件分组：同一文件的所有匹配聚在一起，保证每个文件只渲染一次上下文
        file_groups: dict[str, list[dict]] = {}

        for m in page_matches:
            fp = m["file"]
            file_groups.setdefault(fp, []).append(m)

        results: dict[str, list[list[dict]]] = {}

        # 逐文件渲染：把每条匹配展开成一个“上下文块”（匹配行 + 前后 context_lines 行）
        for fp, matches in file_groups.items():
            file_lines = _get_lines(fp)

            # 行列表为空说明文件读不到（或被判定为不可解码），跳过不渲染
            if not file_lines:
                continue

            chunks: list[list[dict]] = []

            for m in matches:
                # 匹配行号转 0-based 索引，按 context_lines 向两侧扩展，clamp 到文件边界
                line_idx = m["line_num"] - 1
                start = max(0, line_idx - context_lines)
                end = min(len(file_lines), line_idx + context_lines + 1)
                chunk: list[dict] = []

                # 逐行输出：match 标记哪一行是真正的命中行（供 LLM 定位）
                for i in range(start, end):
                    chunk.append({
                        "line_num": i + 1,
                        "content": file_lines[i].rstrip("\n"),
                        "match": (i + 1 == m["line_num"]),
                    })

                chunks.append(chunk)

            # 最终结构：{绝对路径: [上下文块, ...]}，一个块对应一条匹配
            results[fp] = chunks

        return json.dumps({
            "status": "ok",
            "output_mode": "content",
            "results": results,
            "total_matches": total_matches,
            "truncated": truncated,
            "files_scanned": len(files),
            "files_truncated": files_truncated,
            "skipped_large_files": len(skipped_large_files),
            "timed_out_files": len(timed_out_files),
            "search_timed_out": search_timed_out,
            "page": {"offset": offset, "limit": head_limit},
        }, ensure_ascii=False)

    # 这个分支不应该被执行，因为前面已经处理了所有可能的 output_mode
    return json.dumps({
        "status": "error",
        "message": f"Invalid output_mode: {output_mode}"
    }, ensure_ascii=False)
