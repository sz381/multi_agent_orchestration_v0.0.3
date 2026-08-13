"""grep_tool 匹配语义与边界场景测试。

测试项目：
- test_grep_single_file_path:                验证 path 指向单个文件时只搜该文件
- test_grep_directory_recursive:             验证 path 为目录时递归搜索全部文件
- test_grep_case_sensitive_default:          验证默认区分大小写（FOO 不命中）
- test_grep_case_insensitive:                验证 case_sensitive=False 忽略大小写
- test_grep_glob_pattern_filter:             验证 glob_pattern 按文件名后缀过滤
- test_grep_glob_pattern_matches_basename:   验证精确文件名模式命中子目录同名文件
- test_grep_files_with_matches_mode:         验证 files_with_matches 去重后输出文件列表
- test_grep_count_mode:                      验证 count 模式按文件计数
- test_grep_count_respects_pagination:       验证 count 模式受 head_limit 分页限制（现状契约）
- test_grep_content_mode:                    验证 content 模式上下文块结构与 match 标记
- test_grep_content_context_lines_zero:      验证 context_lines=0 只输出命中行
- test_grep_content_context_lines_two:       验证 context_lines=2 扩展上下文且 match 唯一
- test_grep_offset_pagination:               验证 offset 跳过前 N 条匹配
- test_grep_head_limit_truncated:            验证 head_limit 截断且 truncated=True
- test_grep_head_limit_zero:                 验证 head_limit=0 不限制
- test_grep_page_field:                      验证 page 字段携带 offset/limit
- test_grep_offset_exceeds_error:            验证 offset 越界返回 error
- test_grep_regex_anchors:                   验证正则锚点语义（非字面量匹配）
- test_grep_invalid_pattern:                 参数化验证空/空白 pattern 拒绝
- test_grep_invalid_path:                    参数化验证空/空白 path 拒绝
- test_grep_invalid_glob_pattern:            参数化验证空/空白 glob_pattern 拒绝
- test_grep_glob_double_star:                参数化验证 ** 模式拒绝
- test_grep_glob_absolute:                   参数化验证绝对路径模式拒绝
- test_grep_glob_path_traversal:             参数化验证 .. 穿越模式拒绝
- test_grep_glob_path_separator:             验证含 / 相对模式拒绝
- test_grep_invalid_output_mode:             验证未知输出模式拒绝
- test_grep_invalid_context_lines:           参数化验证 context_lines 越界/类型错误拒绝
- test_grep_invalid_head_limit:              参数化验证 head_limit 越界/类型错误拒绝
- test_grep_invalid_offset:                  参数化验证 offset 越界/类型错误拒绝
- test_grep_invalid_regex:                   参数化验证非法正则拒绝
- test_grep_path_outside_denied:             验证 ../ 跳出工作区被拦截
- test_grep_path_absolute_outside_denied:    验证 /etc 等系统绝对路径被拦截
- test_grep_path_does_not_exist:             验证不存在路径拒绝
- test_grep_path_absolute_inside:            验证工作区内绝对路径与相对路径等价
- test_grep_allow_external_reads:            验证外部读取开关放行/拦截
- test_grep_exclude_dirs:                    验证排除目录不搜索（.venv）
- test_grep_exclude_files:                   验证排除文件不搜索（.DS_Store）
- test_grep_max_files_truncated:             验证 GREP_MAX_FILES 截断文件收集
- test_grep_large_file_skipped:              验证超大文件跳过并计入 skipped_large_files
- test_grep_binary_file_skipped:             验证 NUL 嗅探静默跳过二进制文件
- test_grep_utf16_whitelist:                 验证 UTF-16 白名单下正常搜索
- test_grep_undecodable_skipped:             验证解码失败文件静默跳过
- test_grep_encoding_param:                  验证 encoding 参数生效
- test_grep_multiline_dotall:                验证 multiline 让 . 跨行匹配
- test_grep_multiline_line_num:              验证跨行匹配行号取起点行且行文本完整
- test_grep_regex_timeout_breakers:          验证灾难性回溯熔断该文件
- test_grep_total_timeout_partial_results:   验证总时长预算耗尽返回部分结果
- test_grep_total_timeout_normal:            验证预算充足不截断
- test_grep_empty_result:                    验证无匹配契约（status=ok、无 page）
- test_grep_empty_result_message:            验证空结果 message 精确汇总
- test_grep_absolute_paths:                  验证三种输出模式均为绝对路径

覆盖场景：
- 定位：单文件 / 目录递归 / 子目录 / 隐藏文件 / 工作区内绝对路径
- 大小写：默认敏感、case_sensitive=False 忽略
- glob_pattern：*.py 后缀过滤、精确文件名（basename 语义，子目录同名回归）、
  ** / 绝对路径 / .. 穿越 / 含 / 模式四类拒绝
- 输出模式：files_with_matches（去重）、count（按文件计数、页内契约）、
  content（上下文块 + match 标记 + context_lines 扩展）
- 分页：offset 跳转、head_limit 截断与 0 不限、truncated 标记、page 字段、offset 越界
- 正则语义：锚点（^）、multiline DOTALL、跨行匹配起点行号与完整行文本
- 参数校验：pattern/path/glob_pattern/output_mode/context_lines/head_limit/offset/正则编译，
  数字参数显式排除 bool（True 是 int 子类）
- 路径安全：../ 与 /etc 越界拒绝、不存在拒绝、allow_external_reads 开关
- 排除规则：EXCLUDE_DIRS / EXCLUDE_FILES
- 资源上限：GREP_MAX_FILES 收集截断、GREP_MAX_FILE_SIZE 单文件跳过
- 编码与二进制：NUL 嗅探跳过、UTF-16 白名单、解码失败静默跳过、encoding 参数
- 超时熔断：单行灾难性回溯熔断文件（timed_out_files）、总时长预算返回部分结果
  （search_timed_out），二者均不报错
- 空结果：status=ok、total_matches=0、files_scanned 保留、无 page 字段

测试用例数量：69
"""

import os

import pytest

from core.tools._kernel import _fs_readonly
from core.tools._kernel._fs_readonly import grep_tool
from tests.helpers import make_file, read_json, rels


@pytest.mark.asyncio
async def test_grep_single_file_path(grep_tree):
    """基础匹配：单文件：验证 path 指向文件时只搜该文件。

    a.py 中 foo 命中 3 行（L1/L2/L5），files_scanned=1 证明没有遍历其他文件。
    """
    resp = read_json(await grep_tool("foo", path="a.py"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 3
    assert resp["files_scanned"] == 1
    assert resp["total_files"] == 1
    assert rels(grep_tree, resp["files"]) == {"a.py"}


@pytest.mark.asyncio
async def test_grep_directory_recursive(grep_tree):
    """基础匹配：目录递归：验证默认 path='.' 递归搜索全部文件。

    - total_matches=8：a.py 3 + b.py 2 + sub/c.py 1 + deep/nested/e.py 1 + .hidden.txt 1
    - 命中文件恰好 5 个，.DS_Store（排除文件）与 .venv/f.py（排除目录）不出现
    """
    resp = read_json(await grep_tool("foo"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 8
    assert rels(grep_tree, resp["files"]) == {
        "a.py", "b.py", "sub/c.py", "deep/nested/e.py", ".hidden.txt",
    }


@pytest.mark.asyncio
async def test_grep_case_sensitive_default(grep_tree):
    """大小写：默认敏感：验证 FOO 不被 foo 命中。

    a.py L4 是 FOO case，默认区分大小写时 a.py 仍只有 3 条匹配。
    """
    resp = read_json(await grep_tool("foo", path="a.py"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 3

    resp = read_json(await grep_tool("FOO", path="a.py"))
    assert resp["total_matches"] == 1


@pytest.mark.asyncio
async def test_grep_case_insensitive(grep_tree):
    """大小写：忽略：验证 case_sensitive=False 时 FOO 也命中。

    a.py L4 的 FOO case 被计入，a.py 匹配数从 3 涨到 4，全树从 8 涨到 9。
    """
    resp = read_json(await grep_tool("foo", case_sensitive=False, output_mode="count"))
    assert resp["status"] == "ok"
    assert resp["total_occurrences"] == 9
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    assert resp["results"][abs_a] == 4


@pytest.mark.asyncio
async def test_grep_glob_pattern_filter(grep_tree):
    """glob_pattern：后缀过滤：验证 *.py 只搜 Python 文件。

    .hidden.txt 与 sub/d.txt 被滤掉，命中从 8 降到 7（a 3 + b 2 + c 1 + e 1）。
    """
    resp = read_json(await grep_tool("foo", glob_pattern="*.py"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 7
    assert rels(grep_tree, resp["files"]) == {
        "a.py", "b.py", "sub/c.py", "deep/nested/e.py",
    }


@pytest.mark.asyncio
async def test_grep_glob_pattern_matches_basename(grep_tree):
    """glob_pattern：basename 语义：验证精确文件名模式命中子目录文件。

    glob_pattern="c.py" 应命中 sub/c.py——回归锁定：若按含路径段的 rel 匹配，
    子目录同名文件会被静默滤掉（历史 bug）。
    """
    resp = read_json(await grep_tool("foo", glob_pattern="c.py"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 1
    assert rels(grep_tree, resp["files"]) == {"sub/c.py"}


@pytest.mark.asyncio
async def test_grep_files_with_matches_mode(grep_tree):
    """输出模式：files_with_matches：验证文件列表去重且字段完备。

    a.py 贡献 3 条匹配，但 files 中只出现一次（去重），total_files=5。
    """
    resp = read_json(await grep_tool("foo"))
    assert resp["status"] == "ok"
    assert resp["output_mode"] == "files_with_matches"
    assert resp["total_matches"] == 8
    assert resp["total_files"] == 5
    assert resp["truncated"] is False
    assert resp["files_scanned"] == 6
    assert resp["files_truncated"] is False
    assert resp["skipped_large_files"] == 0
    assert resp["timed_out_files"] == 0
    assert resp["search_timed_out"] is False


@pytest.mark.asyncio
async def test_grep_count_mode(grep_tree):
    """输出模式：count：验证按文件计数与字段完备。

    results 键为绝对路径，a.py=3、b.py=2，total_occurrences=8。
    """
    resp = read_json(await grep_tool("foo", output_mode="count"))
    assert resp["status"] == "ok"
    assert resp["output_mode"] == "count"
    assert resp["total_occurrences"] == 8
    assert resp["total_matches"] == 8
    assert resp["total_files"] == 5
    abs_ws = os.path.realpath(str(grep_tree))
    results = {os.path.relpath(k, abs_ws): v for k, v in resp["results"].items()}
    assert results == {
        "a.py": 3,
        "b.py": 2,
        "sub/c.py": 1,
        "deep/nested/e.py": 1,
        ".hidden.txt": 1,
    }


@pytest.mark.asyncio
async def test_grep_count_respects_pagination(grep_tree):
    """输出模式：count 分页契约：验证 count 受 head_limit 限制（现状锁定）。

    当前实现 count 基于页内匹配（page_matches）：head_limit=2 时只数前 2 条，
    total_occurrences=2 而 total_matches=3（全局）。该行为为当前契约，测试锁定
    防止无意改动；若未来改为全量统计需同步更新本用例。
    """
    resp = read_json(await grep_tool("foo", path="a.py", output_mode="count", head_limit=2))
    assert resp["status"] == "ok"
    assert resp["total_occurrences"] == 2
    assert resp["total_matches"] == 3
    assert resp["truncated"] is True
    assert resp["page"] == {"offset": 0, "limit": 2}


@pytest.mark.asyncio
async def test_grep_content_mode(grep_tree):
    """输出模式：content：验证上下文块结构与 match 标记。

    a.py 的 foo 命中 L1/L2/L5，results 键为绝对路径，每个块恰好一个 match=True。
    """
    resp = read_json(await grep_tool("foo", path="a.py", output_mode="content"))
    assert resp["status"] == "ok"
    assert resp["output_mode"] == "content"
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    chunks = resp["results"][abs_a]
    assert len(chunks) == 3
    for chunk in chunks:
        assert sum(1 for line in chunk if line["match"]) == 1
    hit_lines = [next(line for line in chunk if line["match"]) for chunk in chunks]
    assert [line["line_num"] for line in hit_lines] == [1, 2, 5]
    assert [line["content"] for line in hit_lines] == ["foo bar", "hello foo", "foo"]


@pytest.mark.asyncio
async def test_grep_content_context_lines_zero(grep_tree):
    """输出模式：content 上下文：验证 context_lines=0 只输出命中行。

    每个块恰好 1 行且 match=True，行号与内容一一对应。
    """
    resp = read_json(await
        grep_tool("foo", path="a.py", output_mode="content", context_lines=0)
    )
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    chunks = resp["results"][abs_a]
    assert len(chunks) == 3
    for chunk in chunks:
        assert len(chunk) == 1
        assert chunk[0]["match"] is True
    assert [c[0]["line_num"] for c in chunks] == [1, 2, 5]


@pytest.mark.asyncio
async def test_grep_content_context_lines_two(grep_tree):
    """输出模式：content 上下文扩展：验证 context_lines=2 向两侧扩展并 clamp。

    L1 命中块覆盖 L1-L3；L5 命中块覆盖 L3-L5（尾部 clamp 到文件边界）；
    每块 match 标记恰好唯一指向命中行。
    """
    resp = read_json(await
        grep_tool("foo", path="a.py", output_mode="content", context_lines=2)
    )
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    chunks = resp["results"][abs_a]
    assert [len(c) for c in chunks] == [3, 4, 4]
    assert [(line["line_num"], line["match"]) for line in chunks[0]] == [
        (1, True), (2, False), (3, False),
    ]
    assert [(line["line_num"], line["match"]) for line in chunks[2]] == [
        (3, False), (4, False), (5, True), (6, False),
    ]


@pytest.mark.asyncio
async def test_grep_offset_pagination(grep_tree):
    """分页：offset：验证跳过前 N 条匹配。

    a.py 命中 L1/L2/L5，offset=1 后只剩 2 条，首块命中行应为 L2。
    """
    resp = read_json(await
        grep_tool("foo", path="a.py", output_mode="content", offset=1)
    )
    assert resp["status"] == "ok"
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    chunks = resp["results"][abs_a]
    assert len(chunks) == 2
    first_hit = next(line for line in chunks[0] if line["match"])
    assert first_hit["line_num"] == 2


@pytest.mark.asyncio
async def test_grep_head_limit_truncated(grep_tree):
    """分页：head_limit：验证截断到前 N 条且 truncated=True。

    a.py 共 3 条，head_limit=2 只返回 2 条，truncated = (0+2) < 3 = True。
    """
    resp = read_json(await grep_tool("foo", path="a.py", output_mode="content", head_limit=2))
    assert resp["status"] == "ok"
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    assert len(resp["results"][abs_a]) == 2
    assert resp["truncated"] is True
    assert resp["total_matches"] == 3


@pytest.mark.asyncio
async def test_grep_head_limit_zero(grep_tree):
    """分页：head_limit=0：验证 0 表示不限制。

    a.py 3 条匹配全部返回，truncated=False。
    """
    resp = read_json(await grep_tool("foo", path="a.py", output_mode="content", head_limit=0))
    assert resp["status"] == "ok"
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    assert len(resp["results"][abs_a]) == 3
    assert resp["truncated"] is False


@pytest.mark.asyncio
async def test_grep_page_field(grep_tree):
    """分页：page 字段：验证携带 offset/limit 便于 LLM 续页。

    默认 head_limit=200，显式传 5 后 page.limit 应反映实际传入值。
    """
    resp = read_json(await grep_tool("foo", path="a.py"))
    assert resp["page"] == {"offset": 0, "limit": 200}

    resp = read_json(await grep_tool("foo", path="a.py", head_limit=5, offset=1))
    assert resp["page"] == {"offset": 1, "limit": 5}


@pytest.mark.asyncio
async def test_grep_offset_exceeds_error(grep_tree):
    """分页：offset 越界：验证 offset >= total_matches 返回 error。

    a.py 共 3 条匹配，offset=3 已无结果可分页，报错而非空结果。
    """
    resp = read_json(await grep_tool("foo", path="a.py", offset=3))
    assert resp["status"] == "error"
    assert "offset 3 exceeds total matches 3" in resp["message"]


@pytest.mark.asyncio
async def test_grep_regex_anchors(grep_tree):
    """正则语义：锚点：验证 pattern 按正则编译而非字面量。

    ^foo 只命中行首：a.py L1/L5、b.py L2、sub/c.py L2、deep/nested/e.py L1、
    .hidden.txt L1，共 6 条（b.py L1 "bar foo" 与 a.py L2 "hello foo" 不命中）。
    """
    resp = read_json(await grep_tool("^foo"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 6


@pytest.mark.parametrize("pattern", ["", "   "])
@pytest.mark.asyncio
async def test_grep_invalid_pattern(grep_tree, pattern):
    """参数校验：pattern：验证空/空白模式拒绝。

    2 组参数化用例，断言 error 且 message 指明 pattern。
    """
    resp = read_json(await grep_tool(pattern))
    assert resp["status"] == "error"
    assert "pattern must not be empty" in resp["message"]


@pytest.mark.parametrize("path", ["", "   "])
@pytest.mark.asyncio
async def test_grep_invalid_path(grep_tree, path):
    """参数校验：path：验证空/空白路径拒绝。

    2 组参数化用例，断言 error 且 message 指明 path。
    """
    resp = read_json(await grep_tool("foo", path=path))
    assert resp["status"] == "error"
    assert "path must not be empty" in resp["message"]


@pytest.mark.parametrize("glob_pattern", ["", "   "])
@pytest.mark.asyncio
async def test_grep_invalid_glob_pattern(grep_tree, glob_pattern):
    """参数校验：glob_pattern：验证空/空白模式拒绝。

    2 组参数化用例，断言 error 且 message 指明 glob_pattern。
    """
    resp = read_json(await grep_tool("foo", glob_pattern=glob_pattern))
    assert resp["status"] == "error"
    assert "glob_pattern must not be empty" in resp["message"]


@pytest.mark.parametrize("glob_pattern", ["**", "**/*.py", "a/**"])
@pytest.mark.asyncio
async def test_grep_glob_double_star(grep_tree, glob_pattern):
    """参数校验：glob_pattern **：验证递归模式拒绝。

    3 组参数化用例：** 在 fnmatch（匹配 basename）中与 * 等价无递归语义，
    拒绝并提示改用 glob_tool，避免误导。
    """
    resp = read_json(await grep_tool("foo", glob_pattern=glob_pattern))
    assert resp["status"] == "error"
    assert "does not support '**'" in resp["message"]


@pytest.mark.parametrize("glob_pattern", ["/etc/*.py", "///"])
@pytest.mark.asyncio
async def test_grep_glob_absolute(grep_tree, glob_pattern):
    """参数校验：glob_pattern 绝对路径：验证拒绝。

    2 组参数化用例：绝对路径模式对 basename 永远匹配不到，isabs 检查拦截。
    """
    resp = read_json(await grep_tool("foo", glob_pattern=glob_pattern))
    assert resp["status"] == "error"
    assert "absolute paths are not allowed" in resp["message"]


@pytest.mark.parametrize("glob_pattern", ["../x/*.py", "a/../b.py"])
@pytest.mark.asyncio
async def test_grep_glob_path_traversal(grep_tree, glob_pattern):
    """参数校验：glob_pattern 穿越：验证 .. 组件拒绝。

    2 组参数化用例（前缀与中间），无安全风险但结果恒为空，提前报错避免困惑。
    """
    resp = read_json(await grep_tool("foo", glob_pattern=glob_pattern))
    assert resp["status"] == "error"
    assert "must not contain '..'" in resp["message"]


@pytest.mark.asyncio
async def test_grep_glob_path_separator(grep_tree):
    """参数校验：glob_pattern 路径分隔符：验证含 / 相对模式拒绝。

    "src/*.py" 等模式永远匹配不到 basename，提示用 path 参数限定目录。
    """
    resp = read_json(await grep_tool("foo", glob_pattern="src/*.py"))
    assert resp["status"] == "error"
    assert "path separators are not allowed" in resp["message"]
    assert "use the path parameter" in resp["message"]


@pytest.mark.asyncio
async def test_grep_invalid_output_mode(grep_tree):
    """参数校验：output_mode：验证未知模式拒绝并列出可用值。
    """
    resp = read_json(await grep_tool("foo", output_mode="unknown"))
    assert resp["status"] == "error"
    assert "Unknown output_mode" in resp["message"]
    assert "files_with_matches" in resp["message"]


@pytest.mark.parametrize("context_lines", [-1, 11, True, 1.5, "2"])
@pytest.mark.asyncio
async def test_grep_invalid_context_lines(grep_tree, context_lines):
    """参数校验：context_lines：验证越界与类型错误拒绝。

    5 组参数化用例：负数/超上限/float/str 均拒绝；
    True 是 int 子类（True < 10 成立），必须显式排除，否则语义错误地通过。
    """
    resp = read_json(await grep_tool("foo", context_lines=context_lines))
    assert resp["status"] == "error"
    assert "context_lines must be an integer between 0 and 10" in resp["message"]


@pytest.mark.parametrize("head_limit", [-1, 1001, True, 1.5])
@pytest.mark.asyncio
async def test_grep_invalid_head_limit(grep_tree, head_limit):
    """参数校验：head_limit：验证越界与类型错误拒绝。

    4 组参数化用例：负数/超上限/float/True（bool 需排除）均拒绝。
    """
    resp = read_json(await grep_tool("foo", head_limit=head_limit))
    assert resp["status"] == "error"
    assert "head_limit must be an integer between 0 and 1000" in resp["message"]


@pytest.mark.parametrize("offset", [-1, True, 1.5])
@pytest.mark.asyncio
async def test_grep_invalid_offset(grep_tree, offset):
    """参数校验：offset：验证负值与类型错误拒绝。

    3 组参数化用例：负数/float/True（bool 需排除）均拒绝。
    """
    resp = read_json(await grep_tool("foo", offset=offset))
    assert resp["status"] == "error"
    assert "offset must be a non-negative integer" in resp["message"]


@pytest.mark.parametrize("pattern", ["(", "[a", "*a"])
@pytest.mark.asyncio
async def test_grep_invalid_regex(grep_tree, pattern):
    """参数校验：正则编译：验证非法正则拒绝。

    3 组参数化用例：未闭合括号/未闭合字符类/裸量词，编译期报错返回 error，
    而不是在搜索阶段裸炸。
    """
    resp = read_json(await grep_tool(pattern))
    assert resp["status"] == "error"
    assert "Invalid regex pattern" in resp["message"]


@pytest.mark.asyncio
async def test_grep_path_outside_denied(grep_tree):
    """路径安全：越界：验证 ../ 跳出工作区被拦截。

    ../outside 拼接并经 realpath 归一化后落在工作区外，前缀检查按目录边界拒绝。
    """
    resp = read_json(await grep_tool("foo", path="../outside"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


@pytest.mark.asyncio
async def test_grep_path_absolute_outside_denied(grep_tree):
    """路径安全：系统路径：验证 /etc 等绝对路径被拦截。

    前缀检查先于存在性检查：即使 /etc 真实存在，越界即拒绝。
    """
    resp = read_json(await grep_tool("foo", path="/etc"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


@pytest.mark.asyncio
async def test_grep_path_does_not_exist(grep_tree):
    """路径安全：不存在：验证工作区内不存在的路径拒绝。

    存在性检查在越界检查之后，'nope' 合法但不存在的路径报 does not exist。
    """
    resp = read_json(await grep_tool("foo", path="nope"))
    assert resp["status"] == "error"
    assert "does not exist" in resp["message"]


@pytest.mark.asyncio
async def test_grep_path_absolute_inside(grep_tree):
    """路径安全：绝对路径：验证工作区内绝对路径与相对路径等价。

    isabs 分支直接 realpath 后做前缀检查，工作区内绝对路径应放行。
    """
    abs_ws = os.path.realpath(str(grep_tree))
    resp = read_json(await grep_tool("foo", path=abs_ws))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 8


@pytest.mark.asyncio
async def test_grep_allow_external_reads(grep_tree):
    """路径安全：外部放行：验证 allow_external_reads 开关生效。

    目录建在工作区外：
    - 默认 False：前缀检查拦截，返回 error（denied）
    - 传 True：放行，可正常搜索其内部文件
    """
    outside = grep_tree.parent / "ext"
    outside.mkdir(exist_ok=True)
    (outside / "out.txt").write_text("foo out\n", encoding="utf-8")

    resp = read_json(await grep_tool("foo", path=str(outside)))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]

    resp = read_json(await grep_tool("foo", path=str(outside), allow_external_reads=True))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 1


@pytest.mark.asyncio
async def test_grep_exclude_dirs(grep_tree):
    """排除规则：排除目录：验证 .venv 内部文件不进入搜索。

    即使内容含 foo，.venv/f.py 也不出现在结果中（目录在遍历阶段被剪枝）。
    """
    resp = read_json(await grep_tool("foo", output_mode="count"))
    got = rels(grep_tree, list(resp["results"].keys()))
    assert ".venv/f.py" not in got


@pytest.mark.asyncio
async def test_grep_exclude_files(grep_tree):
    """排除规则：排除文件：验证 .DS_Store 匹配到也被过滤。

    文件收集阶段直接滤掉，不进入搜索阶段。
    """
    resp = read_json(await grep_tool("foo"))
    got = rels(grep_tree, resp["files"])
    assert ".DS_Store" not in got
    assert resp["files_scanned"] == 6


@pytest.mark.asyncio
async def test_grep_max_files_truncated(grep_tree, monkeypatch):
    """上限：收集截断：验证文件数达 GREP_MAX_FILES 停止收集。

    将 GREP_MAX_FILES 压到 2：收集到 2 个文件即熔断，
    files_scanned=2、files_truncated=True，后续文件不再搜索。
    """
    monkeypatch.setattr(_fs_readonly, "GREP_MAX_FILES", 2)
    resp = read_json(await grep_tool("foo"))
    assert resp["status"] == "ok"
    assert resp["files_scanned"] == 2
    assert resp["files_truncated"] is True
    assert 0 < resp["total_matches"] < 8


@pytest.mark.asyncio
async def test_grep_large_file_skipped(grep_tree, monkeypatch):
    """上限：单文件大小：验证超过 GREP_MAX_FILE_SIZE 的文件跳过并报告。

    将上限压到 20 字节：a.py（44 字节）被跳过，计入 skipped_large_files，
    结果中不含 a.py，其余文件正常命中（8 - 3 = 5 条）。
    """
    monkeypatch.setattr(_fs_readonly, "GREP_MAX_FILE_SIZE", 20)
    resp = read_json(await grep_tool("foo"))
    assert resp["status"] == "ok"
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    assert resp["skipped_large_files"] == 1
    assert rels(grep_tree, resp["files"]) == {
        "b.py", "sub/c.py", "deep/nested/e.py", ".hidden.txt",
    }
    assert abs_a not in resp["files"]


@pytest.mark.asyncio
async def test_grep_binary_file_skipped(grep_tree):
    """二进制：NUL 嗅探：验证含 NUL 的二进制文件静默跳过。

    bin.dat 头部含 NUL 且编码为 utf-8（不在 UTF-16/32 白名单），
    判定二进制后跳过——若不跳过，正则会匹配到乱码产生垃圾结果。
    """
    (grep_tree / "bin.dat").write_bytes(b"foo\x00bar\n")

    resp = read_json(await grep_tool("foo"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 8
    got = rels(grep_tree, resp["files"])
    assert "bin.dat" not in got


@pytest.mark.asyncio
async def test_grep_utf16_whitelist(grep_tree):
    """二进制：UTF-16 白名单：验证 UTF-16 编码文件正常搜索。

    UTF-16 文本天然含 NUL 字节，白名单放行；需传 encoding="utf-16"
    （默认 utf-8 下解码失败），单文件搜索命中 1 条。
    """
    (grep_tree / "utf16.txt").write_text("foo\n", encoding="utf-16")

    resp = read_json(await grep_tool("foo", path="utf16.txt", encoding="utf-16"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 1
    assert rels(grep_tree, resp["files"]) == {"utf16.txt"}


@pytest.mark.asyncio
async def test_grep_undecodable_skipped(grep_tree):
    """编码：解码失败：验证非法 UTF-8 文件静默跳过。

    bad.bin 字节不合法且无 NUL（不触发二进制嗅探），读文件时
    UnicodeDecodeError 被捕获静默跳过，不中断整个搜索。
    """
    (grep_tree / "bad.bin").write_bytes(b"\xff\xfe\xfa\xfbfoo\n")

    resp = read_json(await grep_tool("foo"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 8
    got = rels(grep_tree, resp["files"])
    assert "bad.bin" not in got


@pytest.mark.asyncio
async def test_grep_encoding_param(grep_tree):
    """编码：encoding 参数：验证指定编码后可搜索非 utf-8 文件。

    latin1.txt 以 latin-1 编码（0xe9 非法 utf-8）：
    - 默认 utf-8：解码失败静默跳过，0 匹配
    - encoding="latin-1"：正常命中 1 条
    """
    (grep_tree / "latin1.txt").write_bytes("caf\xe9 foo\n".encode("latin-1"))

    resp = read_json(await grep_tool("foo", path="latin1.txt"))
    assert resp["total_matches"] == 0

    resp = read_json(await grep_tool("foo", path="latin1.txt", encoding="latin-1"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 1


@pytest.mark.asyncio
async def test_grep_multiline_dotall(grep_tree):
    """multiline：DOTALL：验证 multiline=True 让 . 跨行匹配。

    ml.py 为 "xxxbar\\nhello foo\\n"，模式 "bar.*foo"：
    - 默认：. 不匹配换行符，0 匹配
    - multiline=True：跨行命中 1 条（语义是 DOTALL 而非 MULTILINE）
    """
    (grep_tree / "ml.py").write_text("xxxbar\nhello foo\n", encoding="utf-8")

    resp = read_json(await grep_tool("bar.*foo", path="ml.py"))
    assert resp["total_matches"] == 0

    resp = read_json(await grep_tool("bar.*foo", path="ml.py", multiline=True))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 1


@pytest.mark.asyncio
async def test_grep_multiline_line_num(grep_tree):
    """multiline：行号与行文本：验证跨行匹配取起点行且行文本完整。

    模式 "bar.*foo" 从 L1 的 "xxxbar" 中间开始匹配：
    - line_num 取起点行 = 1（而非终点行 2）
    - content 模式渲染的命中行应为完整行 "xxxbar"（行边界截取，
      若按匹配文本截取会丢行前缀得到 "bar"）
    """
    (grep_tree / "ml.py").write_text("xxxbar\nhello foo\n", encoding="utf-8")

    resp = read_json(await
        grep_tool("bar.*foo", path="ml.py", output_mode="content",
                  context_lines=0, multiline=True)
    )
    assert resp["status"] == "ok"
    abs_ml = os.path.realpath(str(grep_tree / "ml.py"))
    chunk = resp["results"][abs_ml][0]
    assert chunk[0]["line_num"] == 1
    assert chunk[0]["content"] == "xxxbar"
    assert chunk[0]["match"] is True


@pytest.mark.asyncio
async def test_grep_regex_timeout_breakers(grep_tree):
    """超时熔断：单行灾难性回溯：验证熔断该文件而非拖垮整体。

    模式 (a|aa)+$ 对 "a"*40+"b" 回溯指数爆炸，单行超
    REGEX_MATCH_TIMEOUT_SECONDS 后该文件熔断，计入 timed_out_files，
    status 仍为 ok（部分失败不算错误）。
    """
    (grep_tree / "t.py").write_text("a" * 40 + "b\n", encoding="utf-8")

    resp = read_json(await grep_tool("(a|aa)+$", path="t.py"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 0
    assert resp["timed_out_files"] == 1
    assert "1 files timed out" in resp["message"]


@pytest.mark.asyncio
async def test_grep_total_timeout_partial_results(grep_tree, monkeypatch):
    """超时熔断：总时长预算：验证预算耗尽返回部分结果并标记。

    将 GREP_TOTAL_TIMEOUT_SECONDS 压到 0.01s，造 5 个 2 万行文件：
    搜索必然在行循环检查点熔断，返回部分结果（< 全量 10 万条），
    search_timed_out=True 且 status=ok（超时不是错误，只是结果不完整）。
    """
    monkeypatch.setattr(_fs_readonly, "GREP_TOTAL_TIMEOUT_SECONDS", 0.01)
    for i in range(5):
        make_file(grep_tree, f"big{i}.py", 20000)

    resp = read_json(await grep_tool("x"))
    assert resp["status"] == "ok"
    assert resp["search_timed_out"] is True
    assert 0 < resp["total_matches"] < 100000


@pytest.mark.asyncio
async def test_grep_total_timeout_normal(grep_tree):
    """超时熔断：预算充足：验证不触发截断。

    同规模数据下默认预算（30s），全部 10 万行搜索完成，
    search_timed_out=False、total_matches=100000。
    """
    for i in range(5):
        make_file(grep_tree, f"big{i}.py", 20000)

    resp = read_json(await grep_tool("x"))
    assert resp["status"] == "ok"
    assert resp["search_timed_out"] is False
    assert resp["total_matches"] == 100000


@pytest.mark.asyncio
async def test_grep_empty_result(grep_tree):
    """空结果：契约：验证无匹配时的响应形态。

    - status=ok（无匹配不是错误）
    - total_matches=0、total_files=0、files_scanned=6（仍报告扫描规模）
    - 空结果分支无 page 字段（与正常分支区分）
    """
    resp = read_json(await grep_tool("xyz"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 0
    assert resp["total_files"] == 0
    assert resp["files_scanned"] == 6
    assert resp["files_truncated"] is False
    assert resp["search_timed_out"] is False
    assert "page" not in resp


@pytest.mark.asyncio
async def test_grep_empty_result_message(grep_tree):
    """空结果：message：验证精确汇总格式。

    树中收集 6 个文件，message 精确格式为
    "No matches for 'xyz' in 6 files"。
    """
    resp = read_json(await grep_tool("xyz"))
    assert resp["message"] == "No matches for 'xyz' in 6 files"


@pytest.mark.asyncio
async def test_grep_absolute_paths(grep_tree):
    """结果形态：绝对路径：验证三种输出模式的路径均为工作区内绝对路径。

    files_with_matches 的 files、count 的 results 键、content 的 results 键
    三者统一为绝对路径（realpath 归一化），与 view_file / glob_tool 契约一致。
    """
    abs_ws = os.path.realpath(str(grep_tree))

    resp = read_json(await grep_tool("foo"))
    assert all(f.startswith(abs_ws) for f in resp["files"])

    resp = read_json(await grep_tool("foo", output_mode="count"))
    assert all(k.startswith(abs_ws) for k in resp["results"])

    resp = read_json(await grep_tool("foo", output_mode="content"))
    assert all(k.startswith(abs_ws) for k in resp["results"])
