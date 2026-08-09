"""view_file 分段续读与边界场景测试。

测试项目：
- test_read_first_page:                         验证默认参数下读取文件前 100 行的分页字段语义
- test_read_with_offset:                        验证 offset 跳转后从指定行开始读取
- test_has_more_false_at_exact_end:             验证恰好读完文件末尾时 has_more=False
- test_file_shorter_than_limit:                 验证文件行数少于 limit 时读完全部且 has_more=False
- test_read_from_subdir:                        验证可读取工作区子目录中的文件
- test_relative_path_with_dot_prefix:           验证 ./ 前缀相对路径与普通相对路径等价
- test_read_absolute_path:                      验证工作区内绝对路径可直接读取
- test_allow_external_reads:                    验证 allow_external_reads 开关对工作区外文件的放行/拦截
- test_read_last_line:                          验证 offset 指向最后一行时只返回一行
- test_line_content_matches_index:              验证行号与内容一一对应（索引内容文件）
- test_last_line_without_newline:               验证最后一行无换行符也能正常读取
- test_limit_extremes:                          验证 limit 上下限（1 与 1000）可正常读取
- test_read_gbk_encoding:                       验证 gbk 编码文件可正常读取
- test_decode_error_returns_friendly_message:   验证编码不匹配时返回友好错误提示
- test_directory_path_rejected:                 验证传入目录路径被拒绝
- test_relative_path_traversal_denied:          验证 ../ 相对路径跳出工作区被拦截
- test_system_path_denied:                      验证 /etc/passwd 等系统绝对路径被拦截
- test_binary_file_rejected:                    验证二进制文件被 NUL 嗅探拦截
- test_nul_containing_file_rejected:            验证含 NUL 的合法 UTF-8 文件被识别为二进制
- test_utf16_encoding:                          验证 utf-16 文本编码（含 NUL）不被嗅探误杀
- test_single_line_file:                        验证单行文件可正常读取
- test_trailing_empty_line:                     验证文件末尾空行算作一行且 content 为空
- test_paged_read_restores_content:             验证分段续读拼接后可完整还原原始内容
- test_truncated_sets_has_more:                 验证 1MB 截断时 has_more 恒为 True（修复点回归）
- test_first_line_exceeds_max_read_size:        验证首行超 1MB 时返回空结果+截断标记（修复点回归）
- test_oversized_line_can_be_skipped:           验证超长行可被 offset+1 跳过继续读取
- test_paged_read_completes_large_file:         验证大文件分段续读完整覆盖（旧实现读不完）
- test_paged_read_resume_from_mid_file:         验证从 1MB 之后深处开始分段续读
- test_skip_budget_soft_limit:                  验证跳过超限仅提示不拒读（软限制）
- test_offset_exceeds_file:                     验证 offset 超过总行数时返回 error
- test_offset_at_eof_position:                  验证 offset 指向末尾下一行时返回空结果
- test_empty_file:                              验证空文件返回空结果而非报错
- test_missing_file:                            验证不存在的文件返回友好错误
- test_invalid_params:                          参数化验证非法参数被拒绝并提示对应参数名

覆盖场景：
- 常规读取：                offset=1、limit=100 时行号连续、分页字段正确
- offset 跳转：            从文件中部指定行开始读取，行号与内容正确
- 恰好读满 limit           且文件正好结束：    EOF 探测返回 has_more=False
- 文件行数不足 limit：      读完全部行后 EOF 自然结束，has_more=False
- 子目录文件：              路径前缀检查不误伤工作区内的子目录
- ./ 前缀相对路径：         realpath 归一化后与普通相对路径等价
- 工作区内绝对路径：         isabs 分支直接 realpath，前缀检查放行
- 外部文件：                默认拒绝，allow_external_reads=True 时放行
- 末行读取：                跳过阶段恰好在最后一行收尾，start_line=end_line=total
- 内容对应：                行号与内容严格一一对应，内容不错位
- 无换行符末行：            readline 照常返回，content 无 \n 残留
- limit 极值：              limit=1 最小步长、limit=1000 上限均正常
- gbk 编码：                指定 encoding=gbk 正常读取中文内容
- 编码不匹配：              默认 utf-8 读 gbk 文件返回友好 error（UnicodeDecodeError 兜底）
- 目录路径：                isdir 检查拒绝目录，不进入读取
- 相对穿越：                ../ 归一化后落于工作区外，前缀检查拦截
- 系统路径：                前缀检查先于存在性检查，越界即拒绝
- 二进制文件：              头部 NUL 嗅探在解码前拦截，友好 error
- NUL 嗅探：                含 \x00 文件读取前被拦截（此前盲区闭环）
- utf-16                  白名单：encoding 指定 utf-16/32 时放行，不误伤文本
- 单行文件：                最小多行形态，读取后 EOF，has_more=False
- 末尾空行：                readline 的 "\n" 是空行而非 EOF，content 为空串
- 内容还原：                round-trip 拼接与原文逐字节一致（行号+内容+顺序）
- 1MB 截断：               truncated=True 时 has_more=True，message 提示续读
- 超长行（首行）：            空结果分支 truncated/has_more 用计算值，提示 offset+1 跳过
- 超长行（中部）：            逃生通道可用，跳过超长行后后续正常行可读
- 大文件完整性：            分段续读行号无遗漏、无重复、顺序完整
- 深处续读：                offset 可推进到 1MB 之后（跳过阶段越过截断线）
- 软限制：                 跳过超 VIEW_FILE_MAX_SKIP_BYTES 仅提示，不中断读取
- offset 越界：            跳过阶段读尽仍不足目标行，返回 error
- EOF 位置：               offset=total+1 返回空结果（三态边界：total/total+1/越界）
- 空文件：                 0 行返回空结果，has_more=False
- 文件不存在：              does not exist 友好错误
- 参数校验：               空路径/limit 0/1001/offset 0/负数均拒绝

测试用例数量：38
"""

import os

import pytest

from core.tools._kernel import _fs_readonly
from core.tools._kernel._fs_readonly import view_file
from core.tools._kernel.constants import MAX_READ_SIZE
from tests.helpers import make_file, make_indexed_file, read_json


def test_read_first_page(workspace):
    """常规读取：验证默认参数下读取文件前 100 行。

    150 行小文件（约 3KB），offset=1、limit=100 时：
    - 应返回第 1~100 行，行号连续（lines[0].line_no=1，lines[-1].line_no=100）
    - 文件未到末尾且远小于 1MB 截断线：has_more=True、truncated=False
    """
    path = make_file(workspace, "page.txt", 150)
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 100
    assert resp["start_line"] == 1
    assert resp["end_line"] == 100
    assert resp["has_more"] is True
    assert resp["truncated"] is False
    assert resp["lines"][0]["line_no"] == 1
    assert resp["lines"][-1]["line_no"] == 100


def test_read_with_offset(workspace):
    """常规读取：offset 跳转：验证从指定行开始读取。

    150 行小文件，offset=101、limit=10 时：
    - 应返回第 101~110 行（start_line=101、end_line=110、read_lines=10）
    - 文件还有 40 行未读：has_more=True
    """
    path = make_file(workspace, "deep.txt", 150)
    resp = read_json(view_file(str(path), offset=101, limit=10))
    assert resp["status"] == "ok"
    assert resp["start_line"] == 101
    assert resp["end_line"] == 110
    assert resp["read_lines"] == 10
    assert resp["has_more"] is True


def test_has_more_false_at_exact_end(workspace):
    """常规读取：恰好读完：验证文件正好结束时 has_more=False。

    100 行文件，offset=1、limit=100 恰好读满：
    - 读满 limit 后 EOF 探测（read(1)）为空
    - has_more=False，不会误报"还有内容"
    """
    path = make_file(workspace, "exact.txt", 100)
    resp = read_json(view_file(str(path), offset=1, limit=100))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 100
    assert resp["has_more"] is False


def test_file_shorter_than_limit(workspace):
    """常规读取：文件不足 limit：验证读完全部行后自然结束。

    5 行小文件，默认 limit=100 时：
    - 读满 5 行后 EOF 到达（非 limit 限制），read_lines=5、end_line=5
    - has_more=False，不会误报"还有内容"
    """
    path = make_file(workspace, "short.txt", 5)
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 5
    assert resp["end_line"] == 5
    assert resp["has_more"] is False


def test_read_from_subdir(workspace):
    """常规读取：子目录：验证可读取工作区子目录中的文件。

    view_file 的前缀检查按目录边界匹配（safe_root 以分隔符结尾），
    子目录路径仍以工作区开头，不应被误判为越界：
    - 10 行文件建在 workspace/logs/ 下，读取应正常返回全部行
    """
    path = make_file(workspace, "nested.txt", 10, subdir="logs")
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 10
    assert resp["start_line"] == 1
    assert resp["end_line"] == 10
    assert resp["has_more"] is False


def test_relative_path_with_dot_prefix(workspace):
    """常规读取：./ 前缀：验证 ./ 前缀相对路径与普通相对路径等价。

    realpath 会将 ./ 归一化，两种写法应解析到同一路径：
    - "./python/hello.py" 与 "python/hello.py" 返回的 path 与内容完全一致
    - status=ok，且返回的 path 无 ./ 残留（已归一化为绝对路径）
    """
    make_file(workspace, "hello.py", 3, subdir="python")
    resp_dot = read_json(view_file("./python/hello.py"))
    resp_plain = read_json(view_file("python/hello.py"))
    assert resp_dot["status"] == "ok"
    assert resp_plain["status"] == "ok"
    assert resp_dot["path"] == resp_plain["path"]
    assert "./" not in resp_dot["path"]
    assert resp_dot["lines"] == resp_plain["lines"]


def test_read_absolute_path(workspace):
    """常规读取：绝对路径：验证工作区内绝对路径可直接读取。

    make_file 返回的 path 本身即为工作区内的绝对路径，直接传入：
    - isabs 分支不做 join，仅 realpath 归一化后做前缀检查
    - 应正常读取全部行，且返回的 path 与归一化后的传入路径一致
    """
    path = make_file(workspace, "abs.txt", 5)
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 5
    assert resp["path"] == os.path.realpath(str(path))


def test_allow_external_reads(workspace):
    """边界场景：allow_external_reads：验证外部文件读取开关生效。

    文件建在工作区外（tmp_path 的兄弟目录）：
    - 默认 False：前缀检查拦截，返回 error（denied）
    - 传 True：放行，可正常读取全部行
    """
    outside = workspace.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    resp = read_json(view_file(str(outside)))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]

    resp = read_json(view_file(str(outside), allow_external_reads=True))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 1
    assert resp["lines"][0]["content"] == "secret"


def test_read_last_line(workspace):
    """常规读取：末行：验证 offset 指向最后一行时只返回一行。

    150 行文件，offset=150、limit=10 时：
    - 跳过阶段恰好跳过 149 行，读取阶段读到 EOF 自然结束（不足 limit）
    - 只返回 1 行：start_line=end_line=150，has_more=False
    """
    path = make_file(workspace, "tail.txt", 150)
    resp = read_json(view_file(str(path), offset=150, limit=10))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 1
    assert resp["start_line"] == 150
    assert resp["end_line"] == 150
    assert resp["has_more"] is False


def test_line_content_matches_index(workspace):
    """常规读取：内容校验：验证行号与内容一一对应。

    索引文件第 i 行内容为 line-{i}，offset=3、limit=4 时：
    - 每行的 line_no 与 content 严格对应（line_no=3 ↔ content="line-3"）
    - 行号张冠李戴类 bug 在此数据下必然暴露（同质内容文件测不出）
    """
    path = make_indexed_file(workspace, "indexed.txt", 10)
    resp = read_json(view_file(str(path), offset=3, limit=4))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 4
    for i, item in enumerate(resp["lines"]):
        assert item["line_no"] == 3 + i
        assert item["content"] == f"line-{3 + i}"


def test_last_line_without_newline(workspace):
    """常规读取：无换行符末行：验证最后一行缺 \n 也能正常读取。

    真实文件最后一行常无换行符（脚本、编辑器产物）：
    - readline 对无 \n 的最后一行照常返回，行数统计不受影响
    - content 经 rstrip("\n") 处理后无残留换行符
    """
    path = workspace / "noeol.txt"
    path.write_text("line1\nline2\nline3", encoding="utf-8")
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 3
    assert resp["end_line"] == 3
    assert resp["lines"][2]["content"] == "line3"
    assert "\n" not in resp["lines"][2]["content"]


def test_limit_extremes(workspace):
    """常规读取：limit 极值：验证 limit 上下限可正常读取。

    - limit=1：150 行文件只返回 1 行，has_more=True（最小步长，逐行续读）
    - limit=1000：5 行文件一次读完，has_more=False（上限放行且读取正常）
    """
    path = make_file(workspace, "limit_min.txt", 150)
    resp = read_json(view_file(str(path), limit=1))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 1
    assert resp["has_more"] is True

    path = make_file(workspace, "limit_max.txt", 5)
    resp = read_json(view_file(str(path), limit=1000))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 5
    assert resp["has_more"] is False


def test_read_gbk_encoding(workspace):
    """常规读取：gbk 编码：验证非 utf-8 文件指定编码后可正常读取。

    中文内容以 gbk 编码写入，传入 encoding="gbk"：
    - 应正常读取全部行，内容与写入时完全一致
    """
    path = workspace / "gbk.txt"
    path.write_text("你好，世界\n第二行\n", encoding="gbk")
    resp = read_json(view_file(str(path), encoding="gbk"))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 2
    assert resp["lines"][0]["content"] == "你好，世界"
    assert resp["lines"][1]["content"] == "第二行"


def test_decode_error_returns_friendly_message(workspace):
    """边界场景：编码不匹配：验证解码失败返回友好错误。

    gbk 文件未指定 encoding（默认 utf-8）时：
    - UnicodeDecodeError 被兜底捕获，返回 error 而非抛异常
    - message 提示可用 gbk/latin-1 重试
    """
    path = workspace / "gbk.txt"
    path.write_text("你好，世界\n", encoding="gbk")
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "error"
    assert "cannot be decoded as utf-8" in resp["message"]


def test_directory_path_rejected(workspace):
    """边界场景：目录路径：验证传入目录时被拒绝。

    view_file 只读文件，目录应在文件类型检查处被拦截：
    - 返回 error，提示是目录，不进入读取逻辑
    """
    (workspace / "adir").mkdir()
    resp = read_json(view_file(str(workspace / "adir")))
    assert resp["status"] == "error"
    assert "is a directory" in resp["message"]


def test_relative_path_traversal_denied(workspace):
    """边界场景：相对穿越：验证 ../ 跳出工作区被拦截。

    "../outside.txt" 与工作区拼接并经 realpath 归一化后落在工作区外：
    - 前缀检查按目录边界匹配，拒绝访问
    """
    outside = workspace.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    resp = read_json(view_file("../outside.txt"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


def test_system_path_denied(workspace):
    """边界场景：系统路径：验证 /etc/passwd 等绝对路径被拦截。

    前缀检查先于文件存在性检查：
    - 即使文件真实存在（/etc/passwd），越界即拒绝，不泄露任何信息
    """
    resp = read_json(view_file("/etc/passwd"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


def test_binary_file_rejected(workspace):
    """边界场景：二进制文件：验证二进制魔数在解码前被嗅探拦截。

    PNG 魔数 \x89PNG 头部含 NUL 字节：
    - NUL 嗅探在打开文本流之前拦截，返回 error
    - 不会把二进制当文本乱读
    """
    path = workspace / "img.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "error"
    assert "binary" in resp["message"]


def test_nul_containing_file_rejected(workspace):
    """边界场景：NUL 嗅探：验证含 NUL 的合法 UTF-8 文件被拦截。

    此前盲区：\x00 是合法 UTF-8 码点，含 NUL 文件不会触发解码错误，
    会被当文本返回（content 携带 NUL）；嗅探检测后应在读取前拦截：
    - 返回 error，提示疑似二进制文件
    """
    path = workspace / "nul.txt"
    path.write_bytes(b"abc\x00def\nxyz\n")
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "error"
    assert "binary" in resp["message"]


def test_utf16_encoding(workspace):
    """常规读取：utf-16 编码：验证含 NUL 的文本编码不被误杀。

    UTF-16 文本的 ASCII 字符天然带 \x00，嗅探白名单应放行：
    - 指定 encoding="utf-16" 时正常读取，内容与写入时一致
    """
    path = workspace / "utf16.txt"
    path.write_text("你好\n世界\n", encoding="utf-16")
    resp = read_json(view_file(str(path), encoding="utf-16"))
    assert resp["status"] == "ok"
    assert resp["lines"][0]["content"] == "你好"
    assert resp["lines"][1]["content"] == "世界"


def test_single_line_file(workspace):
    """常规读取：单行文件：验证仅一行的文件可正常读取。

    单行是常见文件形态（README、.env 等）：
    - 1 行文件，默认 limit=100：应返回 1 行，行号为 1
    - 读取后到达 EOF：has_more=False
    """
    path = workspace / "single.txt"
    path.write_text("only one line\n", encoding="utf-8")
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 1
    assert resp["start_line"] == 1
    assert resp["end_line"] == 1
    assert resp["lines"][0]["content"] == "only one line"
    assert resp["has_more"] is False


def test_trailing_empty_line(workspace):
    """常规读取：末尾空行：验证文件末尾的空行算作一行。

    readline 返回 "" 才是 EOF，返回 "\n" 是空行：
    - "line1\nline2\n\n" 共 3 行（line1、line2、末尾空行）
    - 空行的 content 经 rstrip("\n") 后为空串
    """
    path = workspace / "trail.txt"
    path.write_text("line1\nline2\n\n", encoding="utf-8")
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 3
    assert resp["end_line"] == 3
    assert resp["lines"][2]["content"] == ""
    assert resp["has_more"] is False


def test_paged_read_restores_content(workspace):
    """完整性：分段续读：拼接还原应等于原始文件内容。

    round-trip 还原：写入 → 分段读出 → 拼接，必须逐字节等于原文：
    - 覆盖"没丢行 + 每行内容完整 + 顺序正确"三个维度
    - 比仅校验行号序列的分页测试更进一步（连内容一起验证）
    """
    path = make_indexed_file(workspace, "full.txt", 300)
    original = path.read_text(encoding="utf-8")

    parts = []
    offset, limit = 1, 50
    while True:
        resp = read_json(view_file(str(path), offset=offset, limit=limit))
        assert resp["status"] == "ok"
        parts.extend(item["content"] for item in resp["lines"])
        if not resp["has_more"]:
            break
        offset = resp["end_line"] + 1

    rebuilt = "\n".join(parts) + "\n"
    assert rebuilt == original


def test_truncated_sets_has_more(workspace):
    """边界场景：1MB 截断：验证截断时 has_more 恒为 True。

    每行 5KB、2000 行约 10MB 的文件，limit=1000 时在 1MB 处命中截断：
    - truncated=True、read_lines < 1000（未读完，被截断）
    - 修复点回归：截断时 has_more 必须为 True（旧版写死 False 导致漏读）
    - message 提示可用 offset=end_line+1 续读
    """
    path = make_file(workspace, "huge.txt", 2000, line_len=5120)
    resp = read_json(view_file(str(path), offset=1, limit=1000))
    assert resp["status"] == "ok"
    assert resp["truncated"] is True
    assert resp["has_more"] is True
    assert resp["read_lines"] < 1000
    assert "Use offset=" in resp["message"]


def test_first_line_exceeds_max_read_size(workspace):
    """边界场景：超长行（首行）：验证首行超 1MB 时返回空结果并标记续读。

    第一行 > 1MB 时无法返回任何行，但必须标记 truncated + has_more：
    - 修复点回归：空结果分支不再写死 has_more=False/truncated=False
      （否则调用者 offset=end_line+1 会回到同一行，导致死循环/丢数据）
    - message 提示 exceeds 限制，并给出 offset=2 逃生提示
    """
    path = workspace / "big_line.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("x" * (MAX_READ_SIZE + 500 * 1024) + "\n")
        f.write("y" * 10 + "\n")
    resp = read_json(view_file(str(path), offset=1, limit=100))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 0
    assert resp["truncated"] is True
    assert resp["has_more"] is True
    assert "exceeds" in resp["message"]
    assert "offset=2" in resp["message"]


def test_oversized_line_can_be_skipped(workspace):
    """边界场景：超长行（中部）：验证超长行可被 offset+1 跳过。

    超长行位于中间时：指向它返回空结果 + truncated + has_more + 提示；
    且 offset+1 可跳过它继续读取后续内容（逃生通道可用）：
    - 超长行之前、之后的正常行均可正常读取
    - 修复点回归：空结果分支的截断标记与逃生提示
    """
    path = workspace / "big_line2.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("first\n")
        f.write("x" * (MAX_READ_SIZE + 500 * 1024) + "\n")
        f.write("last\n")
    resp = read_json(view_file(str(path), offset=1, limit=10))
    assert resp["status"] == "ok"
    assert resp["lines"][0]["content"] == "first"
    resp = read_json(view_file(str(path), offset=2, limit=10))
    assert resp["read_lines"] == 0
    assert resp["truncated"] is True
    assert resp["has_more"] is True
    resp = read_json(view_file(str(path), offset=3, limit=10))
    assert resp["status"] == "ok"
    assert resp["lines"][0]["content"] == "last"


def test_paged_read_completes_large_file(workspace):
    """大文件：分段续读：验证大文件可完整读完且无遗漏。

    约 2.6MB 文件（26000 行 × 101 字节）：
    - 旧实现（只读前 1MB）读不完，新实现必须完整覆盖
    - has_more=True 时续读必须能前进（offset=end_line+1 严格推进）
    - 收集全部行号：无遗漏、无重复、顺序完整
    """
    total = 26000
    path = make_file(workspace, "big.txt", total, line_len=101)
    seen = []
    offset = 1
    limit = 200
    while True:
        resp = read_json(view_file(str(path), offset=offset, limit=limit))
        assert resp["status"] == "ok"
        assert resp["start_line"] == offset
        seen.extend(line["line_no"] for line in resp["lines"])
        if not resp["has_more"]:
            break
        offset = resp["end_line"] + 1
    assert seen == list(range(1, total + 1))


def test_paged_read_resume_from_mid_file(workspace):
    """大文件：中部续读：验证从 1MB 之后的深处开始分段续读。

    约 2.6MB 文件，从第 15000 行（>1MB 位置）开始：
    - 跳过阶段需越过 1MB 以上，验证 offset 可推进到 1MB 之后
    - 收集行号：从 start 到末尾完整、无遗漏、无重复
    """
    total = 26000
    path = make_file(workspace, "big2.txt", total, line_len=101)
    start = 15000
    seen = []
    offset = start
    limit = 300
    while True:
        resp = read_json(view_file(str(path), offset=offset, limit=limit))
        assert resp["status"] == "ok"
        seen.extend(line["line_no"] for line in resp["lines"])
        if not resp["has_more"]:
            break
        offset = resp["end_line"] + 1
    assert seen == list(range(start, total + 1))


def test_skip_budget_soft_limit(workspace, monkeypatch):
    """边界场景：跳过软限制：验证超限仅提示、不拒读。

    将 VIEW_FILE_MAX_SKIP_BYTES 压到 16 字节，读取 offset=50 必然超限：
    - 软限制而非硬限制：不得拒读，正常返回目标行
    - message 含 Skipped 提示（skip_warned 开关保证仅提示一次）
    """
    monkeypatch.setattr(_fs_readonly, "VIEW_FILE_MAX_SKIP_BYTES", 16)
    path = make_file(workspace, "soft.txt", 100)
    resp = read_json(view_file(str(path), offset=50, limit=5))
    assert resp["status"] == "ok"
    assert resp["start_line"] == 50
    assert resp["read_lines"] == 5
    assert "Skipped" in resp.get("message", "")


def test_offset_exceeds_file(workspace):
    """边界场景：offset 越界：验证 offset 超过总行数时返回 error。

    5 行文件，offset=7（超出 2 行）：
    - 跳过阶段读完全部行仍未到目标行，返回 error
    - message 提示 exceeds total lines 及文件实际行数
    """
    path = make_file(workspace, "small.txt", 5)
    resp = read_json(view_file(str(path), offset=7))
    assert resp["status"] == "error"
    assert "exceeds total lines" in resp["message"]


def test_offset_at_eof_position(workspace):
    """边界场景：EOF 位置：验证 offset 指向末尾下一行时返回空结果。

    5 行文件，offset=6（恰好是末尾下一行）：
    - 跳过阶段恰好读完 5 行后 EOF：非"越界报错"而是空结果
    - 空结果契约：start_line=6、end_line=5（0 行区间）、has_more=False
    - 与 offset>total 的 error 形成三态边界（total / total+1 / 越界）
    """
    path = make_file(workspace, "small2.txt", 5)
    resp = read_json(view_file(str(path), offset=6, limit=5))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 0
    assert resp["start_line"] == 6
    assert resp["end_line"] == 5
    assert resp["has_more"] is False
    assert resp["truncated"] is False


def test_empty_file(workspace):
    """边界场景：空文件：验证空文件返回空结果而非报错。

    0 行文件：
    - read_lines=0、has_more=False、truncated=False
    - 与单行/多行文件共同构成文件形态族（空/单行/多行）
    """
    path = workspace / "empty.txt"
    path.write_text("", encoding="utf-8")
    resp = read_json(view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 0
    assert resp["has_more"] is False
    assert resp["truncated"] is False


def test_missing_file(workspace):
    """边界场景：文件不存在：验证不存在的路径返回友好错误。

    工作区内不存在的路径：
    - 通过越界检查后，在存在性检查处报 does not exist
    - 与目录/越界共同构成"三种打不开"的完整错误集
    """
    resp = read_json(view_file(str(workspace / "nope.txt")))
    assert resp["status"] == "error"
    assert "does not exist" in resp["message"]


@pytest.mark.parametrize(
    "kwargs, expect",
    [
        ({"file_path": "", "offset": 1}, "file_path must not be empty"),
        ({"file_path": "x.txt", "offset": 1, "limit": 0}, "limit"),
        ({"file_path": "x.txt", "offset": 1, "limit": 1001}, "limit"),
        ({"file_path": "x.txt", "offset": 0}, "offset"),
        ({"file_path": "x.txt", "offset": -5}, "offset"),
    ],
)
def test_invalid_params(workspace, kwargs, expect):
    """边界场景：参数校验：验证非法参数被拒绝并给出对应提示。

    5 组参数化用例：空 file_path / limit=0 / limit=1001 / offset=0 / offset=-5，
    每组断言 error 且 message 包含对应参数名。
    """
    resp = read_json(view_file(**kwargs))
    assert resp["status"] == "error"
    assert expect in resp["message"]

