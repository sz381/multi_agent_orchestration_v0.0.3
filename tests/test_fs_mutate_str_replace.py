"""Comprehensive tests for str_replace: parameter validation, path safety, matching semantics, replacement semantics, atomic writes and the response contract.

Test cases:
- test_str_replace_invalid_file_path:              parametrized: empty/blank/non-str file_path rejected
- test_str_replace_invalid_old_str_type:           parametrized: non-str old_str rejected
- test_str_replace_empty_old_str:                  empty-string old_str rejected
- test_str_replace_whitespace_old_str_valid:       whitespace old_str is legal (no-strip design locked)
- test_str_replace_invalid_new_str_type:           parametrized: non-str new_str rejected
- test_str_replace_empty_new_str_deletes:          empty-string new_str means deletion
- test_str_replace_unknown_encoding:               unknown encoding rejected
- test_str_replace_workspace_not_configured:       RuntimeError when the workspace is not configured
- test_str_replace_relative_path:                  relative paths resolve to absolute paths inside the workspace
- test_str_replace_absolute_path_inside:           absolute paths inside the workspace equal relative paths
- test_str_replace_home_expansion:                 ~ expands to a path under HOME
- test_str_replace_parent_traversal_denied:        ../ escaping the workspace is blocked
- test_str_replace_absolute_outside_denied:        system absolute paths (e.g. /etc/hosts) blocked
- test_str_replace_prefix_trap_denied:             same-prefix sibling directories blocked
- test_str_replace_nonexistent_file:               nonexistent files rejected
- test_str_replace_path_is_directory:              paths pointing at directories rejected
- test_str_replace_subdir_file:                    files in subdirectories replace normally
- test_str_replace_undecodable_file:               decode failure rejected with an encoding hint
- test_str_replace_permission_denied_read:         read-permission denial rejected
- test_str_replace_gbk_encoding:                   the encoding parameter decodes with the given encoding
- test_str_replace_exceeds_max_size:               over MAX_WRITE_SIZE rejected
- test_str_replace_at_max_size_boundary:           exactly MAX_WRITE_SIZE passes (boundary)
- test_str_replace_single_match_success:           a single exact match replaces successfully
- test_str_replace_text_not_found:                 missing old_str errors with a view_file hint
- test_str_replace_multiple_matches_rejected:      multiple matches without replace_all rejected
- test_str_replace_replace_all:                    replace_all replaces everything
- test_str_replace_replace_all_single:             replace_all marks single matches as ALL too
- test_str_replace_unchanged_identical:            old_str == new_str returns UNCHANGED
- test_str_replace_unchanged_multiple_matches:     UNCHANGED takes priority over the multiple-match check (count kept)
- test_str_replace_case_sensitive:                 matching is case-sensitive
- test_str_replace_multiline_old_str:              exact matching across lines
- test_str_replace_unicode:                        Chinese content replacement
- test_str_replace_digit_text:                     numeric text (string form) replacement
- test_str_replace_diff_count_single:              diff.count is 1 when replace_all=False
- test_str_replace_new_str_with_newlines:          new_str with newlines writes multi-line content
- test_str_replace_surrounding_preserved:          replacement does not break surrounding context
- test_str_replace_delete_content:                 file content under deletion semantics
- test_str_replace_diff_truncation:                overlong old/new truncated, short text kept as-is
- test_str_replace_permissions_preserved:          file permissions preserved after replacement
- test_str_replace_no_temp_left:                   no temp files left behind
- test_str_replace_inode_replaced:                 os.replace swaps the inode atomically
- test_str_replace_encoding_failure_atomic:        the original content is unchanged on encoding failure (atomicity)
- test_str_replace_readonly_dir_graceful:          read-only directories return error gracefully (no crash)
- test_str_replace_success_contract:               ok response field contract (status/path/diff/message)
- test_str_replace_error_contract:                 parametrized: error response has only status/message
- test_str_replace_empty_file:                     empty-file replacement reports not found

Covered scenarios:
- Parameter validation: file_path/old_str/new_str empty, blank, non-str (None/number/list) four rejection classes;
  whitespace old_str is legal (exact text replacement without strip, unlike regex pattern semantics)
- Path safety: relative/absolute/~/subdirectory four legal forms; ../ and system absolute paths and same-prefix
  sibling directories three out-of-bounds rejections (safe_root trailing separator prevents prefix traps); nonexistent/directory forms rejected
- Read stage: invalid encoding bytes, permission denial, encoding parameter decodes with the given encoding
- Size limits: over MAX_WRITE_SIZE rejected, exactly at passes (constant isolated via monkeypatch)
- Matching semantics: single success, not found, multiple matches without replace_all rejected, replace_all full replacement,
  old == new UNCHANGED (taking priority over the multiple-match check when applicable), case-sensitive, multi-line, Chinese, digits
- Replacement semantics: diff.count contract, new_str with newlines, surrounding context preserved, deletion semantics, diff truncation
- Atomic writes: permissions preserved (chmod restored), no temp leftovers, inode replacement, content unchanged on encoding failure,
  read-only directories degrade gracefully (mkstemp covered by exception fallback)
- Response contract: ok branch fixed fields (status/message/path/diff{old,new,count,replace_all}), error branch only status/message
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
    r = read_json(await str_replace(bad_path, "foo", "bar"))
    assert r["status"] == "error"
    assert r["message"] == "file_path must be a non-empty string."


@pytest.mark.parametrize("bad_old", [None, 123, ["foo"]])
@pytest.mark.asyncio
async def test_str_replace_invalid_old_str_type(workspace, bad_old):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", bad_old, "bar"))
    assert r["status"] == "error"
    assert r["message"] == "old_str must be a non-empty string."


@pytest.mark.asyncio
async def test_str_replace_empty_old_str(workspace):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "", "bar"))
    assert r["status"] == "error"
    assert r["message"] == "old_str must be a non-empty string."


@pytest.mark.asyncio
async def test_str_replace_whitespace_old_str_valid(workspace):
    fp = make_text_file(workspace, "a.py", "foo  bar\n")
    r = read_json(await str_replace("a.py", "  ", " "))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "foo bar\n"


@pytest.mark.parametrize("bad_new", [None, 123])
@pytest.mark.asyncio
async def test_str_replace_invalid_new_str_type(workspace, bad_new):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", bad_new))
    assert r["status"] == "error"
    assert r["message"] == "new_str must be a string."


@pytest.mark.asyncio
async def test_str_replace_empty_new_str_deletes(workspace):
    fp = make_text_file(workspace, "a.py", "foo bar\n")
    r = read_json(await str_replace("a.py", "foo ", ""))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "bar\n"


@pytest.mark.asyncio
async def test_str_replace_unknown_encoding(workspace):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar", encoding="not-a-codec"))
    assert r["status"] == "error"
    assert "Unknown encoding" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_workspace_not_configured(workspace, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", None)
    with pytest.raises(RuntimeError, match="WORKSPACE_DIR is not configured"):
        await str_replace("a.py", "foo", "bar")


@pytest.mark.asyncio
async def test_str_replace_relative_path(workspace):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")


@pytest.mark.asyncio
async def test_str_replace_absolute_path_inside(workspace):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace(str(workspace / "a.py"), "foo", "bar"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")


@pytest.mark.asyncio
async def test_str_replace_home_expansion(workspace, monkeypatch):
    monkeypatch.setenv("HOME", str(workspace))
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("~/a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")


@pytest.mark.asyncio
async def test_str_replace_parent_traversal_denied(workspace):
    r = read_json(await str_replace("../escape.py", "foo", "bar"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_absolute_outside_denied(workspace):
    r = read_json(await str_replace("/etc/hosts", "127.0.0.1", "1.1.1.1"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_prefix_trap_denied(workspace):
    evil = workspace.parent / (workspace.name + "_evil")
    evil.mkdir(exist_ok=True)
    (evil / "a.py").write_text("foo\n", encoding="utf-8")
    r = read_json(await str_replace(str(evil / "a.py"), "foo", "bar"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_nonexistent_file(workspace):
    r = read_json(await str_replace("missing.py", "foo", "bar"))
    assert r["status"] == "error"
    assert "does not exist" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_path_is_directory(workspace):
    (workspace / "sub").mkdir()
    r = read_json(await str_replace("sub", "foo", "bar"))
    assert r["status"] == "error"
    assert "is a directory" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_subdir_file(workspace):
    fp = make_text_file(workspace, "sub/a.py", "foo\n")
    r = read_json(await str_replace("sub/a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "bar\n"


@pytest.mark.asyncio
async def test_str_replace_undecodable_file(workspace):
    fp = workspace / "bin.dat"
    fp.write_bytes(b"\xff\xfe\x00A")
    r = read_json(await str_replace("bin.dat", "foo", "bar"))
    assert r["status"] == "error"
    assert "cannot be decoded as utf-8" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_permission_denied_read(workspace):
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
    fp = workspace / "gbk.txt"
    fp.write_bytes("你好 foo\n".encode("gbk"))
    r = read_json(await str_replace("gbk.txt", "你好", "再见", encoding="gbk"))
    assert r["status"] == "ok"
    assert fp.read_bytes() == "再见 foo\n".encode("gbk")


@pytest.mark.asyncio
async def test_str_replace_exceeds_max_size(workspace, monkeypatch):
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    make_text_file(workspace, "a.py", "x" * 11)
    r = read_json(await str_replace("a.py", "x", "y"))
    assert r["status"] == "error"
    assert "exceeds" in r["message"]
    assert "limit" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_at_max_size_boundary(workspace, monkeypatch):
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    make_text_file(workspace, "a.py", "x" * 9 + "!")
    r = read_json(await str_replace("a.py", "!", "?"))
    assert r["status"] == "ok"


@pytest.mark.asyncio
async def test_str_replace_single_match_success(workspace):
    fp = make_text_file(workspace, "a.py", "foo bar\n")
    r = read_json(await str_replace("a.py", "foo", "FOO"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[REPLACED]")
    assert fp.read_text(encoding="utf-8") == "FOO bar\n"


@pytest.mark.asyncio
async def test_str_replace_text_not_found(workspace):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "zzz", "bar"))
    assert r["status"] == "error"
    assert "Text not found" in r["message"]
    assert "view_file" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_multiple_matches_rejected(workspace):
    make_text_file(workspace, "a.py", "foo foo foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "error"
    assert "3 occurrences" in r["message"]
    assert "replace_all=True" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_replace_all(workspace):
    fp = make_text_file(workspace, "a.py", "foo foo foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar", replace_all=True))
    assert r["status"] == "ok"
    assert r["diff"]["count"] == 3
    assert fp.read_text(encoding="utf-8") == "bar bar bar\n"


@pytest.mark.asyncio
async def test_str_replace_replace_all_single(workspace):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar", replace_all=True))
    assert r["status"] == "ok"
    assert r["message"].startswith("[REPLACED ALL]")
    assert r["diff"]["count"] == 1


@pytest.mark.asyncio
async def test_str_replace_unchanged_identical(workspace):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "foo"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[UNCHANGED]")
    assert r["path"] == str(workspace.resolve() / "a.py")
    assert r["diff"] == {"old": "foo", "new": "foo", "count": 1, "replace_all": False}


@pytest.mark.asyncio
async def test_str_replace_unchanged_multiple_matches(workspace):
    make_text_file(workspace, "a.py", "foo foo\n")
    r = read_json(await str_replace("a.py", "foo", "foo"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[UNCHANGED]")
    assert r["diff"]["count"] == 2


@pytest.mark.asyncio
async def test_str_replace_case_sensitive(workspace):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "Foo", "bar"))
    assert r["status"] == "error"
    assert "Text not found" in r["message"]


@pytest.mark.asyncio
async def test_str_replace_multiline_old_str(workspace):
    fp = make_text_file(workspace, "a.py", "aaa\nbar\nfoo\nbbb\n")
    r = read_json(await str_replace("a.py", "bar\nfoo", "X"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "aaa\nX\nbbb\n"


@pytest.mark.asyncio
async def test_str_replace_unicode(workspace):
    fp = make_text_file(workspace, "a.py", "你好世界\n")
    r = read_json(await str_replace("a.py", "你好", "再见"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "再见世界\n"


@pytest.mark.asyncio
async def test_str_replace_digit_text(workspace):
    fp = make_text_file(workspace, "a.py", "version = 42\n")
    r = read_json(await str_replace("a.py", "42", "43"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "version = 43\n"


@pytest.mark.asyncio
async def test_str_replace_diff_count_single(workspace):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert r["diff"]["count"] == 1
    assert r["diff"]["replace_all"] is False


@pytest.mark.asyncio
async def test_str_replace_new_str_with_newlines(workspace):
    fp = make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "foo\nbar"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "foo\nbar\n"


@pytest.mark.asyncio
async def test_str_replace_surrounding_preserved(workspace):
    fp = make_text_file(workspace, "a.py", "aaa foo bbb\n")
    r = read_json(await str_replace("a.py", "foo", "X"))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "aaa X bbb\n"


@pytest.mark.asyncio
async def test_str_replace_delete_content(workspace):
    fp = make_text_file(workspace, "a.py", "foo bar baz\n")
    r = read_json(await str_replace("a.py", "bar ", ""))
    assert r["status"] == "ok"
    assert fp.read_text(encoding="utf-8") == "foo baz\n"


@pytest.mark.asyncio
async def test_str_replace_diff_truncation(workspace):
    long_old = "x" * 600
    long_new = "y" * 600
    fp = make_text_file(workspace, "b.py", long_old + "\n")
    r = read_json(await str_replace("b.py", long_old, long_new))
    assert r["status"] == "ok"
    assert r["diff"]["old"] == "x" * 500 + "\n... [truncated]"
    assert r["diff"]["new"] == "y" * 500 + "\n... [truncated]"
    assert fp.read_text(encoding="utf-8") == long_new + "\n"
    r = read_json(await str_replace("b.py", "y\n", "zz\n"))
    assert r["diff"]["old"] == "y\n"
    assert r["diff"]["new"] == "zz\n"


@pytest.mark.asyncio
async def test_str_replace_permissions_preserved(workspace):
    fp = make_text_file(workspace, "a.py", "foo\n")
    os.chmod(fp, 0o640)
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert os.stat(fp).st_mode & 0o777 == 0o640


@pytest.mark.asyncio
async def test_str_replace_no_temp_left(workspace):
    make_text_file(workspace, "a.py", "foo\n")
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.py"]


@pytest.mark.asyncio
async def test_str_replace_inode_replaced(workspace):
    fp = make_text_file(workspace, "a.py", "foo\n")
    ino_before = os.stat(fp).st_ino
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "ok"
    assert os.stat(fp).st_ino != ino_before


@pytest.mark.asyncio
async def test_str_replace_encoding_failure_atomic(workspace):
    fp = make_text_file(workspace, "a.py", "foo bar\n")
    r = read_json(await str_replace("a.py", "foo", "你好", encoding="ascii"))
    assert r["status"] == "error"
    assert "not encodable as ascii" in r["message"]
    assert fp.read_text(encoding="utf-8") == "foo bar\n"


@pytest.mark.asyncio
async def test_str_replace_readonly_dir_graceful(workspace):
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
    make_text_file(workspace, "a.py", "foo bar\n")
    r = read_json(await str_replace("a.py", "foo", "X"))
    assert set(r.keys()) == {"status", "message", "path", "diff"}
    assert r["status"] == "ok"
    assert set(r["diff"].keys()) == {"old", "new", "count", "replace_all"}


@pytest.mark.parametrize("scenario", ["not_found", "traversal", "nonexistent"])
@pytest.mark.asyncio
async def test_str_replace_error_contract(workspace, scenario):
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
    make_text_file(workspace, "a.py", "")
    r = read_json(await str_replace("a.py", "foo", "bar"))
    assert r["status"] == "error"
    assert "Text not found" in r["message"]
