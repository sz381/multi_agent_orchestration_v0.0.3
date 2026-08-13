"""工作区写入文件系统工具实现

提供函数：
- str_replace:      原子替换文件中的精确文本（CAS 语义，old_str 须唯一或 replace_all）
- write_file:       原子创建或覆盖文件（自动建父目录，新文件权限随 umask）
- clean_dir:        安全地删除工作区内的文件或目录, 注意是 工作区 only

关键约束：
- 所有工具统一返回 JSON 字符串（status: ok/error），不抛异常
  （唯一例外：workspace 未配置时抛 RuntimeError，属配置错误而非业务错误）
- 路径严格限制在工作区内（无越界开关）：realpath 归一化 + 边界前缀检查，
  与 _fs_readonly 共享同一安全链；clean_dir 另有工作区根保护
- 写入原子性：mkstemp 同目录临时文件 + 权限恢复 + os.replace（inode 替换），
  finally 兜底清理临时文件，任何失败不留下半写文件
- 并发互斥：按 realpath 路径缓存的 asyncio.Lock（WeakValueDictionary）三工具共享，
  clean_dir 删除前逐项获取同一文件锁，与写入/替换互斥（防“删了又复活”）；
  目录删除先原子改名隔离再递归删除（防删除期间新写入被误删）
- 资源硬上限：MAX_WRITE_SIZE（content 1MB 字节语义）、MAX_DIFF_SIZE（diff 50 字符截断）、
  CLEAN_MAX_ITEMS（单次删除 500 项，先预检后动手）
- 编码防护：无效编码（LookupError/TypeError）与不可编码字符（UnicodeEncodeError）
  均在写盘前拦截，不产生半写文件
- 幂等语义：write_file 内容与原文一致时返回 [UNCHANGED] 不落盘；
  原文件 ≤1MB 才全读比较，更大跳过读取直接覆盖（字节数必不同）；
  原内容不可知时 diff.old 为空（读失败/stat 失败/超限），不阻塞写入
- 删除不可回滚：clean_dir 部分失败时 error 响应携带 deleted/count 报告已删进度

使用注意：
- str_replace 的 old_str 是精确匹配，多处出现时须 replace_all=True，否则报错
- write_file 的 content 必须是字符串（空串合法=写空文件），大小按字节计
- clean_dir 的 patterns 只匹配文件名/目录名（fnmatch basename 语义），
  不支持 ** 与路径分隔符；None/[] 时递归删除 dir_path 整体（文件则删文件）
- clean_dir 删除的是链接本身而非链接指向的目标
- 编码错误提示会回传异常信息，帮助定位问题
- 只读工具请使用 _fs_readonly
"""

import os
import json
import asyncio
import tempfile
import weakref
import fnmatch
import shutil
import uuid

from core.tools._kernel.constants import (
    MAX_WRITE_SIZE,
    MAX_DIFF_SIZE,
    CLEAN_MAX_ITEMS,
)
from utils.settings import settings


# 弱引用字典，用于存储每个文件的异步锁，防止锁对象因无引用而被垃圾回收。
_file_locks: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_clean_lock = asyncio.Lock()


def _get_file_lock(file_path: str) -> asyncio.Lock:
    """返回一个按文件异步锁，用于对同一路径的写入进行序列化。

    使用 WeakValueDictionary，当没有协程持有该锁的引用时，
    锁将被垃圾回收，防止在长时间运行会话中出现无限制的增长。

    Args:
        file_path: 文件绝对路径（已归一化），作为锁的标识键。

    Returns:
        该路径对应的 asyncio.Lock 实例。
    """
    lock = _file_locks.get(file_path)
    if lock is None:
        lock = asyncio.Lock()
        _file_locks[file_path] = lock
    return lock


def _str_replace_io(
    file_path: str,
    old_str: str,
    new_str: str,
    replace_all: bool,
    encoding: str,
) -> str:
    """锁内临界区同步段：字节预检 → 读取 → 匹配 → 原子替换，返回 JSON。

    由 str_replace 持有路径锁时经 asyncio.to_thread 调用，磁盘 I/O 与文本
    计算在线程池执行，事件循环不被阻塞。本函数不负责加锁，只假定调用方
    已保证同一路径互斥（临界区整体原子执行，mkstemp→write→chmod→replace
    序列不可拆分）。

    Args:
        file_path:   目标文件路径（已通过安全链校验的工作区内绝对路径）。
        old_str:     要替换的精确文本（必须连空白字符完全匹配）。
        new_str:     替换后的文本（空串合法，表示删除）。
        replace_all: 是否替换所有出现位置。
        encoding:    文件编码。

    Returns:
        JSON 字符串，包含 status、path 与 diff 摘要。
    """
    # 字节级大小预检：多字节编码下字符数恒 ≤ 字节数，字符级检查会被
    # 大文件（如 2MB 中文）绕过；getsize 是字节语义，与限制严格一致
    try:
        file_size = os.path.getsize(file_path)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot stat {file_path}: {exc}"
        }, ensure_ascii=False)

    # 文件大小检查，确保文件大小不超过限制
    if file_size > MAX_WRITE_SIZE:
        return json.dumps({
            "status": "error",
            "message": f"File '{file_path}' exceeds {MAX_WRITE_SIZE // 1024 // 1024}MB limit."
        }, ensure_ascii=False)

    # 大小已确认 ≤ 1MB 字节，完整读取不会内存超载
    try:
        with open(file_path, "r", encoding=encoding) as f:
            content = f.read()
    except UnicodeDecodeError:
        return json.dumps({
            "status": "error",
            "message": f"{file_path} cannot be decoded as {encoding}. Retry with encoding='gbk' or 'latin-1'."
        }, ensure_ascii=False)
    except PermissionError:
        return json.dumps({
            "status": "error",
            "message": f"Permission denied: '{file_path}'."
        }, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot read {file_path}: {exc}"
        }, ensure_ascii=False)
    # 意外异常兜底：不裸炸整个调用（与 _fs_readonly 同一策略）
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Unexpected error reading {file_path}: {exc}"
        }, ensure_ascii=False)

    # 文本匹配检查，确保 old_str 在文件中存在
    count = content.count(old_str)
    if count == 0:
        return json.dumps({
            "status": "error",
            "message": f"Text not found in {file_path}. Use view_file to verify file content."
        }, ensure_ascii=False)

    # 特殊情况检查，如果 old_str 和 new_str 相同，则无需进行任何操作
    # 响应契约与正常替换一致：携带 path 与同结构 diff（count 为实际出现次数）
    if old_str == new_str:
        return json.dumps({
            "status": "ok",
            "message": f"[UNCHANGED] No changes to '{file_path}' — old_str and new_str are identical.",
            "path": file_path,
            "diff": {
                "old": old_str[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(old_str) > MAX_DIFF_SIZE else old_str,
                "new": new_str[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(new_str) > MAX_DIFF_SIZE else new_str,
                "count": count,
                "replace_all": replace_all,
            },
        }, ensure_ascii=False)

    # 特殊情况检查，如果 old_str 出现多次且未设置 replace_all，则报错
    if count > 1 and not replace_all:
        return json.dumps({
            "status": "error",
            "message": f"Text matches {count} occurrences in {file_path}. Add more context to make it unique, or use replace_all=True."
        }, ensure_ascii=False)

    # 生成替换后的内容：replace_all 全量替换，否则只替换第一次出现
    if replace_all:
        new_content = content.replace(old_str, new_str)
    else:
        new_content = content.replace(old_str, new_str, 1)

    # 创建临时文件（与目标同目录，保证 os.replace 同文件系统原子性）
    # mkstemp / os.stat 均可能抛 OSError（目录只读、文件被并发删除等），必须纳入兜底
    tmp_path: str | None = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(file_path))
        # 保存原文件权限，以便恢复
        orig_mode = os.stat(file_path).st_mode
        # 写入临时文件
        with os.fdopen(tmp_fd, "w", encoding=encoding) as f:
            f.write(new_content)
        # 恢复原文件权限
        os.chmod(tmp_path, orig_mode)
        # 原子性地替换原文件
        os.replace(tmp_path, file_path)
    except UnicodeEncodeError:
        return json.dumps({
            "status": "error",
            "message": f"new_str contains characters not encodable as {encoding}. Try encoding='utf-8'."
        }, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot write to {file_path}: {exc}"
        }, ensure_ascii=False)
    # 意外异常兜底：写入阶段失败不裸炸（finally 仍会清理临时文件）
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Unexpected error writing {file_path}: {exc}"
        }, ensure_ascii=False)
    finally:
        # 删除临时文件（mkstemp 失败时 tmp_path 为 None，跳过）
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            # 删除文件失败，但已无其他异常，忽略并继续，不能因为这个导致整个替换失败
            except OSError:
                pass

    # 返回结果
    return json.dumps({
        "status": "ok",
        "message": f"[REPLACED{' ALL' if replace_all else ''}] {file_path}"
                   + (f" ({count} occurrences)" if replace_all and count > 0 else ""),
        "path": file_path,
        "diff": {
            "old": old_str[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(old_str) > MAX_DIFF_SIZE else old_str,
            "new": new_str[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(new_str) > MAX_DIFF_SIZE else new_str,
            "count": count if replace_all else 1,
            "replace_all": replace_all,
        },
    }, ensure_ascii=False)


async def str_replace(
    file_path: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
    encoding: str = "utf-8",
) -> str:
    """原子性地替换文件中的精确文本。

    要求 old_str 在文件中恰好匹配一次（或设置 replace_all=True）。

    Args:
        file_path:   目标文件路径（工作区相对路径或绝对路径）。
        old_str:     要替换的精确文本（必须连空白字符完全匹配）。
        new_str:     替换后的文本。
        replace_all: 是否替换所有出现位置（默认 False）。
        encoding:    文件编码（默认 utf-8）。

    Returns:
        JSON 字符串，包含 status、path 与 diff 摘要。

    执行模型：参数校验与路径安全检查在事件循环内完成（纯 CPU）；
    锁内临界区（磁盘 I/O 与文本处理）经 asyncio.to_thread 在线程池执行，
    事件循环不被阻塞；路径锁（asyncio.Lock）的获取与释放在事件循环内完成。
    """
    # 参数检查：file_path 必须是非空字符串
    # 非 str（如数字）会在 strip() 处 AttributeError 裸炸，LLM 传参不可信必须拦截
    if not isinstance(file_path, str) or not file_path.strip():
        return json.dumps({
            "status": "error",
            "message": "file_path must be a non-empty string."
        }, ensure_ascii=False)

    # 参数检查：old_str 必须是非空字符串
    # 注意只查空不 strip：替换空白/缩进是合法需求（与正则 pattern 语义不同）
    if not isinstance(old_str, str) or not old_str:
        return json.dumps({
            "status": "error",
            "message": "old_str must be a non-empty string."
        }, ensure_ascii=False)

    # 参数检查：new_str 必须是字符串（空串合法，表示删除；None/数字会在 replace() 处 TypeError 裸炸）
    if not isinstance(new_str, str):
        return json.dumps({
            "status": "error",
            "message": "new_str must be a string."
        }, ensure_ascii=False)

    # 参数检查：encoding 是否有效
    # 注意非字符串 encoding（None/数字）会抛 TypeError 而非 LookupError，必须一并拦截
    try:
        "".encode(encoding)
    except (LookupError, TypeError):
        return json.dumps({
            "status": "error",
            "message": f"Unknown encoding: '{encoding}'. Try 'utf-8', 'gbk', or 'latin-1'."
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

    # 解析用户主目录
    file_path = os.path.expanduser(file_path)

    # 解析文件路径，确保其为绝对路径
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

    # 路径边界归一化，把工作区根统一成 恰好一个结尾分隔符 的格式，防止前缀匹配陷阱。
    safe_root = safe_root.rstrip(os.sep) + os.sep
    
    # 路径越界检查，确保 file_path 在工作区目录下
    if not file_path.startswith(safe_root):
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

    # 在持有文件锁的情况下，将锁内临界区（字节预检/读取/匹配/原子替换）整体
    # 丢入线程池执行，事件循环不被磁盘 I/O 阻塞；锁的获取与释放在事件循环内完成
    async with _get_file_lock(file_path):
        return await asyncio.to_thread(
            _str_replace_io, file_path, old_str, new_str, replace_all, encoding
        )


def _write_file_io(
    file_path: str,
    content: str,
    encoding: str,
) -> str:
    """锁内临界区同步段：存在性检查 → 读取旧内容 → UNCHANGED 判断 → 原子写，返回 JSON。

    由 write_file 持有路径锁时经 asyncio.to_thread 调用，磁盘 I/O 在线程池
    执行，事件循环不被阻塞。本函数不负责加锁，只假定调用方已保证同一路径互斥。

    Args:
        file_path: 目标文件路径（已通过安全链校验的工作区内绝对路径）。
        content:   完整文件内容（最大 1MB）。
        encoding:  文件编码。

    Returns:
        JSON 字符串，包含 status、path 与 diff 摘要。
    """
    # 文件存在性检查，如果存在则读取原内容
    existed = os.path.exists(file_path)
    old_content = ""
    # 读原文件失败的标记：失败时不做 UNCHANGED 判断（old 为空 ≠ 原文件为空）
    read_failed = False

    # 如果文件存在则读取原内容（仅用于 diff 与 UNCHANGED 判断）
    if existed:
        # 存在性检查，确保 file_path 不是目录
        if os.path.isdir(file_path):
            return json.dumps({
                "status": "error",
                "message": f"'{file_path}' is a directory."
            }, ensure_ascii=False)

        # 字节级预检：原文件 ≤ 1MB 字节才读取（供 UNCHANGED 比较与 diff.old）；
        # 更大则跳过读取直接覆盖——content 编码后必 ≤ MAX_WRITE_SIZE，字节数
        # 必然不同，且省去大文件全读；read_failed 语义扩展为“原内容不可知”
        try:
            old_size = os.path.getsize(file_path)
        except OSError:
            # stat 失败：原内容不可知，保守走覆盖，且不误判 UNCHANGED
            old_size = None
        if old_size is None or old_size > MAX_WRITE_SIZE:
            read_failed = True
        else:
            # 读失败不阻塞写入：diff.old 是装饰性信息，覆盖不可解码/二进制文件是合法操作
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    old_content = f.read()
            except Exception:
                read_failed = True

    # 如果文件存在且内容未变，则返回未修改（响应契约与主分支一致：path + diff）
    if existed and not read_failed and old_content == content:
        return json.dumps({
            "status": "ok",
            "message": f"[UNCHANGED] {file_path} — content identical, no changes made.",
            "path": file_path,
            "diff": {
                "old": old_content[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(old_content) > MAX_DIFF_SIZE else old_content,
                "new": content[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(content) > MAX_DIFF_SIZE else content,
            },
        }, ensure_ascii=False)

    # 原子写：mkstemp 同目录（保证 os.replace 同文件系统原子性）
    # mkstemp / os.stat / os.umask 均可能抛 OSError，必须纳入兜底
    tmp_path: str | None = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(file_path))
        # 权限：覆盖保留原权限；新建按 0o666 & ~umask（mkstemp 固定 0600，
        # 不修正会导致新文件其他用户/进程不可读；umask 仅在锁内读取，竞态窗口可接受）
        if existed:
            orig_mode = os.stat(file_path).st_mode
        else:
            old_umask = os.umask(0)
            os.umask(old_umask)
            orig_mode = 0o666 & ~old_umask
        # 写入临时文件
        with os.fdopen(tmp_fd, "w", encoding=encoding) as f:
            f.write(content)
        # 恢复权限
        os.chmod(tmp_path, orig_mode)
        # 原子性地替换原文件
        os.replace(tmp_path, file_path)
    except UnicodeEncodeError:
        # 理论不可达（已提前预检编码），保留防御
        return json.dumps({
            "status": "error",
            "message": f"Content contains characters not encodable as {encoding}. Try encoding='utf-8'."
        }, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot write to {file_path}: {exc}"
        }, ensure_ascii=False)
    # 意外异常兜底：写入阶段失败不裸炸（finally 仍会清理临时文件）
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Unexpected error writing {file_path}: {exc}"
        }, ensure_ascii=False)
    finally:
        # 删除临时文件（mkstemp 失败时 tmp_path 为 None，跳过）
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # 计算行数，决定 action，返回响应
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    action = "OVERWRITTEN" if existed else "CREATED"
    return json.dumps({
        "status": "ok",
        "message": f"[{action}] {file_path} ({line_count} lines)",
        "path": file_path,
        "diff": {
            "old": old_content[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(old_content) > MAX_DIFF_SIZE else old_content,
            "new": content[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(content) > MAX_DIFF_SIZE else content,
        },
    }, ensure_ascii=False)


async def write_file(
    file_path: str,
    content: str,
    encoding: str = "utf-8",
) -> str:
    """原子性地创建或覆盖文件。

    按需自动创建父目录。

    Args:
        file_path: 目标文件路径（工作区相对路径或绝对路径）。
        content:   完整文件内容（最大 1MB）。
        encoding:  文件编码（默认 utf-8）。

    Returns:
        JSON 字符串，包含 status、path 与 diff 摘要。

    执行模型：参数校验、路径安全检查与父目录创建（to_thread）在事件循环内发起；
    锁内临界区（存在性检查/读取旧内容/UNCHANGED 判断/原子写）经 asyncio.to_thread
    在线程池执行，事件循环不被阻塞；路径锁（asyncio.Lock）的获取与释放在事件循环内完成。
    """
    # 参数检查：file_path 必须是非空字符串
    # 非 str（如数字）会在 strip() 处 AttributeError 裸炸，LLM 传参不可信必须拦截
    if not isinstance(file_path, str) or not file_path.strip():
        return json.dumps({
            "status": "error",
            "message": "file_path must be a non-empty string."
        }, ensure_ascii=False)

    # 参数检查：content 必须是字符串（空串合法，表示写空文件；None/0/False/[] 会静默写空文件或裸炸）
    if not isinstance(content, str):
        return json.dumps({
            "status": "error",
            "message": "content must be a string."
        }, ensure_ascii=False)

    # 参数检查：encoding 是否有效
    # 注意非字符串 encoding（None/数字）会抛 TypeError 而非 LookupError，必须一并拦截
    try:
        "".encode(encoding)
    except (LookupError, TypeError):
        return json.dumps({
            "status": "error",
            "message": f"Unknown encoding: '{encoding}'. Try 'utf-8', 'gbk', or 'latin-1'."
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
    file_path = os.path.expanduser(file_path)

    # 确保 file_path 是绝对路径，如果相对路径则解析为绝对路径
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

    # 路径边界归一化，把工作区根统一成 恰好一个结尾分隔符 的格式，防止前缀匹配陷阱。
    safe_root = safe_root.rstrip(os.sep) + os.sep

    # 路径越界检查，确保 file_path 在工作区目录下
    if not file_path.startswith(safe_root):
        return json.dumps({
            "status": "error",
            "message": f"Access to '{file_path}' is denied."
        }, ensure_ascii=False)

    # 内容大小检查，确保 content 小于 1MB
    try:
        content_size = len(content.encode(encoding))
    except UnicodeEncodeError:
        return json.dumps({
            "status": "error",
            "message": f"Content contains characters not encodable as {encoding}. Try encoding='utf-8'."
        }, ensure_ascii=False)

    # 内容大小检查，确保 content 小于 1MB
    if content_size > MAX_WRITE_SIZE:
        return json.dumps({
            "status": "error",
            "message": f"Content size exceeds {MAX_WRITE_SIZE // 1024 // 1024}MB limit."
        }, ensure_ascii=False)

    # 确保父目录存在，不存在则创建（安全链之后：realpath 已解析符号链接，不会借道越界）
    # makedirs 可能抛 OSError（中间路径是文件、权限拒绝），必须兜底；
    # file_path 是否为目录由锁内检查（existed 分支）承担，此处无需重复；
    # 目录创建属磁盘 I/O，丢线程池执行，事件循环不被阻塞
    parent = os.path.dirname(file_path)
    if parent:
        try:
            await asyncio.to_thread(os.makedirs, parent, exist_ok=True)
        except OSError as exc:
            return json.dumps({
                "status": "error",
                "message": f"Cannot create directory {parent}: {exc}"
            }, ensure_ascii=False)

    # 文件锁，确保文件操作的原子性（与 str_replace 共享同一路径锁）；
    # 锁内临界区（存在性检查/读取旧内容/UNCHANGED 判断/原子写）整体丢入线程池执行
    async with _get_file_lock(file_path):
        return await asyncio.to_thread(_write_file_io, file_path, content, encoding)


def _collect_delete_targets(
    target: str,
    patterns: list[str] | None,
) -> list[str]:
    """扫描收集待删除路径（同步段）。

    文件或空模式直接返回目标本身；否则 os.walk 按 basename glob 匹配
    （fnmatch 语义）收集文件与目录，匹配的目录整目录收录。

    Args:
        target:   已通过安全链校验的目标路径（工作区内绝对路径）。
        patterns: basename 匹配模式列表；None/[] 表示删除目标本身。

    Returns:
        待删除路径列表（绝对路径，未排序；由调用方排序后执行删除）。
    """
    to_delete: list[str] = []
    # 如果目标是文件或没有模式，则只删除目标本身
    if os.path.isfile(target) or not patterns:
        to_delete.append(target)
    else:
        # os.walk onerror 显式转 error：子目录不可读时静默跳过
        # 会导致“以为删了实际没删”，必须显式失败
        def _on_error(exc: OSError) -> None:
            raise exc

        # 遍历目录，收集匹配的文件和目录
        for dirpath, dirnames, filenames in os.walk(target, onerror=_on_error):
            for d in [d for d in dirnames if any(fnmatch.fnmatch(d, p) for p in patterns)]:
                to_delete.append(os.path.join(dirpath, d))
                dirnames.remove(d)
            # 收集匹配的文件
            for f in filenames:
                if any(fnmatch.fnmatch(f, p) for p in patterns):
                    to_delete.append(os.path.join(dirpath, f))
    return to_delete


def _delete_one(path: str) -> None:
    """单路径删除（同步段）。

    目录先原子改名隔离再递归删除（防删除期间新写入文件被 rmtree 误删的
    TOCTOU），失败时清理残留；文件或符号链接直接 unlink（删除链接本身）。

    Args:
        path: 待删除的绝对路径。

    Returns:
        无返回值；删除失败时抛 OSError，由调用方兜底返回 error 响应。
    """
    if os.path.isdir(path) and not os.path.islink(path):
        # 目录删除：先原子改名隔离再递归删除，消除“收集后新写入
        # 文件被 rmtree 误删”的 TOCTOU；失败时 finally 兜底清理残留
        tmp_dir = path + ".clean_tmp_" + uuid.uuid4().hex[:8]
        os.rename(path, tmp_dir)
        try:
            shutil.rmtree(tmp_dir)
        finally:
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        os.unlink(path)


async def clean_dir(
    dir_path: str,
    patterns: list[str] | None = None,
) -> str:
    """安全地删除工作区内的文件或目录（仅限工作区）。

    patterns 为 None 或空列表时递归删除 dir_path 整体；否则按 basename
    glob 匹配（fnmatch 语义）收集文件与目录，匹配的目录整目录删除。

    执行模型：参数校验、路径安全检查与待删列表收集（os.walk）经 asyncio.to_thread
    在线程池执行，事件循环不被阻塞；_clean_lock 与逐项路径锁（asyncio.Lock）的
    获取/释放在事件循环内完成，单路径删除动作（rename/rmtree/unlink）亦经 to_thread。

    Args:
        dir_path:  目标路径（工作区相对路径或绝对路径），可为文件或目录。
        patterns:  可选 basename 匹配模式列表；None/[] 表示删除 dir_path 整体。

    Returns:
        JSON 字符串，包含 status、message、deleted（相对工作区根的路径列表）
        与 count（删除数量）。部分失败时 error 响应同样携带 deleted/count
        报告已删进度——删除不可回滚，半删状态由调用方按需处理。
    """
    # 参数检查：dir_path 必须是非空字符串
    # 非 str（如数字）会在 strip() 处 AttributeError 裸炸，LLM 传参不可信必须拦截
    if not isinstance(dir_path, str) or not dir_path.strip():
        return json.dumps({
            "status": "error",
            "message": "dir_path must be a non-empty string."
        }, ensure_ascii=False)

    # 参数检查：patterns 必须是字符串列表或 None
    # 字符串会被按字符迭代而静默不匹配（LLM 以为删了），数字会裸炸，必须拦截
    if patterns is not None and (
        not isinstance(patterns, list) or any(not isinstance(p, str) for p in patterns)
    ):
        return json.dumps({
            "status": "error",
            "message": "patterns must be a list of strings or None."
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

    # 展开用户主目录，并保存词法归一化路径（不解析符号链接，供 symlink 特判）
    dir_path = os.path.expanduser(dir_path)
    raw_path = os.path.normpath(
        os.path.join(safe_root, dir_path) if not os.path.isabs(dir_path) else dir_path
    )

    # 符号链接特判：必须先于 realpath——链接指向工作区外时 realpath 会越界被拦，
    # 而链接本身在工作区内应当可删（删链接本身而非解析后的目标）
    if os.path.islink(raw_path):
        # 链接本身的词法边界检查（normpath 已折叠 ..，前缀检查即安全）
        safe_root_norm = safe_root.rstrip(os.sep)
        
        if raw_path == safe_root_norm:
            return json.dumps({
                "status": "error",
                "message": "Refusing to delete the workspace root."
            }, ensure_ascii=False)

        if not raw_path.startswith(safe_root_norm + os.sep):
            return json.dumps({
                "status": "error",
                "message": f"Access to '{dir_path}' is denied."
            }, ensure_ascii=False)

        to_delete = [raw_path]
    else:
        # 确保 dir_path 是绝对路径，如果相对路径则解析为绝对路径（递归解析符号链接）
        try:
            target = os.path.realpath(raw_path)
        except OSError as exc:
            return json.dumps({
                "status": "error",
                "message": f"Invalid path: {exc}"
            }, ensure_ascii=False)

        # 路径边界归一化，把工作区根统一成 恰好一个结尾分隔符 的格式，防止前缀匹配陷阱。
        safe_root = safe_root.rstrip(os.sep) + os.sep

        # 确保 dir_path 不是工作区根
        if target == safe_root.rstrip(os.sep):
            return json.dumps({
                "status": "error",
                "message": "Refusing to delete the workspace root."
            }, ensure_ascii=False)

        # 路径越界检查，确保 dir_path 在工作区目录下
        if not target.startswith(safe_root):
            return json.dumps({
                "status": "error",
                "message": f"Access to '{dir_path}' is denied."
            }, ensure_ascii=False)
        # 确保 dir_path 存在
        if not os.path.exists(target):
            return json.dumps({
                "status": "error",
                "message": f"'{target}' does not exist."
            }, ensure_ascii=False)

        # 收集待删除的文件列表（目录扫描属磁盘 I/O，丢线程池执行）
        try:
            to_delete: list[str] = await asyncio.to_thread(
                _collect_delete_targets, target, patterns
            )
        except OSError as exc:
            return json.dumps({
                "status": "error",
                "message": f"Cannot scan '{target}': {exc}"
            }, ensure_ascii=False)

    # 如果没有匹配的文件，则返回
    if not to_delete:
        return json.dumps({
            "status": "ok",
            "message": f"Nothing matched in '{dir_path}'.",
            "deleted": [],
            "count": 0,
        }, ensure_ascii=False)

    # 检查删除数量是否超过限制（收集后、动手前检查，符合安全原则）
    if len(to_delete) > CLEAN_MAX_ITEMS:
        return json.dumps({
            "status": "error",
            "message": (
                f"Would delete {len(to_delete)} items, exceeding the "
                f"{CLEAN_MAX_ITEMS} per-call limit. Narrow the patterns "
                f"or target subdirectories."
            )
        }, ensure_ascii=False)

    to_delete.sort()
    deleted: list[str] = []

    # 删除阶段：_clean_lock 防多个 clean_dir 并发互踩；逐项 _get_file_lock
    # 与 str_replace / write_file 互斥，防“删除正在被写/替换的文件”导致删了又复活；
    # 锁的获取/释放在事件循环内完成，单路径删除动作（rename/rmtree/unlink）丢线程池
    async with _clean_lock:
        for path in to_delete:
            async with _get_file_lock(path):
                try:
                    await asyncio.to_thread(_delete_one, path)
                except OSError as exc:
                    return json.dumps({
                        "status": "error",
                        "message": f"Cannot delete {path}: {exc}",
                        "deleted": [os.path.relpath(p, safe_root) for p in deleted],
                        "count": len(deleted),
                    }, ensure_ascii=False)
                deleted.append(path)

    # 删除完成，返回结果
    return json.dumps({
        "status": "ok",
        "message": f"[DELETED] {len(deleted)} item(s)",
        "deleted": [os.path.relpath(p, safe_root) for p in deleted],
        "count": len(deleted),
    }, ensure_ascii=False)
