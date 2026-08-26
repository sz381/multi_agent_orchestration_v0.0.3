"""Tests for grep_tool matching semantics and boundary scenarios.

Test cases:
- test_grep_single_file_path:                 path pointing at a single file searches only that file
- test_grep_directory_recursive:              path as a directory recursively searches all files
- test_grep_case_sensitive_default:           case-sensitive by default (FOO does not hit)
- test_grep_case_insensitive:                 case_sensitive=False ignores case
- test_grep_glob_pattern_filter:              glob_pattern filters by filename suffix
- test_grep_glob_pattern_matches_basename:    exact-filename patterns hit same-named files in subdirectories
- test_grep_files_with_matches_mode:          files_with_matches dedupes and outputs a file list
- test_grep_count_mode:                       count mode counts per file
- test_grep_count_respects_pagination:        count mode is limited by head_limit pagination (current contract)
- test_grep_content_mode:                     content mode context-block structure and match markers
- test_grep_content_context_lines_zero:       context_lines=0 outputs only matched lines
- test_grep_content_context_lines_two:        context_lines=2 extends context with unique match
- test_grep_offset_pagination:                offset skips the first N matches
- test_grep_head_limit_truncated:             head_limit truncates with truncated=True
- test_grep_head_limit_zero:                  head_limit=0 means no limit
- test_grep_page_field:                       page field carries offset/limit
- test_grep_offset_exceeds_error:             out-of-range offset returns error
- test_grep_regex_anchors:                    regex anchor semantics (not literal matching)
- test_grep_invalid_pattern:                  parametrized: empty/blank pattern rejected
- test_grep_invalid_path:                     parametrized: empty/blank path rejected
- test_grep_invalid_glob_pattern:             parametrized: empty/blank glob_pattern rejected
- test_grep_glob_double_star:                 parametrized: ** patterns rejected
- test_grep_glob_absolute:                    parametrized: absolute-path patterns rejected
- test_grep_glob_path_traversal:              parametrized: .. traversal patterns rejected
- test_grep_glob_path_separator:              relative patterns containing / rejected
- test_grep_invalid_output_mode:              unknown output modes rejected
- test_grep_invalid_context_lines:            parametrized: out-of-range/type-error context_lines rejected
- test_grep_invalid_head_limit:               parametrized: out-of-range/type-error head_limit rejected
- test_grep_invalid_offset:                   parametrized: out-of-range/type-error offset rejected
- test_grep_invalid_regex:                    parametrized: invalid regexes rejected
- test_grep_path_outside_denied:              ../ escaping the workspace is blocked
- test_grep_path_absolute_outside_denied:     system absolute paths like /etc are blocked
- test_grep_path_does_not_exist:              nonexistent paths rejected
- test_grep_path_absolute_inside:             absolute paths inside the workspace equal relative paths
- test_grep_allow_external_reads:             external-read switch allows/blocks
- test_grep_exclude_dirs:                     excluded directories are not searched (.venv)
- test_grep_exclude_files:                    excluded files are not searched (.DS_Store)
- test_grep_max_files_truncated:              GREP_MAX_FILES truncates file collection
- test_grep_large_file_skipped:               oversized files skipped and counted in skipped_large_files
- test_grep_binary_file_skipped:              NUL sniffing silently skips binary files
- test_grep_utf16_whitelist:                  UTF-16 whitelist searches normally
- test_grep_undecodable_skipped:              decode-failure files silently skipped
- test_grep_encoding_param:                   the encoding parameter takes effect
- test_grep_multiline_dotall:                 multiline lets . match across lines
- test_grep_multiline_line_num:               cross-line matches take the start line with full line text
- test_grep_regex_timeout_breakers:           catastrophic backtracking trips the breaker for that file
- test_grep_total_timeout_partial_results:    total time-budget exhaustion returns partial results
- test_grep_total_timeout_normal:             sufficient budget does not truncate
- test_grep_empty_result:                     no-match contract (status=ok, no page)
- test_grep_empty_result_message:             empty-result message summarizes precisely
- test_grep_absolute_paths:                   all three output modes use absolute paths

Covered scenarios:
- Location: single file / directory recursion / subdirectories / hidden files / absolute paths inside the workspace
- Case sensitivity: sensitive by default, case_sensitive=False ignores
- glob_pattern: *.py suffix filtering, exact filenames (basename semantics, same-name subdirectory regression),
  ** / absolute path / .. traversal / patterns containing / — four rejection classes
- Output modes: files_with_matches (deduped), count (per-file count, in-page contract),
  content (context blocks + match markers + context_lines extension)
- Pagination: offset jumps, head_limit truncation and 0 meaning no limit, truncated marker, page field, offset out of range
- Regex semantics: anchors (^), multiline DOTALL, start-line numbers and full line text for cross-line matches
- Parameter validation: pattern/path/glob_pattern/output_mode/context_lines/head_limit/offset/regex compilation,
  numeric params explicitly exclude bool (True is an int subclass)
- Path safety: ../ and /etc out-of-bounds rejected, nonexistent rejected, allow_external_reads switch
- Exclusion rules: EXCLUDE_DIRS / EXCLUDE_FILES
- Resource limits: GREP_MAX_FILES collection truncation, GREP_MAX_FILE_SIZE per-file skip
- Encoding and binary: NUL sniffing skips, UTF-16 whitelist, decode failures silently skipped, encoding parameter
- Timeout breakers: single-line catastrophic backtracking trips the file breaker (timed_out_files), total time budget
  returns partial results (search_timed_out), neither reports an error
- Empty results: status=ok, total_matches=0, files_scanned kept, no page field
"""

import os

import pytest

from core.tools._kernel import _fs_readonly
from core.tools._kernel._fs_readonly import grep_tool
from tests.helpers import make_file, read_json, rels


@pytest.mark.asyncio
async def test_grep_single_file_path(grep_tree):
    resp = read_json(await grep_tool("foo", path="a.py"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 3
    assert resp["files_scanned"] == 1
    assert resp["total_files"] == 1
    assert rels(grep_tree, resp["files"]) == {"a.py"}


@pytest.mark.asyncio
async def test_grep_directory_recursive(grep_tree):
    resp = read_json(await grep_tool("foo"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 8
    assert rels(grep_tree, resp["files"]) == {
        "a.py", "b.py", "sub/c.py", "deep/nested/e.py", ".hidden.txt",
    }


@pytest.mark.asyncio
async def test_grep_case_sensitive_default(grep_tree):
    resp = read_json(await grep_tool("foo", path="a.py"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 3

    resp = read_json(await grep_tool("FOO", path="a.py"))
    assert resp["total_matches"] == 1


@pytest.mark.asyncio
async def test_grep_case_insensitive(grep_tree):
    resp = read_json(await grep_tool("foo", case_sensitive=False, output_mode="count"))
    assert resp["status"] == "ok"
    assert resp["total_occurrences"] == 9
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    assert resp["results"][abs_a] == 4


@pytest.mark.asyncio
async def test_grep_glob_pattern_filter(grep_tree):
    resp = read_json(await grep_tool("foo", glob_pattern="*.py"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 7
    assert rels(grep_tree, resp["files"]) == {
        "a.py", "b.py", "sub/c.py", "deep/nested/e.py",
    }


@pytest.mark.asyncio
async def test_grep_glob_pattern_matches_basename(grep_tree):
    resp = read_json(await grep_tool("foo", glob_pattern="c.py"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 1
    assert rels(grep_tree, resp["files"]) == {"sub/c.py"}


@pytest.mark.asyncio
async def test_grep_files_with_matches_mode(grep_tree):
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
    resp = read_json(await grep_tool("foo", path="a.py", output_mode="count", head_limit=2))
    assert resp["status"] == "ok"
    assert resp["total_occurrences"] == 2
    assert resp["total_matches"] == 3
    assert resp["truncated"] is True
    assert resp["page"] == {"offset": 0, "limit": 2}


@pytest.mark.asyncio
async def test_grep_content_mode(grep_tree):
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
    resp = read_json(await grep_tool("foo", path="a.py", output_mode="content", head_limit=2))
    assert resp["status"] == "ok"
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    assert len(resp["results"][abs_a]) == 2
    assert resp["truncated"] is True
    assert resp["total_matches"] == 3


@pytest.mark.asyncio
async def test_grep_head_limit_zero(grep_tree):
    resp = read_json(await grep_tool("foo", path="a.py", output_mode="content", head_limit=0))
    assert resp["status"] == "ok"
    abs_a = os.path.realpath(str(grep_tree / "a.py"))
    assert len(resp["results"][abs_a]) == 3
    assert resp["truncated"] is False


@pytest.mark.asyncio
async def test_grep_page_field(grep_tree):
    resp = read_json(await grep_tool("foo", path="a.py"))
    assert resp["page"] == {"offset": 0, "limit": 200}

    resp = read_json(await grep_tool("foo", path="a.py", head_limit=5, offset=1))
    assert resp["page"] == {"offset": 1, "limit": 5}


@pytest.mark.asyncio
async def test_grep_offset_exceeds_error(grep_tree):
    resp = read_json(await grep_tool("foo", path="a.py", offset=3))
    assert resp["status"] == "error"
    assert "offset 3 exceeds total matches 3" in resp["message"]


@pytest.mark.asyncio
async def test_grep_regex_anchors(grep_tree):
    resp = read_json(await grep_tool("^foo"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 6


@pytest.mark.parametrize("pattern", ["", "   "])
@pytest.mark.asyncio
async def test_grep_invalid_pattern(grep_tree, pattern):
    resp = read_json(await grep_tool(pattern))
    assert resp["status"] == "error"
    assert "pattern must not be empty" in resp["message"]


@pytest.mark.parametrize("path", ["", "   "])
@pytest.mark.asyncio
async def test_grep_invalid_path(grep_tree, path):
    resp = read_json(await grep_tool("foo", path=path))
    assert resp["status"] == "error"
    assert "path must not be empty" in resp["message"]


@pytest.mark.parametrize("glob_pattern", ["", "   "])
@pytest.mark.asyncio
async def test_grep_invalid_glob_pattern(grep_tree, glob_pattern):
    resp = read_json(await grep_tool("foo", glob_pattern=glob_pattern))
    assert resp["status"] == "error"
    assert "glob_pattern must not be empty" in resp["message"]


@pytest.mark.parametrize("glob_pattern", ["**", "**/*.py", "a/**"])
@pytest.mark.asyncio
async def test_grep_glob_double_star(grep_tree, glob_pattern):
    resp = read_json(await grep_tool("foo", glob_pattern=glob_pattern))
    assert resp["status"] == "error"
    assert "does not support '**'" in resp["message"]


@pytest.mark.parametrize("glob_pattern", ["/etc/*.py", "///"])
@pytest.mark.asyncio
async def test_grep_glob_absolute(grep_tree, glob_pattern):
    resp = read_json(await grep_tool("foo", glob_pattern=glob_pattern))
    assert resp["status"] == "error"
    assert "absolute paths are not allowed" in resp["message"]


@pytest.mark.parametrize("glob_pattern", ["../x/*.py", "a/../b.py"])
@pytest.mark.asyncio
async def test_grep_glob_path_traversal(grep_tree, glob_pattern):
    resp = read_json(await grep_tool("foo", glob_pattern=glob_pattern))
    assert resp["status"] == "error"
    assert "must not contain '..'" in resp["message"]


@pytest.mark.asyncio
async def test_grep_glob_path_separator(grep_tree):
    resp = read_json(await grep_tool("foo", glob_pattern="src/*.py"))
    assert resp["status"] == "error"
    assert "path separators are not allowed" in resp["message"]
    assert "use the path parameter" in resp["message"]


@pytest.mark.asyncio
async def test_grep_invalid_output_mode(grep_tree):
    resp = read_json(await grep_tool("foo", output_mode="unknown"))
    assert resp["status"] == "error"
    assert "Unknown output_mode" in resp["message"]
    assert "files_with_matches" in resp["message"]


@pytest.mark.parametrize("context_lines", [-1, 11, True, 1.5, "2"])
@pytest.mark.asyncio
async def test_grep_invalid_context_lines(grep_tree, context_lines):
    resp = read_json(await grep_tool("foo", context_lines=context_lines))
    assert resp["status"] == "error"
    assert "context_lines must be an integer between 0 and 10" in resp["message"]


@pytest.mark.parametrize("head_limit", [-1, 1001, True, 1.5])
@pytest.mark.asyncio
async def test_grep_invalid_head_limit(grep_tree, head_limit):
    resp = read_json(await grep_tool("foo", head_limit=head_limit))
    assert resp["status"] == "error"
    assert "head_limit must be an integer between 0 and 1000" in resp["message"]


@pytest.mark.parametrize("offset", [-1, True, 1.5])
@pytest.mark.asyncio
async def test_grep_invalid_offset(grep_tree, offset):
    resp = read_json(await grep_tool("foo", offset=offset))
    assert resp["status"] == "error"
    assert "offset must be a non-negative integer" in resp["message"]


@pytest.mark.parametrize("pattern", ["(", "[a", "*a"])
@pytest.mark.asyncio
async def test_grep_invalid_regex(grep_tree, pattern):
    resp = read_json(await grep_tool(pattern))
    assert resp["status"] == "error"
    assert "Invalid regex pattern" in resp["message"]


@pytest.mark.asyncio
async def test_grep_path_outside_denied(grep_tree):
    resp = read_json(await grep_tool("foo", path="../outside"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


@pytest.mark.asyncio
async def test_grep_path_absolute_outside_denied(grep_tree):
    resp = read_json(await grep_tool("foo", path="/etc"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


@pytest.mark.asyncio
async def test_grep_path_does_not_exist(grep_tree):
    resp = read_json(await grep_tool("foo", path="nope"))
    assert resp["status"] == "error"
    assert "does not exist" in resp["message"]


@pytest.mark.asyncio
async def test_grep_path_absolute_inside(grep_tree):
    abs_ws = os.path.realpath(str(grep_tree))
    resp = read_json(await grep_tool("foo", path=abs_ws))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 8


@pytest.mark.asyncio
async def test_grep_allow_external_reads(grep_tree):
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
    resp = read_json(await grep_tool("foo", output_mode="count"))
    got = rels(grep_tree, list(resp["results"].keys()))
    assert ".venv/f.py" not in got


@pytest.mark.asyncio
async def test_grep_exclude_files(grep_tree):
    resp = read_json(await grep_tool("foo"))
    got = rels(grep_tree, resp["files"])
    assert ".DS_Store" not in got
    assert resp["files_scanned"] == 6


@pytest.mark.asyncio
async def test_grep_max_files_truncated(grep_tree, monkeypatch):
    monkeypatch.setattr(_fs_readonly, "GREP_MAX_FILES", 2)
    resp = read_json(await grep_tool("foo"))
    assert resp["status"] == "ok"
    assert resp["files_scanned"] == 2
    assert resp["files_truncated"] is True
    assert 0 < resp["total_matches"] < 8


@pytest.mark.asyncio
async def test_grep_large_file_skipped(grep_tree, monkeypatch):
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
    (grep_tree / "bin.dat").write_bytes(b"foo\x00bar\n")

    resp = read_json(await grep_tool("foo"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 8
    got = rels(grep_tree, resp["files"])
    assert "bin.dat" not in got


@pytest.mark.asyncio
async def test_grep_utf16_whitelist(grep_tree):
    (grep_tree / "utf16.txt").write_text("foo\n", encoding="utf-16")

    resp = read_json(await grep_tool("foo", path="utf16.txt", encoding="utf-16"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 1
    assert rels(grep_tree, resp["files"]) == {"utf16.txt"}


@pytest.mark.asyncio
async def test_grep_undecodable_skipped(grep_tree):
    (grep_tree / "bad.bin").write_bytes(b"\xff\xfe\xfa\xfbfoo\n")

    resp = read_json(await grep_tool("foo"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 8
    got = rels(grep_tree, resp["files"])
    assert "bad.bin" not in got


@pytest.mark.asyncio
async def test_grep_encoding_param(grep_tree):
    (grep_tree / "latin1.txt").write_bytes("caf\xe9 foo\n".encode("latin-1"))

    resp = read_json(await grep_tool("foo", path="latin1.txt"))
    assert resp["total_matches"] == 0

    resp = read_json(await grep_tool("foo", path="latin1.txt", encoding="latin-1"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 1


@pytest.mark.asyncio
async def test_grep_multiline_dotall(grep_tree):

    (grep_tree / "ml.py").write_text("xxxbar\nhello foo\n", encoding="utf-8")

    resp = read_json(await grep_tool("bar.*foo", path="ml.py"))
    assert resp["total_matches"] == 0

    resp = read_json(await grep_tool("bar.*foo", path="ml.py", multiline=True))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 1


@pytest.mark.asyncio
async def test_grep_multiline_line_num(grep_tree):
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
    (grep_tree / "t.py").write_text("a" * 40 + "b\n", encoding="utf-8")

    resp = read_json(await grep_tool("(a|aa)+$", path="t.py"))
    assert resp["status"] == "ok"
    assert resp["total_matches"] == 0
    assert resp["timed_out_files"] == 1
    assert "1 files timed out" in resp["message"]


@pytest.mark.asyncio
async def test_grep_total_timeout_partial_results(grep_tree, monkeypatch):
    monkeypatch.setattr(_fs_readonly, "GREP_TOTAL_TIMEOUT_SECONDS", 0.01)
    for i in range(5):
        make_file(grep_tree, f"big{i}.py", 20000)

    resp = read_json(await grep_tool("x"))
    assert resp["status"] == "ok"
    assert resp["search_timed_out"] is True
    assert 0 < resp["total_matches"] < 100000


@pytest.mark.asyncio
async def test_grep_total_timeout_normal(grep_tree):
    for i in range(5):
        make_file(grep_tree, f"big{i}.py", 20000)

    resp = read_json(await grep_tool("x"))
    assert resp["status"] == "ok"
    assert resp["search_timed_out"] is False
    assert resp["total_matches"] == 100000


@pytest.mark.asyncio
async def test_grep_empty_result(grep_tree):
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
    resp = read_json(await grep_tool("xyz"))
    assert resp["message"] == "No matches for 'xyz' in 6 files"


@pytest.mark.asyncio
async def test_grep_absolute_paths(grep_tree):
    abs_ws = os.path.realpath(str(grep_tree))

    resp = read_json(await grep_tool("foo"))
    assert all(f.startswith(abs_ws) for f in resp["files"])

    resp = read_json(await grep_tool("foo", output_mode="count"))
    assert all(k.startswith(abs_ws) for k in resp["results"])

    resp = read_json(await grep_tool("foo", output_mode="content"))
    assert all(k.startswith(abs_ws) for k in resp["results"])
