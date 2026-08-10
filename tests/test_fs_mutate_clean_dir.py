"""clean_dir 全方面测试：参数校验、路径安全、symlink 语义、收集/删除语义与响应契约。

测试项目：
- test_clean_dir_invalid_dir_path:                   参数化验证空/空白/非字符串 dir_path 拒绝
- test_clean_dir_invalid_patterns_type:              参数化验证非列表 patterns 拒绝（数字/字符串）
- test_clean_dir_invalid_patterns_element:           参数化验证 patterns 含非字符串元素拒绝
- test_clean_dir_empty_patterns_list_means_recursive: 验证 patterns=[] 与 None 同义（递归删除）
- test_clean_dir_workspace_not_configured:           验证工作区未配置时 RuntimeError
- test_clean_dir_relative_path:                      验证相对路径解析为工作区内路径
- test_clean_dir_absolute_path:                      验证工作区内绝对路径与相对路径等价
- test_clean_dir_home_expansion:                     验证 ~ 展开为 HOME 下路径
- test_clean_dir_traversal_denied:                   验证 ../ 跳出工作区被拦截
- test_clean_dir_absolute_outside_denied:            验证工作区外绝对路径被拦截
- test_clean_dir_prefix_trap_denied:                 验证同名前缀兄弟目录被拦截
- test_clean_dir_root_protection:                    参数化验证三种形态工作区根拒绝删除
- test_clean_dir_not_exists:                         验证不存在路径拒绝
- test_clean_dir_link_to_outside_file:               验证链接指向外部文件删链接本身
- test_clean_dir_link_to_inside_file:                验证链接指向区内文件删链接本身
- test_clean_dir_link_to_outside_dir:                验证链接指向外部目录删链接本身
- test_clean_dir_link_to_inside_dir:                 验证链接指向区内目录删链接本身
- test_clean_dir_link_to_workspace_root:             验证链接指向工作区根删链接不触发根保护
- test_clean_dir_walk_matched_symlink_file:          验证 walk 收集的链接文件 unlink 链接
- test_clean_dir_walk_matched_symlink_dir:           验证 walk 收集的链接目录 unlink 链接
- test_clean_dir_file_target:                        验证文件目标删除（deleted 相对根）
- test_clean_dir_file_target_ignores_patterns:       验证文件目标忽略 patterns
- test_clean_dir_recursive_delete_dir:               验证 patterns=None 递归删除目录整体
- test_clean_dir_recursive_empty_dir:                验证空目录递归删除
- test_clean_dir_recursive_deep_nested:              验证深层嵌套目录递归删除
- test_clean_dir_dot_relative_path:                  验证 "./sub" 前缀形态
- test_clean_dir_trailing_slash_path:                验证 "sub/" 尾斜杠形态
- test_clean_dir_pattern_star_deletes_all:           验证 "*" 匹配目录+文件并剪枝
- test_clean_dir_pattern_match_files_recursive:      验证 patterns 嵌套递归匹配文件
- test_clean_dir_pattern_match_dir_whole:            验证匹配目录整目录删除
- test_clean_dir_pattern_match_dir_pruned:           验证匹配目录剪枝不下钻、兄弟保留
- test_clean_dir_pattern_no_match:                   验证无匹配返回 Nothing matched
- test_clean_dir_pattern_match_hidden:               验证隐藏文件参与匹配
- test_clean_dir_multiple_patterns:                  验证多模式并集匹配
- test_clean_dir_pattern_case_sensitive:             验证 fnmatch 大小写敏感
- test_clean_dir_pattern_wildcard_specific:          验证 "?" 单字符通配
- test_clean_dir_empty_pattern_element:              验证空字符串模式无匹配
- test_clean_dir_scan_error_on_unreadable_subdir:    验证子目录不可读扫描转 error
- test_clean_dir_partial_failure_contract:           验证部分失败 error 携带删除进度
- test_clean_dir_delete_readonly_file_ok:            验证只读文件可删（unlink 仅需目录权限）
- test_clean_dir_delete_readonly_dir_error:          验证只读目录删除失败优雅报错
- test_clean_dir_exceeds_limit:                      验证 CLEAN_MAX_ITEMS 超限预检不动手
- test_clean_dir_at_limit:                           验证恰好等于 CLEAN_MAX_ITEMS 放行
- test_clean_dir_success_contract:                   验证 ok 响应字段契约与 [DELETED] 前缀
- test_clean_dir_nothing_matched_contract:           验证无匹配 ok 响应字段契约
- test_clean_dir_error_contract:                     参数化验证纯校验 error 只有 status/message
- test_clean_dir_clean_lock_singleton:               验证 _clean_lock 模块级单例
- test_clean_dir_uses_shared_file_lock:              验证删除路径接入共享文件锁（spy）
- test_clean_dir_no_temp_leftover:                   验证文件/目录删除均无 .clean_tmp_ 残留
- test_clean_dir_delete_then_str_replace_error:      验证删除后写工具优雅报错（锁互斥效果）
- test_clean_dir_only_matches_deleted:               验证只删匹配项、未匹配文件字节级完好
- test_clean_dir_recursive_keeps_siblings:           验证递归删除不动兄弟目录

覆盖场景：
- 参数校验：dir_path 空/空白/非字符串拒绝；patterns 类型与元素校验（字符串被按字符
  迭代的静默不匹配陷阱、数字裸炸陷阱）；空列表与 None 同义（递归删除）；workspace 未配置抛错
- 路径安全：相对/绝对/~/./尾斜杠五类合法形态；../ 与系统绝对路径与同名前缀兄弟目录
  越界拒绝；根保护覆盖 "." / 绝对根 / "sub/.." 词法折叠三形态（防 rm -rf 工作区根）
- symlink 语义：指向工作区内/外文件与目录的链接一律删链接本身（外部目标完好、
  链接指向根不触发根保护）；walk 收集的链接文件/目录 unlink 而非 rmtree（防删真实目标）
- 删除语义：文件目标忽略 patterns；patterns=None/[] 递归删目录（空目录/深层嵌套）；
  patterns 按 basename glob 匹配（嵌套递归收集、匹配目录整删并剪枝不下钻）
- 收集细节：隐藏文件匹配、多模式并集、大小写敏感、? 单字符通配、空模式元素无匹配
- 错误路径：扫描阶段子目录不可读转 error（onerror 不静默漏删）；删除阶段部分失败
  error 携带 deleted/count 进度（不可回滚）；只读文件可删（unlink 仅需目录写权限）；
  只读目录删除失败优雅报错
- 上限：CLEAN_MAX_ITEMS 超限预检在动手前（全部未删）、恰好等于放行（边界）
- 响应契约：ok 分支固定字段（status/message/deleted/count + [DELETED] 前缀）、
  无匹配 ok（Nothing matched + 空列表）、纯校验 error 仅 status/message
  （部分失败 error 额外携带进度字段，属例外契约）
- 锁与原子：_clean_lock 模块级单例、删除路径接入共享文件锁（spy 验证，并发测试前置）、
  目录 rename 隔离删除无 .clean_tmp_ 残留、删除后写工具优雅报错
- 副作用：只删匹配项、未匹配文件字节级完好、递归删除不动兄弟目录

使用注意：
- 项目为 pytest-asyncio strict 模式：所有异步测试必须显式 @pytest.mark.asyncio
- 权限类用例（chmod 000/0555/0444）结束后恢复权限（带存在性保护，删除后不误 chmod），
  避免影响 tmp 清理与后续用例
- 上限用例通过 monkeypatch _fs_mutate.CLEAN_MAX_ITEMS 隔离，不构造真实 500 项
- 路径断言统一用 workspace.resolve()（realpath 归一化，防 macOS /var → /private/var 符号链接差异）
- 工作区外目标用 workspace.parent 或 tempfile.mkdtemp() 构造（不落在工作区内）
- 部分失败用例的 rename 隔离会残留 .clean_tmp_ 目录（rmtree 失败尽力清理），
  由 pytest 临时目录回收，不作断言
- 依赖 conftest.py 的 workspace fixture 与 tests/helpers.py 的 make_text_file / read_json

测试用例数量：64
"""

import os
import tempfile

import pytest

from core.tools._kernel import _fs_mutate
from core.tools._kernel._fs_mutate import clean_dir, str_replace
from tests.helpers import make_text_file, read_json
from utils.settings import settings


@pytest.mark.parametrize("bad_path", ["", "   ", None, 123, ["a.py"]])
@pytest.mark.asyncio
async def test_clean_dir_invalid_dir_path(workspace, bad_path):
    """参数校验：dir_path：验证空/空白/非字符串 dir_path 拒绝。

    参数化覆盖 "" / "   " / None / 123 / ["a.py"] 五类非法输入：
    - 统一返回 error，message 固定为 "dir_path must be a non-empty string."
    """
    r = read_json(await clean_dir(bad_path))
    assert r["status"] == "error"
    assert r["message"] == "dir_path must be a non-empty string."


@pytest.mark.parametrize("bad_patterns", [123, "*.py"])
@pytest.mark.asyncio
async def test_clean_dir_invalid_patterns_type(workspace, bad_patterns):
    """参数校验：patterns 类型：验证非列表 patterns 拒绝。

    参数化覆盖 123 / "*.py"：
    - 数字会在迭代处 TypeError 裸炸、字符串会被按字符迭代而静默不匹配，
      统一拦截返回 error（patterns must be a list of strings or None）
    """
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir("sub", bad_patterns))
    assert r["status"] == "error"
    assert r["message"] == "patterns must be a list of strings or None."
    assert (workspace / "sub/a.py").exists()


@pytest.mark.parametrize("bad_patterns", [[123], [None], ["ok.py", 1]])
@pytest.mark.asyncio
async def test_clean_dir_invalid_patterns_element(workspace, bad_patterns):
    """参数校验：patterns 元素：验证含非字符串元素的列表拒绝。

    参数化覆盖 [123] / [None] / ["ok.py", 1]：
    - fnmatch 对非字符串模式会 TypeError 裸炸，元素级校验统一拦截
    """
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir("sub", bad_patterns))
    assert r["status"] == "error"
    assert r["message"] == "patterns must be a list of strings or None."


@pytest.mark.asyncio
async def test_clean_dir_empty_patterns_list_means_recursive(workspace):
    """参数校验：patterns=[]：验证空列表与 None 同义（递归删除）。

    patterns=[] 不匹配任何模式但语义与 None 一致：
    - 递归删除 dir_path 整体，返回 [DELETED] 1 item(s)
    """
    make_text_file(workspace, "sub/a.py", "x")
    make_text_file(workspace, "sub/nested/b.py", "y")
    r = read_json(await clean_dir("sub", []))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["sub"]
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_workspace_not_configured(workspace, monkeypatch):
    """环境：workspace 未配置：验证抛 RuntimeError（配置缺失属程序错误）。

    workspace_dir 为空时工具无法确定安全边界：
    - 直接 raise 而非返回 JSON，调用方应保证配置就绪
    """
    monkeypatch.setattr(settings, "workspace_dir", None)
    with pytest.raises(RuntimeError, match="WORKSPACE_DIR is not configured"):
        await clean_dir("a.py")


@pytest.mark.asyncio
async def test_clean_dir_relative_path(workspace):
    """路径解析：相对路径：验证相对路径解析为工作区内路径。

    "sub/a.py" 相对工作区根：
    - 正常删除，deleted 为相对工作区根的路径
    """
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir("sub/a.py"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["sub/a.py"]
    assert not (workspace / "sub/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_absolute_path(workspace):
    """路径解析：绝对路径：验证工作区内绝对路径与相对路径等价。

    传 workspace 内绝对路径：
    - 正常删除，结果与相对路径一致
    """
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir(str(workspace / "sub/a.py")))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "sub/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_home_expansion(workspace, monkeypatch):
    """路径解析：~ 展开：验证 ~ 展开为 HOME 下路径。

    monkeypatch HOME 指向工作区后传入 "~/sub"：
    - expanduser 展开为工作区内路径，正常删除
    """
    make_text_file(workspace, "sub/a.py", "x")
    monkeypatch.setenv("HOME", str(workspace))
    r = read_json(await clean_dir("~/sub"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_traversal_denied(workspace):
    """路径安全：../ 越界：验证 ../ 跳出工作区被拦截。

    "../escape" 词法折叠后落在工作区外：
    - 越界检查拦截（先于存在性检查），返回 error（is denied）
    """
    r = read_json(await clean_dir("../escape"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_clean_dir_absolute_outside_denied(workspace):
    """路径安全：绝对越界：验证工作区外绝对路径被拦截。

    独立创建的外部目录绝对路径：
    - 前缀检查拦截，返回 error（is denied），外部目录完好
    """
    outside = tempfile.mkdtemp()
    r = read_json(await clean_dir(outside))
    assert r["status"] == "error"
    assert "is denied" in r["message"]
    assert os.path.isdir(outside)


@pytest.mark.asyncio
async def test_clean_dir_prefix_trap_denied(workspace, monkeypatch):
    """路径安全：前缀陷阱：验证同名前缀兄弟目录被拦截。

    工作区重设为 proj，兄弟目录 proj_evil 是 proj 的前缀延伸：
    - startswith(safe_root + os.sep) 边界检查拦截，proj_evil 完好
    """
    proj = workspace / "proj"
    evil = workspace / "proj_evil"
    proj.mkdir()
    evil.mkdir()
    make_text_file(proj, "a.py", "x")
    make_text_file(evil, "secret.txt", "s")
    monkeypatch.setattr(settings, "workspace_dir", str(proj))
    r = read_json(await clean_dir(str(evil)))
    assert r["status"] == "error"
    assert "is denied" in r["message"]
    assert (evil / "secret.txt").exists()


@pytest.mark.parametrize("root_path", [".", "<root>", "sub/.."])
@pytest.mark.asyncio
async def test_clean_dir_root_protection(workspace, root_path):
    """路径安全：根保护：验证三种形态的工作区根都拒绝删除。

    参数化覆盖 "." / 工作区绝对路径 / "sub/.."（词法折叠回根）：
    - 统一返回 error（Refusing to delete the workspace root），防 rm -rf 根
    """
    if root_path == "<root>":
        root_path = str(workspace.resolve())
    r = read_json(await clean_dir(root_path))
    assert r["status"] == "error"
    assert "workspace root" in r["message"]


@pytest.mark.asyncio
async def test_clean_dir_not_exists(workspace):
    """路径安全：不存在：验证目标路径不存在拒绝。

    "missing" 在工作区内但不存在：
    - 返回 error（does not exist），不会误报删除成功
    """
    r = read_json(await clean_dir("missing"))
    assert r["status"] == "error"
    assert "does not exist" in r["message"]


@pytest.mark.asyncio
async def test_clean_dir_link_to_outside_file(workspace):
    """symlink 语义：外部文件：验证链接指向工作区外文件时删链接本身。

    区内 link.txt → 区外 outside.txt：
    - islink 特判先于 realpath（否则越界检查会提前拦截），删链接本身
    - 外部目标完好
    """
    outside = workspace.parent / "outside_target.txt"
    outside.write_text("secret\n", encoding="utf-8")
    link = workspace / "link.txt"
    link.symlink_to(outside)
    r = read_json(await clean_dir("link.txt"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not os.path.lexists(link)
    assert outside.read_text(encoding="utf-8") == "secret\n"


@pytest.mark.asyncio
async def test_clean_dir_link_to_inside_file(workspace):
    """symlink 语义：内部文件：验证链接指向工作区内文件时删链接本身。

    区内 link.txt → 区内 real.txt：
    - 删除链接本身，真实目标文件保留
    """
    make_text_file(workspace, "real.txt", "data")
    link = workspace / "link.txt"
    link.symlink_to(workspace / "real.txt")
    r = read_json(await clean_dir("link.txt"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not os.path.lexists(link)
    assert (workspace / "real.txt").read_text(encoding="utf-8") == "data"


@pytest.mark.asyncio
async def test_clean_dir_link_to_outside_dir(workspace):
    """symlink 语义：外部目录：验证链接指向工作区外目录时删链接本身。

    区内 linkdir → 区外目录（含 inner.txt）：
    - 删链接本身而非 rmtree 真实目录，外部目录及内容完好
    """
    outside = tempfile.mkdtemp()
    with open(os.path.join(outside, "inner.txt"), "w", encoding="utf-8") as f:
        f.write("keep")
    link = workspace / "linkdir"
    link.symlink_to(outside, target_is_directory=True)
    r = read_json(await clean_dir("linkdir"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not os.path.lexists(link)
    assert os.path.exists(os.path.join(outside, "inner.txt"))


@pytest.mark.asyncio
async def test_clean_dir_link_to_inside_dir(workspace):
    """symlink 语义：内部目录：验证链接指向工作区内目录时删链接本身。

    区内 linkdir → 区内 target_dir：
    - 删链接本身，真实目录及内容保留
    """
    make_text_file(workspace, "target_dir/inner.txt", "x")
    link = workspace / "linkdir"
    link.symlink_to(workspace / "target_dir", target_is_directory=True)
    r = read_json(await clean_dir("linkdir"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not os.path.lexists(link)
    assert (workspace / "target_dir/inner.txt").exists()


@pytest.mark.asyncio
async def test_clean_dir_link_to_workspace_root(workspace):
    """symlink 语义：链接指向根：验证删链接不触发根保护。

    区内 root_link → 工作区根：
    - islink 分支按词法检查（链接路径非根），删除链接本身而非拒绝
    """
    link = workspace / "root_link"
    link.symlink_to(workspace, target_is_directory=True)
    r = read_json(await clean_dir("root_link"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not os.path.lexists(link)
    assert workspace.exists()


@pytest.mark.asyncio
async def test_clean_dir_walk_matched_symlink_file(workspace):
    """symlink 语义：walk 链接文件：验证收集的链接文件 unlink 链接本身。

    sub/match.txt → 区外 real.txt，patterns 匹配 match.txt：
    - 删除阶段 islink 判断走 unlink 而非 rmtree，外部目标完好
    """
    outside = workspace.parent / "outside_real.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (workspace / "sub").mkdir()
    link = workspace / "sub" / "match.txt"
    link.symlink_to(outside)
    r = read_json(await clean_dir("sub", ["*.txt"]))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["sub/match.txt"]
    assert not os.path.lexists(link)
    assert outside.read_text(encoding="utf-8") == "secret\n"


@pytest.mark.asyncio
async def test_clean_dir_walk_matched_symlink_dir(workspace):
    """symlink 语义：walk 链接目录：验证收集的链接目录 unlink 链接本身。

    sub/linked → 区内 real_dir，patterns 匹配 linked：
    - 目录匹配进 to_delete 并剪枝，删除阶段 islink 走 unlink
    - 真实目录及内容保留
    """
    make_text_file(workspace, "real_dir/inner.txt", "x")
    (workspace / "sub").mkdir()
    link = workspace / "sub" / "linked"
    link.symlink_to(workspace / "real_dir", target_is_directory=True)
    r = read_json(await clean_dir("sub", ["linked"]))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["sub/linked"]
    assert not os.path.lexists(link)
    assert (workspace / "real_dir/inner.txt").exists()


@pytest.mark.asyncio
async def test_clean_dir_file_target(workspace):
    """删除语义：文件目标：验证删除单个文件。

    目标为文件：
    - [DELETED] 1 item(s)，deleted 为相对工作区根的路径
    """
    make_text_file(workspace, "a.txt", "x")
    r = read_json(await clean_dir("a.txt"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["a.txt"]
    assert not (workspace / "a.txt").exists()


@pytest.mark.asyncio
async def test_clean_dir_file_target_ignores_patterns(workspace):
    """删除语义：文件目标忽略 patterns：验证文件目标不受模式限制。

    目标为文件且 patterns 不匹配该文件：
    - isfile 分支直接删除目标，patterns 不参与
    """
    make_text_file(workspace, "a.txt", "x")
    r = read_json(await clean_dir("a.txt", ["*.py"]))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "a.txt").exists()


@pytest.mark.asyncio
async def test_clean_dir_recursive_delete_dir(workspace):
    """删除语义：递归删除：验证 patterns=None 删除目录整体。

    目录含嵌套子目录与文件：
    - 只删 dir_path 自身一项（rename 隔离 + rmtree），deleted 为 ["sub"]
    """
    make_text_file(workspace, "sub/a.py", "x")
    make_text_file(workspace, "sub/nested/b.md", "y")
    r = read_json(await clean_dir("sub"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["sub"]
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_recursive_empty_dir(workspace):
    """删除语义：空目录：验证空目录递归删除。

    目标为空目录：
    - 正常删除（rename + rmtree 空目录）
    """
    (workspace / "sub").mkdir()
    r = read_json(await clean_dir("sub"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_recursive_deep_nested(workspace):
    """删除语义：深层嵌套：验证深层目录递归删除。

    目标含 5 层嵌套：
    - 整体递归删除，仅删 dir_path 一项
    """
    make_text_file(workspace, "a/b/c/d/e.py", "x")
    r = read_json(await clean_dir("a"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "a").exists()


@pytest.mark.asyncio
async def test_clean_dir_dot_relative_path(workspace):
    """路径解析："./" 前缀：验证相对前缀形态正常解析。

    "./sub" 词法归一化后为 "sub"：
    - 正常删除（normpath 折叠 "."）
    """
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir("./sub"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_trailing_slash_path(workspace):
    """路径解析：尾斜杠：验证 "sub/" 形态正常解析。

    "sub/" 词法归一化后为 "sub"：
    - 正常删除（normpath 去尾斜杠）
    """
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir("sub/"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_star_deletes_all(workspace):
    """收集语义：通配全部：验证 "*" 匹配目录与文件并整删。

    "*" 匹配 proj 下全部条目：
    - 文件 a.py / b.txt 与目录 sub（含 c.py，剪枝不下钻）全部收集
    - count == 3，删除后 proj 为空目录保留
    """
    make_text_file(workspace, "proj/a.py", "x")
    make_text_file(workspace, "proj/b.txt", "y")
    make_text_file(workspace, "proj/sub/c.py", "z")
    r = read_json(await clean_dir("proj", ["*"]))
    assert r["status"] == "ok"
    assert r["count"] == 3
    assert sorted(r["deleted"]) == ["proj/a.py", "proj/b.txt", "proj/sub"]
    assert sorted(p.name for p in (workspace / "proj").iterdir()) == []


@pytest.mark.asyncio
async def test_clean_dir_pattern_match_files_recursive(workspace):
    """收集语义：嵌套匹配：验证 patterns 递归收集匹配文件。

    "*.py" 匹配三层嵌套中的全部 py 文件：
    - count == 3，deleted 排序稳定（to_delete.sort()）
    - 未匹配文件保留
    """
    make_text_file(workspace, "proj/a.py", "x")
    make_text_file(workspace, "proj/sub/b.py", "y")
    make_text_file(workspace, "proj/sub/nested/c.py", "z")
    make_text_file(workspace, "proj/keep.txt", "k")
    r = read_json(await clean_dir("proj", ["*.py"]))
    assert r["status"] == "ok"
    assert r["count"] == 3
    assert r["deleted"] == [
        "proj/a.py", "proj/sub/b.py", "proj/sub/nested/c.py",
    ]
    assert (workspace / "proj/keep.txt").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_match_dir_whole(workspace):
    """收集语义：目录整删：验证匹配目录整目录删除。

    patterns 匹配目录名 sub：
    - 整目录删除（含内部不匹配的 keep.txt），count == 1
    """
    make_text_file(workspace, "proj/sub/a.py", "x")
    make_text_file(workspace, "proj/sub/keep.txt", "y")
    r = read_json(await clean_dir("proj", ["sub"]))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["proj/sub"]
    assert not (workspace / "proj/sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_match_dir_pruned(workspace):
    """收集语义：目录剪枝：验证匹配目录不下钻、兄弟文件正常收集。

    "*.txt" 匹配文件 keep.txt 但不匹配目录 sub：
    - 仅删 keep.txt；sub 目录不匹配则正常下钻（a.py 不匹配保留）
    """
    make_text_file(workspace, "proj/sub/a.py", "x")
    make_text_file(workspace, "proj/sub/keep.txt", "y")
    r = read_json(await clean_dir("proj", ["*.txt"]))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["proj/sub/keep.txt"]
    assert (workspace / "proj/sub/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_no_match(workspace):
    """收集语义：无匹配：验证无匹配文件时返回 Nothing matched。

    "*.zzz" 无任何匹配：
    - ok 响应（Nothing matched），count == 0，deleted 为空，目标未动
    """
    make_text_file(workspace, "proj/a.py", "x")
    r = read_json(await clean_dir("proj", ["*.zzz"]))
    assert r["status"] == "ok"
    assert "Nothing matched" in r["message"]
    assert r["count"] == 0
    assert r["deleted"] == []
    assert (workspace / "proj/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_match_hidden(workspace):
    """收集语义：隐藏文件：验证隐藏文件参与 basename 匹配。

    ".hidden.txt" 按名字匹配 "*.txt"：
    - 与可见文件一并删除（fnmatch 无隐藏文件豁免）
    """
    make_text_file(workspace, "proj/.hidden.txt", "x")
    make_text_file(workspace, "proj/visible.txt", "y")
    r = read_json(await clean_dir("proj", ["*.txt"]))
    assert r["status"] == "ok"
    assert r["count"] == 2
    assert not (workspace / "proj/.hidden.txt").exists()
    assert not (workspace / "proj/visible.txt").exists()


@pytest.mark.asyncio
async def test_clean_dir_multiple_patterns(workspace):
    """收集语义：多模式：验证多模式并集匹配。

    ["*.py", "*.md"] 取并集：
    - py 与 md 文件删除，txt 文件保留
    """
    make_text_file(workspace, "proj/a.py", "x")
    make_text_file(workspace, "proj/b.md", "y")
    make_text_file(workspace, "proj/c.txt", "z")
    r = read_json(await clean_dir("proj", ["*.py", "*.md"]))
    assert r["status"] == "ok"
    assert r["count"] == 2
    assert not (workspace / "proj/a.py").exists()
    assert not (workspace / "proj/b.md").exists()
    assert (workspace / "proj/c.txt").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_case_sensitive(workspace):
    """收集语义：大小写敏感：验证 fnmatch 匹配大小写敏感。

    "*.PY" 与 a.py 不同名：
    - 无匹配（Nothing matched），文件保留
    """
    make_text_file(workspace, "proj/a.py", "x")
    r = read_json(await clean_dir("proj", ["*.PY"]))
    assert r["status"] == "ok"
    assert r["count"] == 0
    assert (workspace / "proj/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_wildcard_specific(workspace):
    """收集语义：单字符通配：验证 "?" 精确匹配单字符。

    "a?.py" 匹配 a1.py 不匹配 a22.py：
    - 仅 a1.py 删除
    """
    make_text_file(workspace, "proj/a1.py", "x")
    make_text_file(workspace, "proj/a22.py", "y")
    make_text_file(workspace, "proj/b1.py", "z")
    r = read_json(await clean_dir("proj", ["a?.py"]))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "proj/a1.py").exists()
    assert (workspace / "proj/a22.py").exists()
    assert (workspace / "proj/b1.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_empty_pattern_element(workspace):
    """收集语义：空模式：验证空字符串模式无匹配。

    patterns=[""] 按 fnmatch 语义不匹配任何名字：
    - Nothing matched，文件保留
    """
    make_text_file(workspace, "proj/a.py", "x")
    r = read_json(await clean_dir("proj", [""]))
    assert r["status"] == "ok"
    assert r["count"] == 0
    assert (workspace / "proj/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_scan_error_on_unreadable_subdir(workspace):
    """错误路径：扫描权限：验证子目录不可读时扫描转 error。

    ro 目录 chmod 000 后 walk 扫不到：
    - onerror 显式 raise 转 error（Cannot scan），不静默漏删
    """
    make_text_file(workspace, "proj/ro/x.txt", "x")
    os.chmod(workspace / "proj/ro", 0o000)
    try:
        r = read_json(await clean_dir("proj", ["*.txt"]))
        assert r["status"] == "error"
        assert "Cannot scan" in r["message"]
    finally:
        os.chmod(workspace / "proj/ro", 0o755)


@pytest.mark.asyncio
async def test_clean_dir_partial_failure_contract(workspace):
    """错误路径：部分失败：验证删除中途失败返回已删进度。

    a.py 可删 + ro 目录（0555）rmtree 失败：
    - error 响应携带 deleted/count 进度（删除不可回滚）
    - 已删项在 deleted 列表、未删项不在
    """
    make_text_file(workspace, "proj/a.py", "x")
    make_text_file(workspace, "proj/ro/inner.txt", "y")
    os.chmod(workspace / "proj/ro", 0o555)
    try:
        r = read_json(await clean_dir("proj", ["*"]))
        assert r["status"] == "error"
        assert "Cannot delete" in r["message"]
        assert r["deleted"] == ["proj/a.py"]
        assert r["count"] == 1
        assert not (workspace / "proj/a.py").exists()
    finally:
        if (workspace / "proj/ro").exists():
            os.chmod(workspace / "proj/ro", 0o755)


@pytest.mark.asyncio
async def test_clean_dir_delete_readonly_file_ok(workspace):
    """错误路径：只读文件：验证只读文件可删除。

    chmod 0444 文件：
    - unlink 仅需目录写权限（POSIX），删除成功
    """
    make_text_file(workspace, "proj/a.txt", "x")
    os.chmod(workspace / "proj/a.txt", 0o444)
    try:
        r = read_json(await clean_dir("proj/a.txt"))
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert not (workspace / "proj/a.txt").exists()
    finally:
        if (workspace / "proj/a.txt").exists():
            os.chmod(workspace / "proj/a.txt", 0o644)


@pytest.mark.asyncio
async def test_clean_dir_delete_readonly_dir_error(workspace):
    """错误路径：只读目录：验证只读目录递归删除失败优雅报错。

    ro 目录 chmod 0555 后 rmtree 无法删除其中条目：
    - rename 隔离成功但 rmtree 失败，返回 error（Cannot delete），不裸炸
    """
    make_text_file(workspace, "proj/ro/inner.txt", "x")
    os.chmod(workspace / "proj/ro", 0o555)
    try:
        r = read_json(await clean_dir("proj/ro"))
        assert r["status"] == "error"
        assert "Cannot delete" in r["message"]
    finally:
        if (workspace / "proj/ro").exists():
            os.chmod(workspace / "proj/ro", 0o755)


@pytest.mark.asyncio
async def test_clean_dir_exceeds_limit(workspace, monkeypatch):
    """上限：超限：验证 CLEAN_MAX_ITEMS 预检在动手前（全部未删）。

    monkeypatch CLEAN_MAX_ITEMS=2，3 个匹配：
    - 收集后删除前拦截，返回 error（Would delete ... exceeding ...）
    - 无任何文件被删（预检在动手前）
    """
    make_text_file(workspace, "proj/a.py", "x")
    make_text_file(workspace, "proj/b.py", "y")
    make_text_file(workspace, "proj/sub/c.py", "z")
    monkeypatch.setattr(_fs_mutate, "CLEAN_MAX_ITEMS", 2)
    r = read_json(await clean_dir("proj", ["*.py"]))
    assert r["status"] == "error"
    assert "exceeding the 2 per-call limit" in r["message"]
    assert (workspace / "proj/a.py").exists()
    assert (workspace / "proj/b.py").exists()
    assert (workspace / "proj/sub/c.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_at_limit(workspace, monkeypatch):
    """上限：边界：验证恰好等于 CLEAN_MAX_ITEMS 放行。

    monkeypatch CLEAN_MAX_ITEMS=2，恰好 2 个匹配：
    - 超限判断是严格大于（>），恰好等于放行
    """
    make_text_file(workspace, "proj/a.py", "x")
    make_text_file(workspace, "proj/b.py", "y")
    monkeypatch.setattr(_fs_mutate, "CLEAN_MAX_ITEMS", 2)
    r = read_json(await clean_dir("proj", ["*.py"]))
    assert r["status"] == "ok"
    assert r["count"] == 2
    assert not (workspace / "proj/a.py").exists()
    assert not (workspace / "proj/b.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_success_contract(workspace):
    """响应契约：ok 分支：验证字段完整与 message 前缀格式。

    ok 响应固定四字段：
    - status / message / deleted / count
    - message 前缀 "[DELETED] N item(s)"，deleted 为相对工作区根路径
    """
    make_text_file(workspace, "proj/a.py", "x")
    r = read_json(await clean_dir("proj/a.py"))
    assert set(r.keys()) == {"status", "message", "deleted", "count"}
    assert r["status"] == "ok"
    assert r["message"] == "[DELETED] 1 item(s)"
    assert r["deleted"] == ["proj/a.py"]
    assert r["count"] == 1


@pytest.mark.asyncio
async def test_clean_dir_nothing_matched_contract(workspace):
    """响应契约：无匹配分支：验证 Nothing matched 字段完整。

    无匹配时同样走 ok 四字段：
    - message 为 "Nothing matched in '{dir_path}'."
    - deleted 空列表、count 为 0
    """
    make_text_file(workspace, "proj/a.py", "x")
    r = read_json(await clean_dir("proj", ["*.zzz"]))
    assert set(r.keys()) == {"status", "message", "deleted", "count"}
    assert r["status"] == "ok"
    assert r["message"] == "Nothing matched in 'proj'."
    assert r["deleted"] == []
    assert r["count"] == 0


@pytest.mark.parametrize("scenario", ["traversal", "missing", "root", "bad_param"])
@pytest.mark.asyncio
async def test_clean_dir_error_contract(workspace, scenario):
    """响应契约：error 分支：参数化验证四类纯校验 error 只有 status/message。

    覆盖越界 / 不存在 / 根保护 / 非法参数四类错误：
    - 统一返回 {status, message}，不含 deleted / count
    （部分失败 error 携带进度字段，见 partial_failure_contract）
    """
    if scenario == "traversal":
        r = read_json(await clean_dir("../x"))
    elif scenario == "missing":
        r = read_json(await clean_dir("missing"))
    elif scenario == "root":
        r = read_json(await clean_dir("."))
    else:
        r = read_json(await clean_dir(123))
    assert set(r.keys()) == {"status", "message"}
    assert r["status"] == "error"


def test_clean_dir_clean_lock_singleton():
    """锁：单例：验证 _clean_lock 是模块级唯一实例。

    clean_dir 全部删除操作经同一把全局锁串行：
    - 多次访问返回同一对象（并发互斥的前提）
    """
    assert _fs_mutate._clean_lock is _fs_mutate._clean_lock


@pytest.mark.asyncio
async def test_clean_dir_uses_shared_file_lock(workspace, monkeypatch):
    """锁：共享：验证删除路径接入与写工具相同的文件锁。

    spy 包装 _get_file_lock 记录调用：
    - 删除文件路径被请求锁（key 为 realpath 后绝对路径），
      与 str_replace / write_file 互斥的前提成立（并发测试前置）
    """
    make_text_file(workspace, "a.py", "x")
    called: list[str] = []
    original = _fs_mutate._get_file_lock

    def spy(path):
        called.append(path)
        return original(path)

    monkeypatch.setattr(_fs_mutate, "_get_file_lock", spy)
    r = read_json(await clean_dir("a.py"))
    assert r["status"] == "ok"
    assert str(workspace.resolve() / "a.py") in called


@pytest.mark.asyncio
async def test_clean_dir_no_temp_leftover(workspace):
    """锁与原子：无残留：验证文件与目录删除均无 .clean_tmp_ 残留。

    文件删除（unlink）与目录删除（rename 隔离）后：
    - 工作区内不存在任何 .clean_tmp_ 临时目录
    """
    make_text_file(workspace, "sub/a.py", "x")
    make_text_file(workspace, "sub/nested/b.py", "y")
    r = read_json(await clean_dir("sub", ["*.py"]))
    assert r["status"] == "ok"
    assert r["count"] == 2
    leftovers = [p.name for p in workspace.iterdir() if ".clean_tmp_" in p.name]
    assert leftovers == []
    make_text_file(workspace, "sub2/c.py", "z")
    r = read_json(await clean_dir("sub2"))
    assert r["status"] == "ok"
    leftovers = [p.name for p in workspace.iterdir() if ".clean_tmp_" in p.name]
    assert leftovers == []


@pytest.mark.asyncio
async def test_clean_dir_delete_then_str_replace_error(workspace):
    """锁互斥效果：删后替换：验证删除后写工具优雅报错。

    clean_dir 删除 s.py 后 str_replace 再操作：
    - 文件不存在，返回 error（does not exist），不裸炸
    - （文件锁互斥的可见结果：删除与写入不并发交错）
    """
    make_text_file(workspace, "s.py", "foo\n")
    r = read_json(await clean_dir("s.py"))
    assert r["status"] == "ok"
    r = read_json(await str_replace("s.py", "foo", "bar"))
    assert r["status"] == "error"
    assert "does not exist" in r["message"]


@pytest.mark.asyncio
async def test_clean_dir_only_matches_deleted(workspace):
    """副作用：精准删除：验证只删匹配项、未匹配文件字节级完好。

    patterns 删除 py/txt 后：
    - 未匹配的 md 文件内容字节级完好（含中文与特殊字符）
    """
    make_text_file(workspace, "proj/a.py", "x")
    make_text_file(workspace, "proj/b.txt", "y")
    content = "keep\n中文\n"
    make_text_file(workspace, "proj/keep.md", content)
    r = read_json(await clean_dir("proj", ["*.py", "*.txt"]))
    assert r["status"] == "ok"
    assert r["count"] == 2
    assert (workspace / "proj/keep.md").read_bytes() == content.encode("utf-8")


@pytest.mark.asyncio
async def test_clean_dir_recursive_keeps_siblings(workspace):
    """副作用：递归删除不动兄弟：验证目录递归删除不影响同级其他条目。

    删除 sub 后：
    - 工作区根的 keep.py 与 keep_dir 完好
    """
    make_text_file(workspace, "sub/a.py", "x")
    make_text_file(workspace, "keep.py", "keep")
    make_text_file(workspace, "keep_dir/b.txt", "y")
    r = read_json(await clean_dir("sub"))
    assert r["status"] == "ok"
    assert not (workspace / "sub").exists()
    assert (workspace / "keep.py").read_text(encoding="utf-8") == "keep"
    assert (workspace / "keep_dir/b.txt").exists()
