"""write_file 全方面测试：参数校验、路径安全、创建/覆盖语义、原子写与响应契约。

测试项目：
- test_write_file_invalid_file_path:                 参数化验证空/空白/非字符串 file_path 拒绝
- test_write_file_invalid_content_type:              参数化验证非字符串 content 拒绝（含空值吞噬回归）
- test_write_file_empty_content_valid:               验证空串 content 写空文件（合法）
- test_write_file_unknown_encoding:                  验证未知编码拒绝
- test_write_file_encoding_non_str:                  参数化验证非字符串 encoding 拒绝（TypeError 兜底）
- test_write_file_workspace_not_configured:          验证工作区未配置时 RuntimeError
- test_write_file_exceeds_max_size:                  验证超过 MAX_WRITE_SIZE 拒绝
- test_write_file_at_max_size_boundary:              验证恰好 MAX_WRITE_SIZE 放行（边界）
- test_write_file_multibyte_bytes_semantics:         验证按字节数算大小（多字节字符超限）
- test_write_file_relative_path:                     验证相对路径解析为工作区内绝对路径
- test_write_file_absolute_path_inside:              验证工作区内绝对路径与相对路径等价
- test_write_file_home_expansion:                    验证 ~ 展开为 HOME 下路径
- test_write_file_parent_traversal_denied:           验证 ../ 跳出工作区被拦截
- test_write_file_absolute_outside_denied:           验证系统绝对路径（/etc/hosts）被拦截
- test_write_file_prefix_trap_denied:                验证同名前缀兄弟目录被拦截
- test_write_file_symlink_outside_denied:            验证符号链接指向工作区外被拦截
- test_write_file_symlink_inside_allowed:            验证符号链接指向工作区内写入真实目标
- test_write_file_create_new_file:                   验证创建新文件（CREATED + 内容 + path）
- test_write_file_create_nested_dirs:                验证深层父目录自动创建
- test_write_file_create_absolute_path:              验证绝对路径创建
- test_write_file_create_umask_mode:                 验证新文件权限 = 0o666 & ~umask（0600 陷阱回归）
- test_write_file_create_empty_file:                 验证写空文件（0 行）
- test_write_file_create_whitespace_content:         验证纯空白内容原样保真（不 strip 设计锁定）
- test_write_file_overwrite_existing:                验证覆盖已存在文件（OVERWRITTEN + diff）
- test_write_file_overwrite_keeps_mode:              验证覆盖保留原权限
- test_write_file_overwrite_readonly_file:           验证覆盖只读文件成功且权限保留
- test_write_file_unchanged_same_content:            验证内容相同返回 UNCHANGED（path + diff 契约）
- test_write_file_unchanged_mtime_inode:             验证 UNCHANGED 不触碰文件（mtime/inode 不变）
- test_write_file_empty_file_unchanged:              验证空文件写空串返回 UNCHANGED
- test_write_file_overwrite_large_old_file:          验证原文件超限时限长读取并正确覆盖
- test_write_file_overwrite_undecodable_not_blocking: 验证覆盖不可解码文件不阻塞（diff.old 为空）
- test_write_file_overwrite_undecodable_empty:       验证读失败时不误判 UNCHANGED（清空成功）
- test_write_file_target_is_directory:               验证目标路径是目录拒绝
- test_write_file_parent_path_is_file:               验证父路径是文件时 makedirs 兜底
- test_write_file_readonly_dir_graceful:             验证目录只读时优雅返回 error（不裸炸）
- test_write_file_traversal_no_side_effect:          验证越界路径不产生任何副作用
- test_write_file_failed_write_no_temp:              验证写失败无临时文件残留
- test_write_file_gbk_write_read:                    验证 gbk 编码写入与读回
- test_write_file_latin1_write:                      验证 latin-1 编码写入
- test_write_file_ascii_unencodable_rejected:        验证不可编码内容提前拦截且不产生文件
- test_write_file_diff_truncation:                   验证超长 old/new 截断加标记、短文本原样
- test_write_file_diff_at_boundary:                  验证恰好 MAX_DIFF_SIZE 不截断（边界）
- test_write_file_line_count_variants:               参数化验证 message 行数计算全边界
- test_write_file_success_contract:                  验证 ok 响应字段契约（无 count/replace_all）
- test_write_file_error_contract:                    参数化验证 error 响应只有 status/message
- test_write_file_lock_shared_same_path:             验证同路径同锁对象（并发前置）
- test_write_file_inode_replaced:                    验证覆盖换 inode 的原子替换
- test_write_file_no_temp_left:                      验证成功写入后无临时文件残留
- test_write_file_special_chars_fidelity:            验证特殊字符内容完整保真

覆盖场景：
- 参数校验：file_path 空/空白/非字符串四类拒绝；content 非字符串拒绝（None/0/False/[]
  曾静默写空文件的空值吞噬回归）；空串合法写空文件；encoding 未知编码与
  非字符串（TypeError 曾裸炸）两类拒绝；workspace 未配置抛 RuntimeError
- 大小限制：超过 MAX_WRITE_SIZE 拒绝、恰好等于放行、按字节数计算
  （"中"*4 仅 4 字符但 12 字节超限，与 str_replace 字符语义区分）
- 路径安全：相对/绝对/~/子目录四类合法形态；../ 与系统绝对路径与同名前缀兄弟目录
  与符号链接越界四类拒绝（symlink 经 realpath 解析后拦截）；工作区内符号链接
  写入真实目标且链接本身保留
- 创建语义：CREATED 标记、深层父目录自动创建、新文件权限 0o666 & ~umask
  （mkstemp 0600 陷阱回归）、空文件、纯空白内容不 strip 保真
- 覆盖语义：OVERWRITTEN 标记与 diff.old/new、覆盖保留原权限（含只读文件）、
  UNCHANGED 短路（mtime/inode 不变）、空文件写空串 UNCHANGED、大原文件限长读、
  覆盖不可解码文件不阻塞（diff.old 为空）且不误判 UNCHANGED
- 错误路径：目标为目录、父路径为文件（makedirs 兜底）、目录只读（mkstemp 兜底
  + 恢复权限）、越界无副作用、失败无临时文件残留
- 编码：gbk / latin-1 写入读回、不可编码内容提前拦截（写入前）
- diff 截断：超过 MAX_DIFF_SIZE（50）截断加 "\n... [truncated]"、恰好 50 不截断
- 响应契约：ok 分支固定字段（status/message/path/diff{old,new}，无 count/replace_all），
  error 分支仅 status/message；message 前缀 [CREATED]/[OVERWRITTEN]/[UNCHANGED] 与行数
- 原子写：inode 替换、无临时文件残留、锁对象按路径单例（并发测试前置）

测试用例数量：70
"""

import os

import pytest

from core.tools._kernel import _fs_mutate
from core.tools._kernel._fs_mutate import write_file
from tests.helpers import make_text_file, read_json
from utils.settings import settings


@pytest.mark.parametrize("bad_path", ["", "   ", None, 123, ["a.py"]])
@pytest.mark.asyncio
async def test_write_file_invalid_file_path(workspace, bad_path):
    """参数校验：file_path：验证空/空白/非字符串 file_path 拒绝。

    参数化覆盖 "" / "   " / None / 123 / ["a.py"] 五类非法输入：
    - 统一返回 error，message 固定为 "file_path must be a non-empty string."
    """
    r = read_json(await write_file(bad_path, "foo"))
    assert r["status"] == "error"
    assert r["message"] == "file_path must be a non-empty string."


@pytest.mark.parametrize("bad_content", [None, 0, False, [], ["foo"], 3.14])
@pytest.mark.asyncio
async def test_write_file_invalid_content_type(workspace, bad_content):
    """参数校验：content 类型：验证非字符串 content 拒绝（空值吞噬回归）。

    参数化覆盖 None / 0 / False / [] / ["foo"] / 3.14：
    - 曾存在 `if not content: content = ""` 将 None/0/False/[] 静默转为空文件写入
      的数据破坏漏洞，此处锁定全部拒绝，message 固定为 "content must be a string."
    """
    r = read_json(await write_file("a.py", bad_content))
    assert r["status"] == "error"
    assert r["message"] == "content must be a string."


@pytest.mark.asyncio
async def test_write_file_empty_content_valid(workspace):
    """参数校验：content 空串：验证空串合法（写空文件）。

    "" 与 None 的区别正是空值吞噬漏洞的边界：
    - 返回 ok，message 以 [CREATED] 开头且含 "(0 lines)"，文件大小为 0
    """
    r = read_json(await write_file("empty.txt", ""))
    assert r["status"] == "ok"
    assert r["message"].startswith("[CREATED]")
    assert "(0 lines)" in r["message"]
    assert os.path.getsize(r["path"]) == 0


@pytest.mark.asyncio
async def test_write_file_unknown_encoding(workspace):
    """参数校验：encoding：验证未知编码拒绝。

    "not-a-codec" 无法通过 "".encode() 探测：
    - 返回 error，message 含 "Unknown encoding" 并提示可用编码
    """
    r = read_json(await write_file("a.py", "foo", encoding="not-a-codec"))
    assert r["status"] == "error"
    assert "Unknown encoding" in r["message"]


@pytest.mark.parametrize("bad_encoding", [123, None, ["utf-8"], 3.14])
@pytest.mark.asyncio
async def test_write_file_encoding_non_str(workspace, bad_encoding):
    """参数校验：encoding 类型：验证非字符串 encoding 拒绝（TypeError 兜底）。

    参数化覆盖 123 / None / ["utf-8"] / 3.14：
    - "".encode() 对非字符串抛 TypeError 而非 LookupError，曾导致裸炸；
      修复后统一返回 error，message 含 "Unknown encoding"
    """
    r = read_json(await write_file("a.py", "foo", encoding=bad_encoding))
    assert r["status"] == "error"
    assert "Unknown encoding" in r["message"]


@pytest.mark.asyncio
async def test_write_file_workspace_not_configured(workspace, monkeypatch):
    """环境：workspace 未配置：验证抛 RuntimeError（配置缺失属程序错误）。

    workspace_dir 为空时工具无法确定安全边界：
    - 直接 raise 而非返回 JSON，调用方应保证配置就绪
    """
    monkeypatch.setattr(settings, "workspace_dir", None)
    with pytest.raises(RuntimeError, match="WORKSPACE_DIR is not configured"):
        await write_file("a.py", "foo")


@pytest.mark.asyncio
async def test_write_file_exceeds_max_size(workspace, monkeypatch):
    """大小限制：超限：验证超过 MAX_WRITE_SIZE 拒绝。

    monkeypatch MAX_WRITE_SIZE=10，content 11 字节：
    - 写入前拦截，返回 error（exceeds ... limit）
    """
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    r = read_json(await write_file("big.txt", "x" * 11))
    assert r["status"] == "error"
    assert "exceeds" in r["message"]
    assert "limit" in r["message"]


@pytest.mark.asyncio
async def test_write_file_at_max_size_boundary(workspace, monkeypatch):
    """大小限制：边界：验证恰好 MAX_WRITE_SIZE 放行（不误杀）。

    monkeypatch MAX_WRITE_SIZE=10，content 恰好 10 字节：
    - len(content) == MAX_WRITE_SIZE 不触发超限，写入成功
    """
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    r = read_json(await write_file("ok.txt", "x" * 10))
    assert r["status"] == "ok"
    assert (workspace / "ok.txt").read_text(encoding="utf-8") == "x" * 10


@pytest.mark.asyncio
async def test_write_file_multibyte_bytes_semantics(workspace, monkeypatch):
    """大小限制：字节语义：验证按字节数计算（多字节字符超限）。

    monkeypatch MAX_WRITE_SIZE=10，"中" 占 3 字节：
    - "中"*4 仅 4 字符但 12 字节 → 拒绝（与 str_replace 的字符语义区分）
    - "中"*3 恰好 9 字节 → 放行
    """
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    r = read_json(await write_file("mb.txt", "中" * 4))
    assert r["status"] == "error"
    r = read_json(await write_file("mb.txt", "中" * 3))
    assert r["status"] == "ok"


@pytest.mark.asyncio
async def test_write_file_relative_path(workspace):
    """路径解析：相对路径：验证相对路径解析为工作区内绝对路径。

    传入 "a.py"（工作区内相对路径）：
    - 应解析为工作区内绝对路径，path 字段为 realpath 归一化后的完整路径
    """
    r = read_json(await write_file("a.py", "foo"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")


@pytest.mark.asyncio
async def test_write_file_absolute_path_inside(workspace):
    """路径解析：绝对路径：验证工作区内绝对路径与相对路径等价。

    同一文件分别以相对/绝对形式传入：
    - 两种写法解析到同一路径，写入结果与 path 字段完全一致
    """
    r = read_json(await write_file(str(workspace / "a.py"), "foo"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")
    assert (workspace / "a.py").read_text(encoding="utf-8") == "foo"


@pytest.mark.asyncio
async def test_write_file_home_expansion(workspace, monkeypatch):
    """路径解析：~ 展开：验证 ~ 展开为 HOME 下路径。

    monkeypatch HOME 指向工作区后传入 "~/a.py"：
    - expanduser 展开为工作区内路径，正常创建
    """
    monkeypatch.setenv("HOME", str(workspace))
    r = read_json(await write_file("~/a.py", "foo"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")


@pytest.mark.asyncio
async def test_write_file_parent_traversal_denied(workspace):
    """路径安全：../ 越界：验证 ../ 跳出工作区被拦截。

    "../escape.py" 解析后落在工作区外：
    - 前缀检查拦截，返回 error（is denied）
    """
    r = read_json(await write_file("../escape.py", "foo"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_write_file_absolute_outside_denied(workspace):
    """路径安全：系统绝对路径：验证存在但越界的绝对路径被拦截。

    "/etc/hosts" 真实存在但不在工作区内：
    - 前缀检查拦截，返回 error（is denied）
    """
    r = read_json(await write_file("/etc/hosts", "foo"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_write_file_prefix_trap_denied(workspace):
    """路径安全：前缀陷阱：验证同名前缀兄弟目录被拦截。

    构造 workspace.name + "_evil" 兄弟目录（路径前缀与工作区相同）：
    - safe_root 尾分隔符归一化后不误判，返回 error（is denied）
    """
    evil = workspace.parent / (workspace.name + "_evil")
    evil.mkdir(exist_ok=True)
    r = read_json(await write_file(str(evil / "a.py"), "foo"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_write_file_symlink_outside_denied(workspace):
    """路径安全：符号链接越界：验证指向工作区外的符号链接被拦截。

    工作区内 link.txt → 工作区外 outside.txt：
    - realpath 解析后落在安全根之外，前缀检查拦截，返回 error（is denied）
    """
    outside = workspace.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    link = workspace / "link.txt"
    link.symlink_to(outside)
    r = read_json(await write_file("link.txt", "foo"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]
    assert outside.read_text(encoding="utf-8") == "secret\n"


@pytest.mark.asyncio
async def test_write_file_symlink_inside_allowed(workspace):
    """路径安全：符号链接区内：验证指向工作区内的符号链接写入真实目标。

    工作区内 link.txt → 工作区内 target.txt：
    - realpath 解析到真实目标并写入，符号链接本身保留（os.replace 替换的是目标）
    """
    make_text_file(workspace, "target.txt", "old")
    link = workspace / "link.txt"
    link.symlink_to(workspace / "target.txt")
    r = read_json(await write_file("link.txt", "new"))
    assert r["status"] == "ok"
    assert link.is_symlink()
    assert (workspace / "target.txt").read_text(encoding="utf-8") == "new"


@pytest.mark.asyncio
async def test_write_file_create_new_file(workspace):
    """创建语义：新文件：验证创建标记、内容与路径。

    工作区内不存在的 "a.py"：
    - message 以 [CREATED] 开头，path 为归一化绝对路径，内容精确写入
    """
    r = read_json(await write_file("a.py", "hello\nworld\n"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[CREATED]")
    assert r["path"] == str(workspace.resolve() / "a.py")
    assert (workspace / "a.py").read_text(encoding="utf-8") == "hello\nworld\n"


@pytest.mark.asyncio
async def test_write_file_create_nested_dirs(workspace):
    """创建语义：嵌套目录：验证深层父目录自动创建。

    "a/b/c/d.txt" 的父目录链均不存在：
    - makedirs(exist_ok=True) 递归创建，文件写入成功
    """
    r = read_json(await write_file("a/b/c/d.txt", "deep"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[CREATED]")
    assert (workspace / "a/b/c/d.txt").read_text(encoding="utf-8") == "deep"


@pytest.mark.asyncio
async def test_write_file_create_absolute_path(workspace):
    """创建语义：绝对路径：验证工作区内绝对路径创建。

    传入工作区内绝对路径（含不存在的子目录）：
    - 创建成功，path 与传入路径一致（realpath 归一化）
    """
    target = workspace / "sub" / "abs.py"
    r = read_json(await write_file(str(target), "abs"))
    assert r["status"] == "ok"
    assert r["path"] == str(target.resolve())
    assert target.read_text(encoding="utf-8") == "abs"


@pytest.mark.asyncio
async def test_write_file_create_umask_mode(workspace):
    """创建语义：新文件权限：验证权限 = 0o666 & ~umask（0600 陷阱回归）。

    mkstemp 创建的临时文件权限固定 0600，若未修正将直接成为新文件权限：
    - 断言最终权限等于 0o666 & ~umask（读取当前 umask 后立即恢复）
    """
    old_umask = os.umask(0)
    os.umask(old_umask)
    r = read_json(await write_file("perm.py", "foo"))
    assert r["status"] == "ok"
    assert os.stat(workspace / "perm.py").st_mode & 0o777 == 0o666 & ~old_umask


@pytest.mark.asyncio
async def test_write_file_create_empty_file(workspace):
    """创建语义：空文件：验证写空文件（0 行）。

    content="" 且文件不存在：
    - [CREATED] (0 lines)，文件存在且大小为 0
    """
    r = read_json(await write_file("empty.txt", ""))
    assert r["status"] == "ok"
    assert r["message"].startswith("[CREATED]")
    assert "(0 lines)" in r["message"]
    assert os.path.exists(workspace / "empty.txt")
    assert os.path.getsize(workspace / "empty.txt") == 0


@pytest.mark.asyncio
async def test_write_file_create_whitespace_content(workspace):
    """创建语义：空白内容：验证纯空白内容原样保真（不 strip 设计锁定）。

    content="  " 与空串语义不同：
    - 原样写入两个空格，文件大小 2，不进行任何裁剪
    """
    r = read_json(await write_file("ws.txt", "  "))
    assert r["status"] == "ok"
    assert os.path.getsize(workspace / "ws.txt") == 2


@pytest.mark.asyncio
async def test_write_file_overwrite_existing(workspace):
    """覆盖语义：已有文件：验证覆盖标记与 diff 摘要。

    覆盖已存在文件：
    - message 以 [OVERWRITTEN] 开头，内容更新，diff.old/new 分别为原内容与新内容
    """
    make_text_file(workspace, "a.py", "old content\n")
    r = read_json(await write_file("a.py", "new content\n"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[OVERWRITTEN]")
    assert (workspace / "a.py").read_text(encoding="utf-8") == "new content\n"
    assert r["diff"]["old"] == "old content\n"
    assert r["diff"]["new"] == "new content\n"


@pytest.mark.asyncio
async def test_write_file_overwrite_keeps_mode(workspace):
    """覆盖语义：权限保留：验证覆盖已存在文件后权限不变。

    chmod 0o640 后覆盖：
    - 覆盖分支取原文件 st_mode 恢复，权限仍为 0o640
    """
    fp = make_text_file(workspace, "a.py", "old")
    os.chmod(fp, 0o640)
    r = read_json(await write_file("a.py", "new"))
    assert r["status"] == "ok"
    assert os.stat(fp).st_mode & 0o777 == 0o640


@pytest.mark.asyncio
async def test_write_file_overwrite_readonly_file(workspace):
    """覆盖语义：只读文件：验证覆盖只读文件成功且权限保留。

    chmod 0o444 后覆盖（读原内容可读、os.replace 只需目录写权限）：
    - 覆盖成功，权限仍为 0o444
    """
    fp = make_text_file(workspace, "a.py", "old")
    os.chmod(fp, 0o444)
    try:
        r = read_json(await write_file("a.py", "new"))
        assert r["status"] == "ok"
        assert os.stat(fp).st_mode & 0o777 == 0o444
        assert fp.read_text(encoding="utf-8") == "new"
    finally:
        os.chmod(fp, 0o644)


@pytest.mark.asyncio
async def test_write_file_unchanged_same_content(workspace):
    """覆盖语义：UNCHANGED：验证内容相同返回 UNCHANGED。

    写入内容与文件现有内容完全一致：
    - 返回 ok，message 以 [UNCHANGED] 开头，携带 path 与同结构 diff（old == new）
    """
    make_text_file(workspace, "a.py", "same\n")
    r = read_json(await write_file("a.py", "same\n"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[UNCHANGED]")
    assert r["path"] == str(workspace.resolve() / "a.py")
    assert r["diff"] == {"old": "same\n", "new": "same\n"}


@pytest.mark.asyncio
async def test_write_file_unchanged_mtime_inode(workspace):
    """覆盖语义：UNCHANGED 短路：验证不触碰文件（mtime/inode 不变）。

    内容一致时原子写被短路：
    - 前后 st_mtime_ns 与 st_ino 完全一致，证明未发生任何写操作
    """
    fp = make_text_file(workspace, "a.py", "same\n")
    before = os.stat(fp)
    r = read_json(await write_file("a.py", "same\n"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[UNCHANGED]")
    after = os.stat(fp)
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_ino == before.st_ino


@pytest.mark.asyncio
async def test_write_file_empty_file_unchanged(workspace):
    """覆盖语义：空文件：验证空文件写空串返回 UNCHANGED。

    空文件内容 "" 与 content "" 一致：
    - 返回 UNCHANGED（不是 CREATED/OVERWRITTEN），文件保持空
    """
    make_text_file(workspace, "a.py", "")
    r = read_json(await write_file("a.py", ""))
    assert r["status"] == "ok"
    assert r["message"].startswith("[UNCHANGED]")


@pytest.mark.asyncio
async def test_write_file_overwrite_large_old_file(workspace, monkeypatch):
    """覆盖语义：大原文件：验证原文件超限时限长读取并正确覆盖。

    monkeypatch MAX_WRITE_SIZE=10，原文件 20 字符（> MAX_WRITE_SIZE）：
    - 读取被限制在 MAX_WRITE_SIZE+1 字符，必不等于 content，直接覆盖
    - 不误判 UNCHANGED，且无全量读入内存的 OOM 风险
    """
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    make_text_file(workspace, "a.py", "x" * 20)
    r = read_json(await write_file("a.py", "small"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[OVERWRITTEN]")
    assert (workspace / "a.py").read_text(encoding="utf-8") == "small"


@pytest.mark.asyncio
async def test_write_file_overwrite_undecodable_not_blocking(workspace):
    """覆盖语义：不可解码文件：验证覆盖不阻塞（diff.old 为空）。

    gbk 编码的中文文件按 utf-8 读会解码失败：
    - 读失败不阻塞写入（diff.old 是装饰性信息），覆盖成功且内容正确
    - diff.old == ""（读失败置空），diff.new 为新内容
    """
    fp = workspace / "gbk.txt"
    fp.write_bytes("中文旧内容\n".encode("gbk"))
    r = read_json(await write_file("gbk.txt", "utf8 new"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[OVERWRITTEN]")
    assert fp.read_text(encoding="utf-8") == "utf8 new"
    assert r["diff"]["old"] == ""
    assert r["diff"]["new"] == "utf8 new"


@pytest.mark.asyncio
async def test_write_file_overwrite_undecodable_empty(workspace):
    """覆盖语义：读失败防误判：验证覆盖不可解码文件写空串不返回 UNCHANGED。

    gbk 文件读失败时 old_content 为空，若直接比较会误判 "" == "" 为 UNCHANGED，
    导致文件未被清空（read_failed 标记修复的回归用例）：
    - 返回 OVERWRITTEN，文件确实被清空为 0 字节
    """
    fp = workspace / "gbk.txt"
    fp.write_bytes("中文旧内容\n".encode("gbk"))
    r = read_json(await write_file("gbk.txt", ""))
    assert r["status"] == "ok"
    assert r["message"].startswith("[OVERWRITTEN]")
    assert os.path.getsize(fp) == 0


@pytest.mark.asyncio
async def test_write_file_target_is_directory(workspace):
    """错误路径：目标为目录：验证指向目录拒绝。

    传入工作区内目录 "sub"：
    - 锁内文件类型检查拦截，返回 error（is a directory）
    """
    (workspace / "sub").mkdir()
    r = read_json(await write_file("sub", "foo"))
    assert r["status"] == "error"
    assert "is a directory" in r["message"]


@pytest.mark.asyncio
async def test_write_file_parent_path_is_file(workspace):
    """错误路径：父路径为文件：验证 makedirs 兜底。

    "block" 是已存在文件，写入 "block/x.txt" 时 makedirs 抛 FileExistsError：
    - 已纳入异常兜底，返回 error（Cannot create directory）
    """
    (workspace / "block").write_text("x", encoding="utf-8")
    r = read_json(await write_file("block/x.txt", "y"))
    assert r["status"] == "error"
    assert "Cannot create directory" in r["message"]


@pytest.mark.asyncio
async def test_write_file_readonly_dir_graceful(workspace):
    """错误路径：目录只读：验证 mkstemp 失败优雅返回 error（不裸炸）。

    chmod 目录 0o555 后 mkstemp 抛 PermissionError：
    - 已纳入异常兜底，返回 error（Cannot write to）
    - 原文件内容不变，无临时文件残留；finally 恢复目录 0o755
    """
    fp = make_text_file(workspace, "a.py", "keep\n")
    os.chmod(workspace, 0o555)
    try:
        r = read_json(await write_file("a.py", "new"))
        assert r["status"] == "error"
        assert "Cannot write to" in r["message"]
    finally:
        os.chmod(workspace, 0o755)
    assert fp.read_text(encoding="utf-8") == "keep\n"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.py"]


@pytest.mark.asyncio
async def test_write_file_traversal_no_side_effect(workspace):
    """错误路径：越界无副作用：验证越界路径不产生任何文件或目录。

    "../escape/x.txt" 在越界检查后即被拦截：
    - 工作区外不出现 escape/ 目录（检查先于 makedirs）
    """
    r = read_json(await write_file("../escape/x.txt", "foo"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]
    assert not (workspace.parent / "escape").exists()


@pytest.mark.asyncio
async def test_write_file_failed_write_no_temp(workspace):
    """错误路径：失败无残留：验证写失败无临时文件残留。

    makedirs 失败（父路径是文件）后：
    - 工作区内仅剩 block 文件，无 mkstemp 前缀的临时文件
    """
    (workspace / "block").write_text("x", encoding="utf-8")
    r = read_json(await write_file("block/x.txt", "y"))
    assert r["status"] == "error"
    assert sorted(p.name for p in workspace.iterdir()) == ["block"]


@pytest.mark.asyncio
async def test_write_file_gbk_write_read(workspace):
    """编码：gbk：验证 gbk 编码写入与读回。

    encoding="gbk" 写入中文：
    - 磁盘字节与 "你好，世界".encode("gbk") 完全一致
    """
    r = read_json(await write_file("gbk.txt", "你好，世界", encoding="gbk"))
    assert r["status"] == "ok"
    assert (workspace / "gbk.txt").read_bytes() == "你好，世界".encode("gbk")


@pytest.mark.asyncio
async def test_write_file_latin1_write(workspace):
    """编码：latin-1：验证 latin-1 编码写入。

    encoding="latin-1" 写入 é：
    - 磁盘字节与 "café".encode("latin-1") 完全一致（单字节 0xE9）
    """
    r = read_json(await write_file("l1.txt", "café", encoding="latin-1"))
    assert r["status"] == "ok"
    assert (workspace / "l1.txt").read_bytes() == "café".encode("latin-1")


@pytest.mark.asyncio
async def test_write_file_ascii_unencodable_rejected(workspace):
    """编码：不可编码：验证 ascii 无法编码内容提前拦截且不产生文件。

    encoding="ascii" 写入中文：
    - 写入前预检（content.encode）拦截，返回 error，文件不存在
    """
    r = read_json(await write_file("a.py", "中文", encoding="ascii"))
    assert r["status"] == "error"
    assert "not encodable as ascii" in r["message"]
    assert not (workspace / "a.py").exists()


@pytest.mark.asyncio
async def test_write_file_diff_truncation(workspace):
    """diff 截断：验证超长 old/new 截断加标记、短文本原样。

    600 字符内容超过 MAX_DIFF_SIZE（500）：
    - diff.old / diff.new 截断为前 500 字符 + "\n... [truncated]"
    - 短文本（"y\n"）原样返回
    """
    long_old = "x" * 600
    make_text_file(workspace, "a.py", long_old)
    r = read_json(await write_file("a.py", "y" * 600))
    assert r["status"] == "ok"
    assert r["diff"]["old"] == "x" * 500 + "\n... [truncated]"
    assert r["diff"]["new"] == "y" * 500 + "\n... [truncated]"
    r = read_json(await write_file("a.py", "y\n"))
    assert r["diff"]["old"] == "y" * 500 + "\n... [truncated]"
    assert r["diff"]["new"] == "y\n"


@pytest.mark.asyncio
async def test_write_file_diff_at_boundary(workspace):
    """diff 截断：边界：验证恰好 MAX_DIFF_SIZE 不截断。

    old/new 恰好 500 字符：
    - 原样返回，无 "[truncated]" 标记
    """
    content = "z" * 500
    make_text_file(workspace, "a.py", content)
    r = read_json(await write_file("a.py", content))
    assert r["status"] == "ok"
    assert r["message"].startswith("[UNCHANGED]")
    assert r["diff"]["old"] == content
    assert r["diff"]["new"] == content


@pytest.mark.parametrize("content, expected_lines", [
    ("", 0),
    ("a", 1),
    ("a\n", 1),
    ("\n", 1),
    ("a\nb", 2),
    ("a\nb\nc\n", 3),
    ("\n\n", 2),
])
@pytest.mark.asyncio
async def test_write_file_line_count_variants(workspace, content, expected_lines):
    """响应契约：行数：参数化验证 message 行数计算全边界。

    覆盖空串 / 单行无尾换行 / 尾换行 / 纯换行 / 多行 / 连续空行：
    - message 恒为 "[CREATED] {path} ({expected_lines} lines)"
    """
    r = read_json(await write_file("lc.txt", content))
    assert r["status"] == "ok"
    assert r["message"] == f"[CREATED] {r['path']} ({expected_lines} lines)"


@pytest.mark.asyncio
async def test_write_file_success_contract(workspace):
    """响应契约：ok 分支：验证字段完整且不含 str_replace 专属字段。

    ok 响应固定四字段：
    - status / message / path / diff，diff 固定两子字段 old / new
    - 不含 count / replace_all（与 str_replace 的 diff 结构区分）
    """
    make_text_file(workspace, "a.py", "old\n")
    r = read_json(await write_file("a.py", "new\n"))
    assert set(r.keys()) == {"status", "message", "path", "diff"}
    assert r["status"] == "ok"
    assert set(r["diff"].keys()) == {"old", "new"}


@pytest.mark.parametrize("scenario", ["traversal", "directory", "oversize", "bad_content"])
@pytest.mark.asyncio
async def test_write_file_error_contract(workspace, scenario, monkeypatch):
    """响应契约：error 分支：参数化验证四类 error 只有 status/message 两字段。

    覆盖越界 / 目录 / 超限 / 非法 content 四类错误：
    - 统一返回 {status, message}，不含 path / diff
    """
    (workspace / "sub").mkdir()
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    if scenario == "traversal":
        r = read_json(await write_file("../x.py", "foo"))
    elif scenario == "directory":
        r = read_json(await write_file("sub", "foo"))
    elif scenario == "oversize":
        r = read_json(await write_file("big.py", "x" * 11))
    else:
        r = read_json(await write_file("a.py", None))
    assert set(r.keys()) == {"status", "message"}
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_write_file_lock_shared_same_path(workspace):
    """锁：单例：验证同路径返回同一锁对象、不同路径不同锁。

    write_file 与 str_replace 共享模块级 _file_locks：
    - 同一路径两次获取是同一对象（并发互斥的前提），不同路径互不相同
    """
    p1 = str(workspace.resolve() / "a.py")
    p2 = str(workspace.resolve() / "b.py")
    assert _fs_mutate._get_file_lock(p1) is _fs_mutate._get_file_lock(p1)
    assert _fs_mutate._get_file_lock(p1) is not _fs_mutate._get_file_lock(p2)


@pytest.mark.asyncio
async def test_write_file_inode_replaced(workspace):
    """原子写：inode：验证覆盖换 inode 的原子替换。

    覆盖前后 st_ino 不同：
    - 证明新内容写入临时文件后整体换名，非原地改写
    """
    fp = make_text_file(workspace, "a.py", "old\n")
    ino_before = os.stat(fp).st_ino
    r = read_json(await write_file("a.py", "new\n"))
    assert r["status"] == "ok"
    assert os.stat(fp).st_ino != ino_before


@pytest.mark.asyncio
async def test_write_file_no_temp_left(workspace):
    """原子写：无残留：验证成功写入后无临时文件残留。

    mkstemp 临时文件在 finally 中清理：
    - 成功后目录仅剩目标文件
    """
    r = read_json(await write_file("a.py", "foo"))
    assert r["status"] == "ok"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.py"]


@pytest.mark.asyncio
async def test_write_file_special_chars_fidelity(workspace):
    """内容保真：特殊字符：验证各类特殊字符完整保真。

    前导/尾随空格、制表符、\r\n、emoji、中文、连续空行一次性写入：
    - 读回内容与写入内容逐字符一致（无任何转换/裁剪）
    """
    content = "  leading spaces\n\ttab\ttab\n\r\nmix\r\n😀 中文 混合\n\n\nend  \n"
    r = read_json(await write_file("special.txt", content))
    assert r["status"] == "ok"
    assert (workspace / "special.txt").read_bytes() == content.encode("utf-8")
