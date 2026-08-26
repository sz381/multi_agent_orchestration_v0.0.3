"""Tests for view_file segmented continuation reads and boundary scenarios.

Test cases:
- test_read_first_page:                         reading the first 100 lines with default params, pagination field semantics
- test_read_with_offset:                        offset jumps to read from the given line
- test_has_more_false_at_exact_end:             has_more=False when the file end is reached exactly
- test_file_shorter_than_limit:                 files shorter than limit read fully with has_more=False
- test_read_from_subdir:                        files in workspace subdirectories are readable
- test_relative_path_with_dot_prefix:           ./-prefixed relative paths equal ordinary relative paths
- test_read_absolute_path:                      absolute paths inside the workspace are directly readable
- test_allow_external_reads:                    allow_external_reads switch allows/blocks files outside the workspace
- test_read_last_line:                          offset pointing at the last line returns exactly one line
- test_line_content_matches_index:              line numbers and content correspond one-to-one (indexed content file)
- test_last_line_without_newline:               the last line without a newline is readable
- test_limit_extremes:                          limit bounds (1 and 1000) read normally
- test_read_gbk_encoding:                       gbk-encoded files read normally
- test_decode_error_returns_friendly_message:   encoding mismatch returns a friendly error hint
- test_directory_path_rejected:                 directory paths are rejected
- test_relative_path_traversal_denied:          ../ relative paths escaping the workspace are blocked
- test_system_path_denied:                      system absolute paths like /etc/passwd are blocked
- test_binary_file_rejected:                    binary files are intercepted by NUL sniffing
- test_nul_containing_file_rejected:            legal UTF-8 files containing NUL are recognized as binary
- test_utf16_encoding:                          utf-16 text encoding (contains NUL) is not killed by sniffing
- test_single_line_file:                        single-line files read normally
- test_trailing_empty_line:                     a trailing empty line counts as a line with empty content
- test_paged_read_restores_content:             segmented continuation reads reassemble the original content fully
- test_truncated_sets_has_more:                 1MB truncation keeps has_more always True (fix-point regression)
- test_first_line_exceeds_max_read_size:        a first line over 1MB returns an empty result with a truncation marker (fix-point regression)
- test_oversized_line_can_be_skipped:           overlong lines can be skipped with offset+1 to continue reading
- test_paged_read_completes_large_file:         segmented continuation reads cover large files fully (old implementation could not)
- test_paged_read_resume_from_mid_file:         segmented continuation reads resume deep past 1MB
- test_skip_budget_soft_limit:                  skip over the limit only warns, does not refuse (soft limit)
- test_offset_exceeds_file:                     offset beyond the total line count returns error
- test_offset_at_eof_position:                  offset pointing at the line after EOF returns an empty result
- test_empty_file:                              empty files return an empty result rather than an error
- test_missing_file:                            nonexistent files return a friendly error
- test_invalid_params:                          parametrized: invalid params rejected with the corresponding param name

Covered scenarios:
- Normal reads:              offset=1, limit=100 with continuous line numbers and correct pagination fields
- offset jumps:              reading from a specified mid-file line with correct line numbers and content
- Exactly limit              and the file ends there:    EOF detection returns has_more=False
- File shorter than limit:   all lines read, EOF ends naturally, has_more=False
- Subdirectory files:        path-prefix checks do not hurt workspace subdirectories
- ./-prefixed relative paths: equal ordinary relative paths after realpath normalization
- Absolute paths in workspace: the isabs branch realpaths directly and prefix checks pass
- External files:            denied by default, allowed with allow_external_reads=True
- Last-line reads:           the skip stage finishes exactly on the last line, start_line=end_line=total
- Content correspondence:    line numbers and content strictly one-to-one, no misalignment
- Last line without newline: readline returns it normally, content has no \n leftover
- limit extremes:            limit=1 minimum step and limit=1000 maximum both work
- gbk encoding:              reading Chinese content works with encoding=gbk
- Encoding mismatch:         reading a gbk file with default utf-8 returns a friendly error (UnicodeDecodeError fallback)
- Directory paths:           isdir check rejects directories without reading
- Relative traversal:        ../ normalized to outside the workspace, prefix check blocks
- System paths:              prefix checks precede existence checks, out-of-bounds rejected
- Binary files:              head NUL sniffing intercepts before decoding, friendly error
- NUL sniffing:              files containing \x00 are intercepted before reading (previous blind spot closed)
- utf-16                  whitelist: encoding specified as utf-16/32 passes, text not hurt
- Single-line files:         minimal multi-line form, EOF after reading, has_more=False
- Trailing empty line:       readline's "\n" is an empty line, not EOF, content is an empty string
- Content restoration:       round-trip concatenation matches the original byte-for-byte (line numbers + content + order)
- 1MB truncation:           truncated=True gives has_more=True, message hints continuation
- Overlong line (first):    the empty-result branch uses computed truncated/has_more, hints skipping with offset+1
- Overlong line (middle):   the escape hatch works, normal lines after the skipped overlong line are readable
- Large-file integrity:      segmented continuation reads have no missing/duplicate line numbers, complete order
- Deep resumption:           offset can advance past 1MB (the skip stage crosses the truncation line)
- Soft limit:               skipping over VIEW_FILE_MAX_SKIP_BYTES only warns, does not interrupt reading
- offset out of range:      the skip stage reads everything and still cannot reach the target line, returns error
- EOF position:             offset=total+1 returns an empty result (three-state boundary: total/total+1/out of range)
- Empty file:               0 lines return an empty result, has_more=False
- Missing file:             does not exist friendly error
- Parameter validation:     empty path/limit 0/1001/offset 0/negative all rejected
"""

import os

import pytest

from core.tools._kernel import _fs_readonly
from core.tools._kernel._fs_readonly import view_file
from core.tools._kernel.constants import MAX_READ_SIZE
from tests.helpers import make_file, make_indexed_file, read_json


@pytest.mark.asyncio
async def test_read_first_page(workspace):
    path = make_file(workspace, "page.txt", 150)
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 100
    assert resp["start_line"] == 1
    assert resp["end_line"] == 100
    assert resp["has_more"] is True
    assert resp["truncated"] is False
    assert resp["lines"][0]["line_no"] == 1
    assert resp["lines"][-1]["line_no"] == 100


@pytest.mark.asyncio
async def test_read_with_offset(workspace):
    path = make_file(workspace, "deep.txt", 150)
    resp = read_json(await view_file(str(path), offset=101, limit=10))
    assert resp["status"] == "ok"
    assert resp["start_line"] == 101
    assert resp["end_line"] == 110
    assert resp["read_lines"] == 10
    assert resp["has_more"] is True


@pytest.mark.asyncio
async def test_has_more_false_at_exact_end(workspace):
    path = make_file(workspace, "exact.txt", 100)
    resp = read_json(await view_file(str(path), offset=1, limit=100))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 100
    assert resp["has_more"] is False


@pytest.mark.asyncio
async def test_file_shorter_than_limit(workspace):
    path = make_file(workspace, "short.txt", 5)
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 5
    assert resp["end_line"] == 5
    assert resp["has_more"] is False


@pytest.mark.asyncio
async def test_read_from_subdir(workspace):
    path = make_file(workspace, "nested.txt", 10, subdir="logs")
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 10
    assert resp["start_line"] == 1
    assert resp["end_line"] == 10
    assert resp["has_more"] is False


@pytest.mark.asyncio
async def test_relative_path_with_dot_prefix(workspace):
    make_file(workspace, "hello.py", 3, subdir="python")
    resp_dot = read_json(await view_file("./python/hello.py"))
    resp_plain = read_json(await view_file("python/hello.py"))
    assert resp_dot["status"] == "ok"
    assert resp_plain["status"] == "ok"
    assert resp_dot["path"] == resp_plain["path"]
    assert "./" not in resp_dot["path"]
    assert resp_dot["lines"] == resp_plain["lines"]


@pytest.mark.asyncio
async def test_read_absolute_path(workspace):
    path = make_file(workspace, "abs.txt", 5)
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 5
    assert resp["path"] == os.path.realpath(str(path))


@pytest.mark.asyncio
async def test_allow_external_reads(workspace):
    outside = workspace.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    resp = read_json(await view_file(str(outside)))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]

    resp = read_json(await view_file(str(outside), allow_external_reads=True))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 1
    assert resp["lines"][0]["content"] == "secret"


@pytest.mark.asyncio
async def test_read_last_line(workspace):
    path = make_file(workspace, "tail.txt", 150)
    resp = read_json(await view_file(str(path), offset=150, limit=10))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 1
    assert resp["start_line"] == 150
    assert resp["end_line"] == 150
    assert resp["has_more"] is False


@pytest.mark.asyncio
async def test_line_content_matches_index(workspace):
    path = make_indexed_file(workspace, "indexed.txt", 10)
    resp = read_json(await view_file(str(path), offset=3, limit=4))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 4
    for i, item in enumerate(resp["lines"]):
        assert item["line_no"] == 3 + i
        assert item["content"] == f"line-{3 + i}"


@pytest.mark.asyncio
async def test_last_line_without_newline(workspace):
    path = workspace / "noeol.txt"
    path.write_text("line1\nline2\nline3", encoding="utf-8")
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 3
    assert resp["end_line"] == 3
    assert resp["lines"][2]["content"] == "line3"
    assert "\n" not in resp["lines"][2]["content"]


@pytest.mark.asyncio
async def test_limit_extremes(workspace):
    path = make_file(workspace, "limit_min.txt", 150)
    resp = read_json(await view_file(str(path), limit=1))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 1
    assert resp["has_more"] is True

    path = make_file(workspace, "limit_max.txt", 5)
    resp = read_json(await view_file(str(path), limit=1000))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 5
    assert resp["has_more"] is False


@pytest.mark.asyncio
async def test_read_gbk_encoding(workspace):
    path = workspace / "gbk.txt"
    path.write_text("你好，世界\n第二行\n", encoding="gbk")
    resp = read_json(await view_file(str(path), encoding="gbk"))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 2
    assert resp["lines"][0]["content"] == "你好，世界"
    assert resp["lines"][1]["content"] == "第二行"


@pytest.mark.asyncio
async def test_decode_error_returns_friendly_message(workspace):
    path = workspace / "gbk.txt"
    path.write_text("你好，世界\n", encoding="gbk")
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "error"
    assert "cannot be decoded as utf-8" in resp["message"]


@pytest.mark.asyncio
async def test_directory_path_rejected(workspace):
    (workspace / "adir").mkdir()
    resp = read_json(await view_file(str(workspace / "adir")))
    assert resp["status"] == "error"
    assert "is a directory" in resp["message"]


@pytest.mark.asyncio
async def test_relative_path_traversal_denied(workspace):
    outside = workspace.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    resp = read_json(await view_file("../outside.txt"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


@pytest.mark.asyncio
async def test_system_path_denied(workspace):
    resp = read_json(await view_file("/etc/passwd"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


@pytest.mark.asyncio
async def test_binary_file_rejected(workspace):
    path = workspace / "img.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "error"
    assert "binary" in resp["message"]


@pytest.mark.asyncio
async def test_nul_containing_file_rejected(workspace):
    path = workspace / "nul.txt"
    path.write_bytes(b"abc\x00def\nxyz\n")
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "error"
    assert "binary" in resp["message"]


@pytest.mark.asyncio
async def test_utf16_encoding(workspace):
    path = workspace / "utf16.txt"
    path.write_text("你好\n世界\n", encoding="utf-16")
    resp = read_json(await view_file(str(path), encoding="utf-16"))
    assert resp["status"] == "ok"
    assert resp["lines"][0]["content"] == "你好"
    assert resp["lines"][1]["content"] == "世界"


@pytest.mark.asyncio
async def test_single_line_file(workspace):
    path = workspace / "single.txt"
    path.write_text("only one line\n", encoding="utf-8")
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 1
    assert resp["start_line"] == 1
    assert resp["end_line"] == 1
    assert resp["lines"][0]["content"] == "only one line"
    assert resp["has_more"] is False


@pytest.mark.asyncio
async def test_trailing_empty_line(workspace):
    path = workspace / "trail.txt"
    path.write_text("line1\nline2\n\n", encoding="utf-8")
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 3
    assert resp["end_line"] == 3
    assert resp["lines"][2]["content"] == ""
    assert resp["has_more"] is False


@pytest.mark.asyncio
async def test_paged_read_restores_content(workspace):
    path = make_indexed_file(workspace, "full.txt", 300)
    original = path.read_text(encoding="utf-8")

    parts = []
    offset, limit = 1, 50
    while True:
        resp = read_json(await view_file(str(path), offset=offset, limit=limit))
        assert resp["status"] == "ok"
        parts.extend(item["content"] for item in resp["lines"])
        if not resp["has_more"]:
            break
        offset = resp["end_line"] + 1

    rebuilt = "\n".join(parts) + "\n"
    assert rebuilt == original


@pytest.mark.asyncio
async def test_truncated_sets_has_more(workspace):
    path = make_file(workspace, "huge.txt", 2000, line_len=5120)
    resp = read_json(await view_file(str(path), offset=1, limit=1000))
    assert resp["status"] == "ok"
    assert resp["truncated"] is True
    assert resp["has_more"] is True
    assert resp["read_lines"] < 1000
    assert "Use offset=" in resp["message"]


@pytest.mark.asyncio
async def test_first_line_exceeds_max_read_size(workspace):
    path = workspace / "big_line.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("x" * (MAX_READ_SIZE + 500 * 1024) + "\n")
        f.write("y" * 10 + "\n")
    resp = read_json(await view_file(str(path), offset=1, limit=100))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 0
    assert resp["truncated"] is True
    assert resp["has_more"] is True
    assert "exceeds" in resp["message"]
    assert "offset=2" in resp["message"]


@pytest.mark.asyncio
async def test_oversized_line_can_be_skipped(workspace):
    path = workspace / "big_line2.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("first\n")
        f.write("x" * (MAX_READ_SIZE + 500 * 1024) + "\n")
        f.write("last\n")
    resp = read_json(await view_file(str(path), offset=1, limit=10))
    assert resp["status"] == "ok"
    assert resp["lines"][0]["content"] == "first"
    resp = read_json(await view_file(str(path), offset=2, limit=10))
    assert resp["read_lines"] == 0
    assert resp["truncated"] is True
    assert resp["has_more"] is True
    resp = read_json(await view_file(str(path), offset=3, limit=10))
    assert resp["status"] == "ok"
    assert resp["lines"][0]["content"] == "last"


@pytest.mark.asyncio
async def test_paged_read_completes_large_file(workspace):
    total = 26000
    path = make_file(workspace, "big.txt", total, line_len=101)
    seen = []
    offset = 1
    limit = 200
    while True:
        resp = read_json(await view_file(str(path), offset=offset, limit=limit))
        assert resp["status"] == "ok"
        assert resp["start_line"] == offset
        seen.extend(line["line_no"] for line in resp["lines"])
        if not resp["has_more"]:
            break
        offset = resp["end_line"] + 1
    assert seen == list(range(1, total + 1))


@pytest.mark.asyncio
async def test_paged_read_resume_from_mid_file(workspace):
    total = 26000
    path = make_file(workspace, "big2.txt", total, line_len=101)
    start = 15000
    seen = []
    offset = start
    limit = 300
    while True:
        resp = read_json(await view_file(str(path), offset=offset, limit=limit))
        assert resp["status"] == "ok"
        seen.extend(line["line_no"] for line in resp["lines"])
        if not resp["has_more"]:
            break
        offset = resp["end_line"] + 1
    assert seen == list(range(start, total + 1))


@pytest.mark.asyncio
async def test_skip_budget_soft_limit(workspace, monkeypatch):
    monkeypatch.setattr(_fs_readonly, "VIEW_FILE_MAX_SKIP_BYTES", 16)
    path = make_file(workspace, "soft.txt", 100)
    resp = read_json(await view_file(str(path), offset=50, limit=5))
    assert resp["status"] == "ok"
    assert resp["start_line"] == 50
    assert resp["read_lines"] == 5
    assert "Skipped" in resp.get("message", "")


@pytest.mark.asyncio
async def test_offset_exceeds_file(workspace):
    path = make_file(workspace, "small.txt", 5)
    resp = read_json(await view_file(str(path), offset=7))
    assert resp["status"] == "error"
    assert "exceeds total lines" in resp["message"]


@pytest.mark.asyncio
async def test_offset_at_eof_position(workspace):
    path = make_file(workspace, "small2.txt", 5)
    resp = read_json(await view_file(str(path), offset=6, limit=5))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 0
    assert resp["start_line"] == 6
    assert resp["end_line"] == 5
    assert resp["has_more"] is False
    assert resp["truncated"] is False


@pytest.mark.asyncio
async def test_empty_file(workspace):
    path = workspace / "empty.txt"
    path.write_text("", encoding="utf-8")
    resp = read_json(await view_file(str(path)))
    assert resp["status"] == "ok"
    assert resp["read_lines"] == 0
    assert resp["has_more"] is False
    assert resp["truncated"] is False


@pytest.mark.asyncio
async def test_missing_file(workspace):
    resp = read_json(await view_file(str(workspace / "nope.txt")))
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
@pytest.mark.asyncio
async def test_invalid_params(workspace, kwargs, expect):
    resp = read_json(await view_file(**kwargs))
    assert resp["status"] == "error"
    assert expect in resp["message"]

