"""str_replace 全方面测试：参数校验、路径安全、匹配语义、替换语义、原子写与响应契约。

测试项目：
- test_str_replace_invalid_file_path:             参数化验证空/空白/非字符串 file_path 拒绝
- test_str_replace_invalid_old_str_type:          参数化验证非字符串 old_str 拒绝
- test_str_replace_empty_old_str:                 验证空串 old_str 拒绝
- test_str_replace_whitespace_old_str_valid:      验证空白 old_str 合法（不 strip 设计锁定）
- test_str_replace_invalid_new_str_type:          参数化验证非字符串 new_str 拒绝
- test_str_replace_empty_new_str_deletes:         验证空串 new_str 表示删除
- test_str_replace_unknown_encoding:              验证未知编码拒绝
- test_str_replace_workspace_not_configured:      验证工作区未配置时 RuntimeError
- test_str_replace_relative_path:                 验证相对路径解析为工作区内绝对路径
- test_str_replace_absolute_path_inside:          验证工作区内绝对路径与相对路径等价
- test_str_replace_home_expansion:                验证 ~ 展开为 HOME 下路径
- test_str_replace_parent_traversal_denied:       验证 ../ 跳出工作区被拦截
- test_str_replace_absolute_outside_denied:       验证系统绝对路径（/etc/hosts）被拦截
- test_str_replace_prefix_trap_denied:            验证同名前缀兄弟目录被拦截
- test_str_replace_nonexistent_file:              验证不存在文件拒绝
- test_str_replace_path_is_directory:             验证指向目录拒绝
- test_str_replace_subdir_file:                   验证子目录内文件正常替换
- test_str_replace_undecodable_file:              验证解码失败拒绝并提示换编码
- test_str_replace_permission_denied_read:        验证读取权限拒绝
- test_str_replace_gbk_encoding:                  验证 encoding 参数按指定编码解码
- test_str_replace_exceeds_max_size:              验证超过 MAX_WRITE_SIZE 拒绝
- test_str_replace_at_max_size_boundary:          验证恰好 MAX_WRITE_SIZE 放行（边界）
- test_str_replace_single_match_success:          验证单次精确匹配替换成功
- test_str_replace_text_not_found:                验证 old_str 不存在报错并提示 view_file
- test_str_replace_multiple_matches_rejected:     验证多匹配未开 replace_all 拒绝
- test_str_replace_replace_all:                   验证 replace_all 全量替换
- test_str_replace_replace_all_single:            验证 replace_all 单次匹配也标记 ALL
- test_str_replace_unchanged_identical:           验证 old_str == new_str 返回 UNCHANGED
- test_str_replace_unchanged_multiple_matches:    验证 UNCHANGED 优先于多匹配检查（count 保留）
- test_str_replace_case_sensitive:                验证匹配区分大小写
- test_str_replace_multiline_old_str:             验证跨行精确匹配
- test_str_replace_unicode:                       验证中文内容替换
- test_str_replace_digit_text:                    验证数字文本（字符串形式）替换
- test_str_replace_diff_count_single:             验证 replace_all=False 时 diff.count 为 1
- test_str_replace_new_str_with_newlines:         验证 new_str 含换行写入多行内容
- test_str_replace_surrounding_preserved:         验证替换不破坏前后文
- test_str_replace_delete_content:                验证删除语义的文件内容
- test_str_replace_diff_truncation:               验证超长 old/new 截断与短文本原样
- test_str_replace_permissions_preserved:         验证替换后文件权限保留
- test_str_replace_no_temp_left:                  验证无临时文件残留
- test_str_replace_inode_replaced:                验证 os.replace 换 inode 的原子替换
- test_str_replace_encoding_failure_atomic:       验证编码失败时原文件内容不变（原子性）
- test_str_replace_readonly_dir_graceful:         验证目录只读时优雅返回 error（不裸炸）
- test_str_replace_success_contract:              验证 ok 响应字段契约（status/path/diff/message）
- test_str_replace_error_contract:                参数化验证 error 响应只有 status/message
- test_str_replace_empty_file:                    验证空文件替换报 not found

覆盖场景：
- 参数校验：file_path/old_str/new_str 空、空白、非字符串（None/数字/列表）四类拒绝，
  空白 old_str 合法（精确文本替换不 strip，与正则 pattern 语义不同）
- 路径安全：相对/绝对/~/子目录四类合法形态，../ 与系统绝对路径与同名前缀兄弟目录
  三类越界拒绝（safe_root 尾分隔符防前缀陷阱），不存在/目录两类形态拒绝
- 读取阶段：非法编码字节、权限拒绝、encoding 参数按指定编码解码
- 大小限制：超过 MAX_WRITE_SIZE 拒绝、恰好等于放行（monkeypatch 常量隔离）
- 匹配语义：单次成功、不存在、多匹配未开 replace_all 拒绝、replace_all 全量、
  old == new 的 UNCHANGED（含多匹配时优先于多匹配检查）、大小写敏感、跨行、中文、数字
- 替换语义：diff.count 契约、new_str 含换行、前后文保留、删除语义、diff 截断
- 原子写：权限保留（chmod 恢复）、无临时文件残留、inode 替换、编码失败内容不变、
  目录只读优雅降级（mkstemp 纳入异常兜底）
- 响应契约：ok 分支固定字段（status/message/path/diff{old,new,count,replace_all}），
  error 分支仅 status/message

测试用例数量：55
"""

import os

import pytest

from core.tools._kernel import _fs_mutate
from core.tools._kernel._fs_mutate import str_replace
from tests.helpers import make_text_file, read_json
from utils.settings import settings


@pytest.mark.parametrize("bad_path", ["", "   ", None, 123, ["a.py"]])
@pytest.mark.asyncio
async def test_str_replace_invalid_file_path(workspace, bad_path):
    """参数校验：file_path：验证空/空白/非字符串 file_path 拒绝。

    参数化覆盖 "" / "   " / None / 123 / ["a.py"] 五类非法输入：
    - 统一返回 error，message 固定为 "file_path must be a non-empty string."
    """
    r = read_json(await str_replace(bad_path, "foo", "bar"))
    assert r["status"] == "error"
    assert r["message"] == "file_path must be a non-empty string."


@pytest.mark.parametrize("bad_old", [None, 123, ["foo"]])
@pytest.mark.asyncio
async def test_str_replace_invalid_old_str_type(workspace, bad_old):
    """参数校验：old_str 类型：验证非字符串 old_str 拒绝。

    参数化覆盖 None / 123 / ["foo"]：
    - 统一返回 error，message 固定为 "old_str must be a non-empty string."
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", bad_old, "bar"))
    assert r["status"] == "error"
    assert r["message"] == "old_str must be a non-empty string."


@pytest.mark.asyncio
async def test_str_replace_empty_old_str(workspace):
    """参数校验：old_str 空串：验证空串 old_str 拒绝。

    "" 无法构成精确替换目标：
    - 返回 error，message 与类型非法共用 "old_str must be a non-empty string."
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "", "bar"))
    assert r["status"] == "error"
    assert r["message"] == "old_str must be a non-empty string."


@pytest.mark.asyncio
async def test_str_replace_whitespace_old_str_valid(workspace):
    """参数校验：old_str 空白：验证空白 old_str 合法（不 strip 设计锁定）。

    精确文本替换语义下，空白文本（如双空格缩进）是合法替换目标：
    - "  " 替换为 " " 应成功，与正则 pattern 的 strip 校验语义不同
    """
    fp = make_text_file(workspace, "a.py", "foo  bar\n")
    r = read_json(await str_replace("a.py", "  ", " "))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "foo bar\n"


@pytest.mark.parametrize("bad_new", [None, 123])
@pytest.mark.asyncio
async def test_str_replace_invalid_new_str_type(workspace, bad_new):
    """参数校验：new_str 类型：验证非字符串 new_str 拒绝。

    参数化覆盖 None / 123：
    - 统一返回 error，message 固定为 "new_str must be a string."
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", bad_new))
    assert r["status"] == "error"
    assert r["message"] == "new_str must be a string."


@pytest.mark.asyncio
async def test_str_replace_empty_new_str_deletes(workspace):
    """参数校验：new_str 空串：验证空串 new_str 表示删除语义。

    "" 是合法替换目标（删除 old_str 本身）：
    - "foo bar" 中替换 "foo " 为空串后剩余 "bar\n"
    """
    fp = make_text_file(workspace, "a.py", "foo bar\n")
    r = read_json(await str_replace("a.py", "foo ", ""))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "bar\n"


@pytest.mark.asyncio
async def test_str_replace_unknown_encoding(workspace):
    """参数校验：encoding：验证未知编码拒绝。

    "not-a-codec" 无法通过 "".encode() 探测：
    - 返回 error，message 含 "Unknown encoding" 并提示可用编码
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar", encoding="not-a-codec"))
    assert r["status"] == "error"
    assert "Unknown encoding" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_workspace_not_configured(workspace, monkeypatch):
    """环境：workspace 未配置：验证抛 RuntimeError（配置缺失属程序错误）。

    workspace_dir 为空时工具无法确定安全边界：
    - 直接 raise 而非返回 JSON，调用方应保证配置就绪
    """
    monkeypatch.setattr(settings, "workspace_dir", None)
    with pytest.raises(RuntimeError, match="WORKSPACE_DIR is not configured"):
        await str_replace("a.py", "foo", "bar")


@pytest.mark.asyncio
async def test_str_replace_relative_path(workspace):
    """路径解析：相对路径：验证相对路径解析为工作区内绝对路径。

    传入 "a.py"（工作区内相对路径）：
    - 应解析为工作区内绝对路径，path 字段为 realpath 归一化后的完整路径
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")


@pytest.mark.asyncio
async def test_str_replace_absolute_path_inside(workspace):
    """路径解析：绝对路径：验证工作区内绝对路径与相对路径等价。

    同一文件分别以相对/绝对形式传入：
    - 两种写法解析到同一路径，替换结果与 path 字段完全一致
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace(str(workspace / "a.py"), "foo", "bar"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")


@pytest.mark.asyncio
async def test_str_replace_home_expansion(workspace, monkeypatch):
    """路径解析：~ 展开：验证 ~ 展开为 HOME 下路径。

    monkeypatch HOME 指向工作区后传入 "~/a.py"：
    - expanduser 展开为工作区内路径，正常替换
    """
    monkeypatch.setenv("HOME", str(workspace))
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("~/a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")


@pytest.mark.asyncio
async def test_str_replace_parent_traversal_denied(workspace):
    """路径安全：../ 越界：验证 ../ 跳出工作区被拦截。

    "../escape.py" 解析后落在工作区外：
    - 前缀检查拦截，返回 error（is denied）
    """
    r = read_json(await str_replace("../escape.py", "foo", "bar"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_absolute_outside_denied(workspace):
    """路径安全：系统绝对路径：验证存在但越界的绝对路径被拦截。

    "/etc/hosts" 真实存在但不在工作区内：
    - 前缀检查先于存在性检查，返回 error（is denied）
    """
    r = read_json(await str_replace("/etc/hosts", "127.0.0.1", "1.1.1.1"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_prefix_trap_denied(workspace):
    """路径安全：前缀陷阱：验证同名前缀兄弟目录被拦截。

    构造 workspace.name + "_evil" 兄弟目录（路径前缀与工作区相同）：
    - safe_root 尾分隔符归一化后不误判，返回 error（is denied）
    """
    evil = workspace.parent / (workspace.name + "_evil")
    evil.mkdir(exist_ok=True)
    (evil / "a.py").write_text("foo\n", encoding="utf-8")
    r = read_json(await str_replace(str(evil / "a.py"), "foo", "bar"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_nonexistent_file(workspace):
    """路径安全：不存在文件：验证不存在文件拒绝。

    "missing.py" 不在工作区内：
    - 返回 error，message 含 "does not exist"
    """
    r = read_json(await str_replace("missing.py", "foo", "bar"))
    assert r["status"] == "error"
    assert "does not exist" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_path_is_directory(workspace):
    """路径安全：目录路径：验证指向目录拒绝。

    传入工作区内目录 "sub"：
    - 文件类型检查拦截，返回 error（is a directory）
    """
    (workspace / "sub").mkdir()
    r = read_json(await str_replace("sub", "foo", "bar"))
    assert r["status"] == "error"
    assert "is a directory" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_subdir_file(workspace):
    """路径安全：子目录文件：验证子目录内文件正常替换。

    "sub/a.py" 位于工作区子目录内：
    - 前缀检查按目录边界放行，替换成功
    """
    fp = make_text_file(workspace, "sub/a.py", "foo\n")
    r = read_json(await str_replace("sub/a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "bar\n"


@pytest.mark.asyncio
async def test_str_replace_undecodable_file(workspace):
    """读取阶段：解码失败：验证非法编码字节拒绝并提示换编码。

    b"\xff\xfe\x00A" 无法按 utf-8 解码：
    - 返回 error，message 含 "cannot be decoded as utf-8" 并提示 gbk/latin-1
    """
    fp = workspace / "bin.dat"
    fp.write_bytes(b"\xff\xfe\x00A")
    r = read_json(await str_replace("bin.dat", "foo", "bar"))
    assert r["status"] == "error"
    assert "cannot be decoded as utf-8" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_permission_denied_read(workspace):
    """读取阶段：权限拒绝：验证读取权限拒绝。

    chmod 0o000 后 open 读抛 PermissionError：
    - 返回 error，message 含 "Permission denied"
    - finally 恢复 0o644，避免影响后续用例
    """
    fp = make_text_file(workspace, "a.py", "foo\n")
    os.chmod(fp, 0o000)
    try:
        r = read_json(await str_replace("a.py", "foo", "bar"))
        assert r["status"] == "error"
        assert "Permission denied" in r["message"]
    finally:
        os.chmod(fp, 0o644)


@pytest.mark.asyncio
async def test_str_replace_gbk_encoding(workspace):
    """读取阶段：encoding 参数：验证按指定编码解码与写入。

    gbk 编码文件传入 encoding="gbk"：
    - 读、写均按 gbk 处理，替换后字节内容与预期一致
    """
    fp = workspace / "gbk.txt"
    fp.write_bytes("你好 foo\n".encode("gbk"))
    r = read_json(await str_replace("gbk.txt", "你好", "再见", encoding="gbk"))
    assert r["status"] == "ok"
    assert fp.read_bytes() == "再见 foo\n".encode("gbk")


@pytest.mark.asyncio
async def test_str_replace_exceeds_max_size(workspace, monkeypatch):
    """大小限制：超限：验证超过 MAX_WRITE_SIZE 拒绝。

    monkeypatch MAX_WRITE_SIZE=10，文件内容 11 字符：
    - read(MAX_WRITE_SIZE+1) 探测超限，返回 error（exceeds ... limit）
    """
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    make_text_file(workspace, "a.py", "x" * 11)
    r = read_json(await str_replace("a.py", "x", "y"))
    assert r["status"] == "error"
    assert "exceeds" in r["message"]
    assert "limit" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_at_max_size_boundary(workspace, monkeypatch):
    """大小限制：边界：验证恰好 MAX_WRITE_SIZE 放行（不误杀）。

    monkeypatch MAX_WRITE_SIZE=10，文件内容恰好 10 字符：
    - len(content) == MAX_WRITE_SIZE 不触发超限，替换成功
    """
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    make_text_file(workspace, "a.py", "x" * 9 + "!")
    r = read_json(await str_replace("a.py", "!", "?"))
    assert r["status"] == "ok"


@pytest.mark.asyncio
async def test_str_replace_single_match_success(workspace):
    """匹配语义：单次命中：验证单次精确匹配替换成功。

    文件 "foo bar\n" 中 "foo" 恰好出现一次：
    - 替换成功，message 以 [REPLACED] 开头，内容变为 "FOO bar\n"
    """
    fp = make_text_file(workspace, "a.py", "foo bar\n")
    r = read_json(await str_replace("a.py", "foo", "FOO"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[REPLACED]")
    assert fp.read_text(encoding="utf-8") == "FOO bar\n"


@pytest.mark.asyncio
async def test_str_replace_text_not_found(workspace):
    """匹配语义：未命中：验证 old_str 不存在报错并提示 view_file。

    "zzz" 不在文件中（count == 0）：
    - 返回 error，message 含 "Text not found" 与 "view_file" 提示
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "zzz", "bar"))
    assert r["status"] == "error"
    assert "Text not found" in r["message"]
    assert "view_file" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_multiple_matches_rejected(workspace):
    """匹配语义：多匹配：验证多匹配未开 replace_all 拒绝。

    "foo" 在文件中出现 3 次且 replace_all=False：
    - 返回 error，message 含出现次数与 "replace_all=True" 提示
    """
    make_text_file(workspace, "a.py", "foo foo foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "error"
    assert "3 occurrences" in r["message"]
    assert "replace_all=True" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_replace_all(workspace):
    """匹配语义：replace_all：验证全量替换且 diff.count 为实际次数。

    "foo" 出现 3 次，replace_all=True：
    - 全部替换为 "bar"，diff.count == 3
    """
    fp = make_text_file(workspace, "a.py", "foo foo foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar", replace_all=True))
    assert r["status"] == "ok"
    assert r["diff"]["count"] == 3
    assert fp.read_text(encoding="utf-8") == "bar bar bar\n"


@pytest.mark.asyncio
async def test_str_replace_replace_all_single(workspace):
    """匹配语义：replace_all 单次：验证单次匹配也标记 ALL。

    "foo" 出现 1 次，replace_all=True：
    - 替换成功，message 以 [REPLACED ALL] 开头，diff.count == 1
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar", replace_all=True))
    assert r["status"] == "ok"
    assert r["message"].startswith("[REPLACED ALL]")
    assert r["diff"]["count"] == 1


@pytest.mark.asyncio
async def test_str_replace_unchanged_identical(workspace):
    """匹配语义：UNCHANGED：验证 old_str == new_str 返回 UNCHANGED。

    old 与 new 相同无需任何操作：
    - 返回 ok，message 以 [UNCHANGED] 开头，携带 path 与同结构 diff
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "foo"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[UNCHANGED]")
    assert r["path"] == str(workspace.resolve() / "a.py")
    assert r["diff"] == {"old": "foo", "new": "foo", "count": 1, "replace_all": False}


@pytest.mark.asyncio
async def test_str_replace_unchanged_multiple_matches(workspace):
    """匹配语义：UNCHANGED 优先级：验证其优先于多匹配检查。

    "foo" 出现 2 次且 old == new：
    - 不触发多匹配报错，返回 UNCHANGED，diff.count 保留实际次数 2
    """
    make_text_file(workspace, "a.py", "foo foo\n")
    r = read_json(await str_replace("a.py", "foo", "foo"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[UNCHANGED]")
    assert r["diff"]["count"] == 2


@pytest.mark.asyncio
async def test_str_replace_case_sensitive(workspace):
    """匹配语义：大小写：验证匹配区分大小写。

    "Foo" 与文件内容 "foo" 不匹配（count 区分大小写）：
    - 返回 error（Text not found）
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "Foo", "bar"))
    assert r["status"] == "error"
    assert "Text not found" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_multiline_old_str(workspace):
    """匹配语义：跨行：验证跨行精确匹配。

    old_str "bar\nfoo" 跨两行：
    - 精确匹配整段文本并替换为 "X"
    """
    fp = make_text_file(workspace, "a.py", "aaa\nbar\nfoo\nbbb\n")
    r = read_json(await str_replace("a.py", "bar\nfoo", "X"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "aaa\nX\nbbb\n"


@pytest.mark.asyncio
async def test_str_replace_unicode(workspace):
    """匹配语义：中文：验证中文内容替换。

    "你好世界" 中替换 "你好" 为 "再见"：
    - utf-8 下精确匹配，内容变为 "再见世界\n"
    """
    fp = make_text_file(workspace, "a.py", "你好世界\n")
    r = read_json(await str_replace("a.py", "你好", "再见"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "再见世界\n"


@pytest.mark.asyncio
async def test_str_replace_digit_text(workspace):
    """匹配语义：数字文本：验证字符串形式的数字可替换。

    "42" 以字符串形式出现（非数字类型参数）：
    - 精确匹配并替换为 "43"
    """
    fp = make_text_file(workspace, "a.py", "version = 42\n")
    r = read_json(await str_replace("a.py", "42", "43"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "version = 43\n"


@pytest.mark.asyncio
async def test_str_replace_diff_count_single(workspace):
    """替换语义：diff.count：验证 replace_all=False 时固定为 1。

    单次替换（replace_all 默认 False）：
    - diff.count == 1，diff.replace_all is False
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert r["diff"]["count"] == 1
    assert r["diff"]["replace_all"] is False


@pytest.mark.asyncio
async def test_str_replace_new_str_with_newlines(workspace):
    """替换语义：多行 new_str：验证含换行内容写入多行。

    new_str "foo\nbar"：
    - 替换后文件内容为 "foo\nbar\n"（new_str 原样写入）
    """
    fp = make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "foo\nbar"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "foo\nbar\n"


@pytest.mark.asyncio
async def test_str_replace_surrounding_preserved(workspace):
    """替换语义：前后文：验证替换不破坏周围内容。

    "aaa foo bbb\n" 替换 "foo" 为 "X"：
    - 仅替换目标文本，前后文 "aaa " 与 " bbb" 原样保留
    """
    fp = make_text_file(workspace, "a.py", "aaa foo bbb\n")
    r = read_json(await str_replace("a.py", "foo", "X"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "aaa X bbb\n"


@pytest.mark.asyncio
async def test_str_replace_delete_content(workspace):
    """替换语义：删除：验证删除语义的文件内容。

    new_str 为空串等价于删除 old_str：
    - "foo bar baz" 删除 "bar " 后剩余 "foo baz\n"
    """
    fp = make_text_file(workspace, "a.py", "foo bar baz\n")
    r = read_json(await str_replace("a.py", "bar ", ""))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "foo baz\n"


@pytest.mark.asyncio
async def test_str_replace_diff_truncation(workspace):
    """替换语义：diff 截断：验证超长 old/new 截断加标记、短文本原样。

    60 字符文本超过 MAX_DIFF_SIZE（50）：
    - diff.old / diff.new 截断为前 50 字符 + "\n... [truncated]"
    - 短文本（"y\n"）原样返回
    """
    long_old = "x" * 60
    long_new = "y" * 60
    fp = make_text_file(workspace, "b.py", long_old + "\n")
    r = read_json(await str_replace("b.py", long_old, long_new))
    assert r["status"] == "ok"
    assert r["diff"]["old"] == "x" * 50 + "\n... [truncated]"
    assert r["diff"]["new"] == "y" * 50 + "\n... [truncated]"
    assert fp.read_text(encoding="utf-8") == long_new + "\n"
    r = read_json(await str_replace("b.py", "y\n", "zz\n"))
    assert r["diff"]["old"] == "y\n"
    assert r["diff"]["new"] == "zz\n"


@pytest.mark.asyncio
async def test_str_replace_permissions_preserved(workspace):
    """原子写：权限保留：验证替换后文件权限不变。

    chmod 0o640 后执行替换：
    - 临时文件写入后 chmod 恢复原权限，替换后 st_mode 仍为 0o640
    """
    fp = make_text_file(workspace, "a.py", "foo\n")
    os.chmod(fp, 0o640)
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert os.stat(fp).st_mode & 0o777 == 0o640


@pytest.mark.asyncio
async def test_str_replace_no_temp_left(workspace):
    """原子写：无残留：验证替换后无临时文件残留。

    mkstemp 临时文件在 finally 中清理：
    - 替换成功后目录仅剩目标文件
    """
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.py"]


@pytest.mark.asyncio
async def test_str_replace_inode_replaced(workspace):
    """原子写：inode：验证 os.replace 换 inode 的原子替换。

    替换前后 st_ino 不同：
    - 证明新内容写入临时文件后整体换名，非原地改写
    """
    fp = make_text_file(workspace, "a.py", "foo\n")
    ino_before = os.stat(fp).st_ino
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert os.stat(fp).st_ino != ino_before


@pytest.mark.asyncio
async def test_str_replace_encoding_failure_atomic(workspace):
    """原子写：编码失败原子性：验证失败时原文件内容不变。

    ascii 编码无法写入中文 new_str（UnicodeEncodeError）：
    - 返回 error 且原文件内容保持不变（os.replace 未执行）
    """
    fp = make_text_file(workspace, "a.py", "foo bar\n")
    r = read_json(await str_replace("a.py", "foo", "你好", encoding="ascii"))
    assert r["status"] == "error"
    assert "not encodable as ascii" in r["message"]
    assert fp.read_text(encoding="utf-8") == "foo bar\n"


@pytest.mark.asyncio
async def test_str_replace_readonly_dir_graceful(workspace):
    """原子写：目录只读：验证 mkstemp 失败优雅返回 error（不裸炸）。

    chmod 目录 0o555 后 mkstemp 抛 PermissionError：
    - 已纳入异常兜底，返回 error（Cannot write to），无临时文件残留
    - finally 恢复目录 0o755
    """
    fp = make_text_file(workspace, "a.py", "foo\n")
    os.chmod(workspace, 0o555)
    try:
        r = read_json(await str_replace("a.py", "foo", "bar"))
        assert r["status"] == "error"
        assert "Cannot write to" in r["message"]
    finally:
        os.chmod(workspace, 0o755)
    assert fp.read_text(encoding="utf-8") == "foo\n"


@pytest.mark.asyncio
async def test_str_replace_success_contract(workspace):
    """响应契约：ok 分支：验证字段完整。

    ok 响应固定四字段：
    - status / message / path / diff，diff 固定四子字段 old / new / count / replace_all
    """
    make_text_file(workspace, "a.py", "foo bar\n")
    r = read_json(await str_replace("a.py", "foo", "X"))
    assert set(r.keys()) == {"status", "message", "path", "diff"}
    assert r["status"] == "ok"
    assert set(r["diff"].keys()) == {"old", "new", "count", "replace_all"}


@pytest.mark.parametrize("scenario", ["not_found", "traversal", "nonexistent"])
@pytest.mark.asyncio
async def test_str_replace_error_contract(workspace, scenario):
    """响应契约：error 分支：参数化验证三类 error 只有 status/message 两字段。

    覆盖未命中 / 越界 / 不存在三类错误：
    - 统一返回 {status, message}，不含 path / diff
    """
    make_text_file(workspace, "a.py", "foo\n")
    if scenario == "not_found":
        r = read_json(await str_replace("a.py", "zzz", "bar"))
    elif scenario == "traversal":
        r = read_json(await str_replace("../x.py", "foo", "bar"))
    else:
        r = read_json(await str_replace("missing.py", "foo", "bar"))
    assert set(r.keys()) == {"status", "message"}
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_str_replace_empty_file(workspace):
    """边界：空文件：验证空文件替换报 not found。

    文件内容为空，任何非空 old_str 都 count == 0：
    - 返回 error（Text not found）
    """
    make_text_file(workspace, "a.py", "")
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "error"
    assert "Text not found" in r["message"]
