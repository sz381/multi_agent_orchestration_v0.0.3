"""glob_tool 匹配语义与边界场景测试。

测试项目：
- test_glob_star_py_matches_root:            验证单段 *.py 只匹配根下文件、不递归子目录
- test_glob_star_matches_all_root_entries:   验证 * 匹配根下全部条目（文件+目录+隐藏文件）
- test_glob_exact_path:                      验证多段精确模式 a/b.py 命中单个文件
- test_glob_multi_segment:                   验证深层精确路径 sub/nested/deep.py
- test_glob_dir_pattern:                     验证无通配模式可匹配目录自身
- test_question_mark_wildcard:               验证 ? 单字符通配匹配 x.py
- test_char_class_wildcard:                  验证 [hm] 字符类通配匹配 hello.py/main.py
- test_hidden_file_matched_by_star:          验证 fnmatch 语义下 * 匹配点开头隐藏文件
- test_double_star_all:                      验证裸 ** 匹配全部文件与目录（含根自身），每目录恰好一次
- test_double_star_py:                       验证 **/*.py 跨任意层匹配所有 .py
- test_double_star_txt:                      验证 **/*.txt 跨层匹配并返回全部层级结果
- test_double_star_note:                     验证 **/note.txt 按文件名跨层定位
- test_dir_double_star:                      验证 a/** 匹配 a 自身与内部全部条目
- test_double_star_zero_level:               验证 ** 零层语义（**/hello.py 匹配根下文件）
- test_excluded_dirs_not_returned:           验证排除目录既不返回也不进入（.venv/logs）
- test_excluded_files_filtered:              验证排除文件 .DS_Store 匹配到也被过滤
- test_dir_path_into_excluded_dir:           验证 dir_path 直指排除目录内部可正常搜索
- test_dir_path_subdir:                      验证 dir_path 指定子目录时只搜索该目录
- test_dir_path_absolute_inside:             验证工作区内绝对 dir_path 与相对路径等价
- test_dir_path_outside_denied:              验证 dir_path ../ 跳出工作区被拦截
- test_dir_path_absolute_outside_denied:     验证 dir_path /etc 等系统绝对路径被拦截
- test_dir_path_not_directory:               验证 dir_path 指向文件时拒绝
- test_dir_path_missing:                     验证 dir_path 不存在时拒绝
- test_allow_external_reads:                 验证 allow_external_reads 开关对外部目录放行/拦截
- test_symlink_dir_not_entered:              验证符号链接目录不跟随（防逃逸），自身可被匹配
- test_result_cap_truncated:                 验证 files 截断到 GLOB_MAX_RESULTS 且 count 保留总数
- test_scan_cap_truncated:                   验证 total 达 GLOB_MAX_SCAN 熔断停止扫描
- test_files_sorted:                         验证 files 按路径字典序升序返回
- test_absolute_paths_returned:              验证返回路径均为工作区内绝对路径
- test_empty_result:                         验证无匹配时 count=0/files 为空/truncated=False
- test_message_summary:                      验证 message 汇总匹配数量
- test_invalid_patterns:                     参数化验证空/空白/绝对/穿越模式均拒绝
- test_invalid_dir_path:                     参数化验证 dir_path 空/空白被拒绝

覆盖场景：
- 根下匹配：              *.py 只匹配根下文件，a/b.py 等子目录文件不出现
- 全条目匹配：            * 匹配根下文件+目录（含隐藏文件），排除规则仍生效
- 精确路径：              多段精确模式命中单个文件
- 目录匹配：              无通配模式可匹配目录自身
- ? 通配：                单字符通配精确匹配一个字符
- 字符类通配：            [seq] 匹配集合内字符开头
- 隐藏文件：              fnmatch 语义下 * 匹配点开头文件（与标准 glob 不匹配隐藏的差异锁定）
- 裸 **：                 匹配全部文件与目录（含根自身），每目录恰好一次无重复
- **/*.py：               跨任意层匹配所有 .py 文件
- ** 零层：               **/hello.py 中 ** 可视为不存在，直接匹配根下文件
- 目录+**：               a/** 匹配 a 自身与内部全部条目
- 排除目录：              .venv/logs 既不返回也不进入（内部文件不可见）
- 排除文件：              .DS_Store 匹配到也过滤（.DS_* 模式返回空）
- 排除目录直指：          dir_path 指向 .venv 内部时可正常搜索（Notes 语义）
- dir_path 子目录：       只搜索指定子目录
- dir_path 绝对路径：     工作区内绝对路径与相对路径等价
- 越界拒绝：              ../ 或 /etc 前缀检查拦截，先于目录存在性检查
- 非目录：                dir_path 指向文件或不存在路径报 is not a directory
- 外部放行：              allow_external_reads=True 可搜索工作区外目录
- 符号链接：              目录符号链接不跟随进入（防逃逸），自身作为普通条目可被匹配
- 结果上限：              files 截断到 GLOB_MAX_RESULTS（200），count 保留总匹配数
- 扫描熔断：              total 达 GLOB_MAX_SCAN（5000）停止扫描，truncated=True
- 排序：                  files 按路径字典序升序返回
- 绝对路径：              返回路径均为工作区内绝对路径（realpath 归一化）
- 空结果：                count=0、files=[]、truncated=False
- 参数校验：              空/空白/绝对/.. 模式与空 dir_path 均拒绝并提示原因

测试用例数量：39
"""

import os

import pytest

from core.tools._kernel import _fs_readonly
from core.tools._kernel._fs_readonly import glob_tool
from tests.helpers import read_json, rels


def test_glob_star_py_matches_root(tree):
    """基础匹配：*.py：验证单段模式只匹配根下文件、不递归子目录。

    - 根下 hello.py / main.py / x.py 应全部命中（count=3）
    - a/b.py、sub/nested/deep.py 在子目录中，不应出现
    """
    resp = read_json(glob_tool("*.py"))
    assert resp["status"] == "ok"
    assert resp["count"] == 3
    got = {os.path.basename(f) for f in resp["files"]}
    assert got == {"hello.py", "main.py", "x.py"}


def test_glob_star_matches_all_root_entries(tree):
    """基础匹配：*：验证单段 * 匹配根下全部条目。

    - 文件（含 .hidden.txt）与目录（a/b/sub）都匹配
    - .DS_Store、.venv、logs 被排除规则过滤
    """
    resp = read_json(glob_tool("*"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {
        "hello.py", "main.py", "x.py", "README.md", "data.txt",
        ".hidden.txt", "a", "b", "sub",
    }
    assert resp["count"] == 9


def test_glob_exact_path(tree):
    """基础匹配：精确路径：验证多段精确模式命中单个文件。

    a/b.py 无通配符，应精确命中 a 目录下的 b.py。
    """
    resp = read_json(glob_tool("a/b.py"))
    assert resp["status"] == "ok"
    assert resp["count"] == 1
    assert os.path.basename(resp["files"][0]) == "b.py"


def test_glob_multi_segment(tree):
    """基础匹配：深层精确路径：验证跨多层精确模式。

    sub/nested/deep.py 三段路径逐层消费，应命中唯一文件。
    """
    resp = read_json(glob_tool("sub/nested/deep.py"))
    assert resp["status"] == "ok"
    assert resp["count"] == 1
    assert os.path.basename(resp["files"][0]) == "deep.py"


def test_glob_dir_pattern(tree):
    """基础匹配：目录匹配：验证无通配模式可匹配目录自身。

    pattern=a 无通配符，普通叶子分支记录匹配的目录条目。
    """
    resp = read_json(glob_tool("a"))
    assert resp["status"] == "ok"
    assert resp["count"] == 1
    assert os.path.basename(resp["files"][0]) == "a"


def test_question_mark_wildcard(tree):
    """通配符：?：验证单字符通配。

    ?.py 匹配恰好一个字符的文件名，树中只有 x.py 满足。
    """
    resp = read_json(glob_tool("?.py"))
    assert resp["status"] == "ok"
    assert [os.path.basename(f) for f in resp["files"]] == ["x.py"]


def test_char_class_wildcard(tree):
    """通配符：[seq]：验证字符类通配。

    [hm]*.py 匹配 h 或 m 开头的 .py：hello.py 与 main.py。
    """
    resp = read_json(glob_tool("[hm]*.py"))
    assert resp["status"] == "ok"
    assert [os.path.basename(f) for f in resp["files"]] == ["hello.py", "main.py"]


def test_hidden_file_matched_by_star(tree):
    """通配符：隐藏文件：验证 fnmatch 语义下 * 匹配点开头文件。

    与标准 glob 不匹配隐藏文件不同，本实现基于 fnmatch，* 会匹配
    .hidden.txt（行为锁定）；.DS_Store 与 .venv 仍被排除规则过滤。
    """
    resp = read_json(glob_tool("*"))
    got = {os.path.basename(f) for f in resp["files"]}
    assert ".hidden.txt" in got

    resp = read_json(glob_tool(".*"))
    assert [os.path.basename(f) for f in resp["files"]] == [".hidden.txt"]


def test_double_star_all(tree):
    """** 递归：裸 **：验证匹配全部文件与目录（含根自身）。

    - 根目录自身以 "." 形式出现在结果中
    - 每个目录恰好被记录一次，无重复
    - .venv/logs 及内部文件不可见
    """
    resp = read_json(glob_tool("**"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {
        ".",
        "hello.py", "main.py", "x.py", "README.md", "data.txt", ".hidden.txt",
        "a", "a/b.py", "a/c", "a/c/note.txt",
        "b", "b/note.txt",
        "sub", "sub/data.txt", "sub/nested", "sub/nested/deep.py",
    }
    assert resp["count"] == 17
    assert resp["truncated"] is False


def test_double_star_py(tree):
    """** 递归：**/*.py：验证跨任意层匹配所有 .py 文件。

    根下 hello.py/main.py/x.py 与深层 a/b.py、sub/nested/deep.py 全部命中。
    """
    resp = read_json(glob_tool("**/*.py"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"hello.py", "main.py", "x.py", "a/b.py", "sub/nested/deep.py"}
    assert resp["count"] == 5


def test_double_star_txt(tree):
    """** 递归：**/*.txt：验证跨层匹配并返回全部层级结果。

    根下 data.txt 与各子目录中的 txt 全部命中（含 note.txt）；
    .hidden.txt 也被 *.txt 命中（fnmatch 语义，见隐藏文件用例）。
    """
    resp = read_json(glob_tool("**/*.txt"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"data.txt", ".hidden.txt", "a/c/note.txt", "b/note.txt", "sub/data.txt"}
    assert resp["count"] == 5


def test_double_star_note(tree):
    """** 递归：**/note.txt：验证按文件名跨层定位。

    ** 跨任意层后匹配 note.txt，两个子目录中的同名文件都命中。
    """
    resp = read_json(glob_tool("**/note.txt"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"a/c/note.txt", "b/note.txt"}
    assert resp["count"] == 2


def test_dir_double_star(tree):
    """** 递归：a/**：验证匹配目录自身与内部全部条目。

    - a 自身被记录（** 零层匹配）
    - a 下文件与子目录全部命中，共 4 个
    """
    resp = read_json(glob_tool("a/**"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"a", "a/b.py", "a/c", "a/c/note.txt"}
    assert resp["count"] == 4


def test_double_star_zero_level(tree):
    """** 递归：零层语义：验证 **/hello.py 中 ** 可视为不存在。

    ** 先尝试零层匹配（不消费任何目录），直接命中根下 hello.py。
    """
    resp = read_json(glob_tool("**/hello.py"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"hello.py"}
    assert resp["count"] == 1


def test_excluded_dirs_not_returned(tree):
    """排除规则：排除目录：验证既不返回也不进入。

    .venv 与 logs 不出现在结果中，其内部文件（venv.py/app.log）
    也因不进入而不被扫描到。
    """
    resp = read_json(glob_tool("**"))
    got = rels(tree, resp["files"])
    assert ".venv" not in got
    assert "logs" not in got
    assert ".venv/venv.py" not in got
    assert "logs/app.log" not in got


def test_excluded_files_filtered(tree):
    """排除规则：排除文件：验证 .DS_Store 匹配到也被过滤。

    - * 与 ** 的结果中都不含 .DS_Store
    - .DS_* 模式匹配到 .DS_Store 但被过滤，返回空结果
    """
    for pattern in ("*", "**", "**/*"):
        resp = read_json(glob_tool(pattern))
        assert all(".DS_Store" not in os.path.basename(f) for f in resp["files"])

    resp = read_json(glob_tool(".DS_*"))
    assert resp["status"] == "ok"
    assert resp["files"] == []


def test_dir_path_into_excluded_dir(tree):
    """排除规则：排除目录直指：验证 dir_path 指向其内部可正常搜索。

    docstring Notes：排除目录既不返回也不进入，但将 dir_path 直接
    指向该目录即可搜索其内部。
    """
    resp = read_json(glob_tool("*.py", dir_path=".venv"))
    assert resp["status"] == "ok"
    assert [os.path.basename(f) for f in resp["files"]] == ["venv.py"]


def test_dir_path_subdir(tree):
    """dir_path：子目录：验证只搜索指定子目录。

    dir_path=a 时 *.py 只匹配 a 下的 b.py，根下文件不出现。
    """
    resp = read_json(glob_tool("*.py", dir_path="a"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"a/b.py"}
    assert resp["count"] == 1


def test_dir_path_absolute_inside(tree):
    """dir_path：绝对路径：验证工作区内绝对路径与相对路径等价。

    isabs 分支直接 realpath 后做前缀检查，工作区内绝对路径应放行。
    """
    abs_ws = os.path.realpath(str(tree))
    resp = read_json(glob_tool("*.py", dir_path=abs_ws))
    assert resp["status"] == "ok"
    assert resp["count"] == 3


def test_dir_path_outside_denied(tree):
    """dir_path：越界：验证 ../ 跳出工作区被拦截。

    ../outside 与工作区拼接并经 realpath 归一化后落在工作区外，
    前缀检查按目录边界匹配拒绝访问。
    """
    resp = read_json(glob_tool("*.py", dir_path="../outside"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


def test_dir_path_absolute_outside_denied(tree):
    """dir_path：系统路径：验证 /etc 等绝对路径被拦截。

    前缀检查先于目录存在性检查：即使 /etc 真实存在，越界即拒绝。
    """
    resp = read_json(glob_tool("*.py", dir_path="/etc"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


def test_dir_path_not_directory(tree):
    """dir_path：非目录：验证指向文件时拒绝。

    dir_path 指向 hello.py（文件），isdir 检查拒绝。
    """
    resp = read_json(glob_tool("*", dir_path="hello.py"))
    assert resp["status"] == "error"
    assert "is not a directory" in resp["message"]


def test_dir_path_missing(tree):
    """dir_path：不存在：验证指向不存在路径时拒绝。

    工作区内不存在的目录，isdir 检查返回 False，同样报不是目录。
    """
    resp = read_json(glob_tool("*", dir_path="nope"))
    assert resp["status"] == "error"
    assert "is not a directory" in resp["message"]


def test_allow_external_reads(workspace):
    """dir_path：外部放行：验证 allow_external_reads 开关生效。

    目录建在工作区外：
    - 默认 False：前缀检查拦截，返回 error（denied）
    - 传 True：放行，可正常搜索其内部文件
    """
    outside = workspace.parent / "ext"
    outside.mkdir()
    (outside / "out.py").write_text("print('out')\n", encoding="utf-8")

    resp = read_json(glob_tool("*.py", dir_path=str(outside)))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]

    resp = read_json(glob_tool("*.py", dir_path=str(outside), allow_external_reads=True))
    assert resp["status"] == "ok"
    assert [os.path.basename(f) for f in resp["files"]] == ["out.py"]


def test_symlink_dir_not_entered(tree):
    """路径安全：符号链接目录：验证不跟随进入（防逃逸）。

    - 指向工作区外的目录符号链接，**/*.py 不暴露其内部文件
    - 裸 ** 中链接自身作为普通条目被记录（is_dir(follow_symlinks=False)）
    """
    outside = tree.parent / "secret_dir"
    outside.mkdir()
    (outside / "secret.py").write_text("print('secret')\n", encoding="utf-8")
    os.symlink(str(outside), str(tree / "link"), target_is_directory=True)

    resp = read_json(glob_tool("**/*.py"))
    assert all("secret" not in f for f in resp["files"])
    assert all("link/" not in f for f in resp["files"])

    resp = read_json(glob_tool("**"))
    got = {os.path.basename(f) for f in resp["files"]}
    assert "link" in got


def test_result_cap_truncated(tree, monkeypatch):
    """上限截断：结果上限：验证 files 截断且 count 保留总数。

    将 GLOB_MAX_RESULTS 压到 20，造 30 个匹配文件：
    - files 只返回 20 个，count 仍为 30（截断发生在结果列表，不丢计数）
    - truncated=True，message 追加 (truncated) 标记
    """
    monkeypatch.setattr(_fs_readonly, "GLOB_MAX_RESULTS", 20)
    for i in range(30):
        (tree / f"f{i:02d}.txt").write_text("x\n", encoding="utf-8")

    resp = read_json(glob_tool("f*.txt"))
    assert resp["status"] == "ok"
    assert len(resp["files"]) == 20
    assert resp["count"] == 30
    assert resp["truncated"] is True
    assert "(truncated)" in resp["message"]


def test_scan_cap_truncated(tree, monkeypatch):
    """上限截断：扫描熔断：验证 total 达 GLOB_MAX_SCAN 停止扫描。

    将 GLOB_MAX_SCAN 压到 20，造 30 个匹配文件：
    - 第 20 个匹配后熔断，后续不再扫描（count=20）
    - 熔断后 truncated=True
    """
    monkeypatch.setattr(_fs_readonly, "GLOB_MAX_SCAN", 20)
    for i in range(30):
        (tree / f"g{i:02d}.txt").write_text("x\n", encoding="utf-8")

    resp = read_json(glob_tool("g*.txt"))
    assert resp["status"] == "ok"
    assert resp["count"] == 20
    assert len(resp["files"]) == 20
    assert resp["truncated"] is True


def test_files_sorted(tree):
    """结果形态：排序：验证 files 按路径字典序升序返回。

    乱序创建的文件，结果按名称排序（同前缀下相对路径排序
    与绝对路径排序一致）。
    """
    for name in ("zeta.py", "alpha.py", "mid.py"):
        (tree / name).write_text("print(1)\n", encoding="utf-8")

    resp = read_json(glob_tool("*.py"))
    assert resp["status"] == "ok"
    assert [os.path.basename(f) for f in resp["files"]] == [
        "alpha.py", "hello.py", "main.py", "mid.py", "x.py", "zeta.py",
    ]


def test_absolute_paths_returned(tree):
    """结果形态：绝对路径：验证返回路径均为工作区内绝对路径。

    _glob_walk 的 root 从 search_dir（realpath 归一化）出发，
    所有结果应为工作区真实路径前缀下的绝对路径。
    """
    resp = read_json(glob_tool("*.py"))
    assert resp["status"] == "ok"
    abs_ws = os.path.realpath(str(tree))
    assert all(f.startswith(abs_ws) for f in resp["files"])


def test_empty_result(tree):
    """结果形态：空结果：验证无匹配时的契约。

    - count=0、files=[]、truncated=False
    - status=ok（无匹配不是错误）
    """
    resp = read_json(glob_tool("*.xyz"))
    assert resp["status"] == "ok"
    assert resp["count"] == 0
    assert resp["files"] == []
    assert resp["truncated"] is False


def test_message_summary(tree):
    """结果形态：message：验证汇总匹配数量。

    树中根下 *.py 共 3 个，message 精确格式为
    "Found 3 files matching '*.py'"。
    """
    resp = read_json(glob_tool("*.py"))
    assert resp["status"] == "ok"
    assert resp["message"] == "Found 3 files matching '*.py'"


@pytest.mark.parametrize(
    "pattern, expect",
    [
        ("", "must not be empty"),
        ("   ", "must not be empty"),
        ("/etc/passwd", "absolute"),
        ("///", "absolute"),
        ("../x", ".."),
        ("a/../b", ".."),
    ],
)
def test_invalid_patterns(tree, pattern, expect):
    """参数校验：模式：验证非法模式被拒绝并提示对应原因。

    6 组参数化用例：空/空白/绝对路径/仅斜杠/.. 穿越（前缀与中间），
    每组断言 error 且 message 包含对应文案片段。
    """
    resp = read_json(glob_tool(pattern))
    assert resp["status"] == "error"
    assert expect in resp["message"]


@pytest.mark.parametrize("dir_path", ["", "   "])
def test_invalid_dir_path(tree, dir_path):
    """参数校验：dir_path：验证空/空白目录被拒绝。

    2 组参数化用例，断言 error 且 message 指明 dir_path。
    """
    resp = read_json(glob_tool("*.py", dir_path=dir_path))
    assert resp["status"] == "error"
    assert "dir_path must not be empty" in resp["message"]
