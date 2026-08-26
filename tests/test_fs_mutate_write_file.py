"""Comprehensive tests for write_file: parameter validation, path safety, create/overwrite semantics, atomic writes and the response contract.

Test cases:
- test_write_file_invalid_file_path:                  parametrized: empty/blank/non-str file_path rejected
- test_write_file_invalid_content_type:               parametrized: non-str content rejected (including the empty-value-swallowing regression)
- test_write_file_empty_content_valid:                empty-string content writes an empty file (legal)
- test_write_file_unknown_encoding:                   unknown encoding rejected
- test_write_file_encoding_non_str:                   parametrized: non-str encoding rejected (TypeError fallback)
- test_write_file_workspace_not_configured:           RuntimeError when the workspace is not configured
- test_write_file_exceeds_max_size:                   over MAX_WRITE_SIZE rejected
- test_write_file_at_max_size_boundary:               exactly MAX_WRITE_SIZE passes (boundary)
- test_write_file_multibyte_bytes_semantics:          size is measured in bytes (multi-byte chars over the limit)
- test_write_file_relative_path:                      relative paths resolve to absolute paths inside the workspace
- test_write_file_absolute_path_inside:               absolute paths inside the workspace equal relative paths
- test_write_file_home_expansion:                     ~ expands to a path under HOME
- test_write_file_parent_traversal_denied:            ../ escaping the workspace is blocked
- test_write_file_absolute_outside_denied:            system absolute paths (e.g. /etc/hosts) blocked
- test_write_file_prefix_trap_denied:                 same-prefix sibling directories blocked
- test_write_file_symlink_outside_denied:             symlinks pointing outside the workspace blocked
- test_write_file_symlink_inside_allowed:             symlinks pointing inside the workspace write the real target
- test_write_file_create_new_file:                    creates a new file (CREATED + content + path)
- test_write_file_create_nested_dirs:                 deep parent directories created automatically
- test_write_file_create_absolute_path:               creation via an absolute path
- test_write_file_create_umask_mode:                  new-file permissions = 0o666 & ~umask (0600 trap regression)
- test_write_file_create_empty_file:                  writes an empty file (0 lines)
- test_write_file_create_whitespace_content:          pure-whitespace content kept byte-for-byte (no-strip design locked)
- test_write_file_overwrite_existing:                 overwrites an existing file (OVERWRITTEN + diff)
- test_write_file_overwrite_keeps_mode:               overwrite keeps the original permissions
- test_write_file_overwrite_readonly_file:            overwriting a read-only file succeeds and keeps permissions
- test_write_file_unchanged_same_content:             identical content returns UNCHANGED (path + diff contract)
- test_write_file_unchanged_mtime_inode:              UNCHANGED does not touch the file (mtime/inode unchanged)
- test_write_file_empty_file_unchanged:               empty file written with an empty string returns UNCHANGED
- test_write_file_overwrite_large_old_file:           over-limit originals are read with a length cap and overwritten correctly
- test_write_file_overwrite_undecodable_not_blocking: overwriting an undecodable file does not block (diff.old is empty)
- test_write_file_overwrite_undecodable_empty:        read failure does not misjudge UNCHANGED (cleared successfully)
- test_write_file_target_is_directory:                a target path that is a directory is rejected
- test_write_file_parent_path_is_file:                makedirs fallback when the parent path is a file
- test_write_file_readonly_dir_graceful:              read-only directories return error gracefully (no crash)
- test_write_file_traversal_no_side_effect:           out-of-bounds paths produce no side effects
- test_write_file_failed_write_no_temp:               failed writes leave no temp files
- test_write_file_gbk_write_read:                     gbk-encoded write and read-back
- test_write_file_latin1_write:                       latin-1-encoded write
- test_write_file_ascii_unencodable_rejected:         unencodable content intercepted early without creating a file
- test_write_file_diff_truncation:                    overlong old/new truncated with markers, short text kept as-is
- test_write_file_diff_at_boundary:                   exactly MAX_DIFF_SIZE is not truncated (boundary)
- test_write_file_line_count_variants:                parametrized: all boundaries of the message line-count calculation
- test_write_file_success_contract:                   ok response field contract (no count/replace_all)
- test_write_file_error_contract:                     parametrized: error response has only status/message
- test_write_file_lock_shared_same_path:              same path shares the same lock object (concurrency prerequisite)
- test_write_file_inode_replaced:                     overwrite swaps the inode atomically
- test_write_file_no_temp_left:                       no temp files left after a successful write
- test_write_file_special_chars_fidelity:             special-character content kept fully intact

Covered scenarios:
- Parameter validation: file_path empty/blank/non-str four rejection classes; non-str content rejected (None/0/False/[]
  were the empty-value-swallowing regression silently writing empty files); empty string legally writes an empty file; unknown encoding and
  non-str encoding (TypeError used to crash) two rejection classes; RuntimeError when the workspace is not configured
- Size limits: over MAX_WRITE_SIZE rejected, exactly at passes, size measured in bytes
  (a 4-char Chinese string is 12 bytes and over the limit, distinct from str_replace char semantics)
- Path safety: relative/absolute/~/subdirectory four legal forms; ../ and system absolute paths and same-prefix sibling directories
  and symlink out-of-bounds four rejections (symlink resolved by realpath then blocked); workspace-internal symlinks
  write the real target and the link itself is kept
- Create semantics: CREATED marker, deep parent directories auto-created, new-file permissions 0o666 & ~umask
  (mkstemp 0600 trap regression), empty files, pure-whitespace content kept without strip
- Overwrite semantics: OVERWRITTEN marker with diff.old/new, overwrite keeps original permissions (including read-only files),
  UNCHANGED short-circuit (mtime/inode unchanged), empty file with empty string UNCHANGED, over-limit originals read with a cap,
  overwriting undecodable files does not block (diff.old empty) and does not misjudge UNCHANGED
- Error paths: target is a directory, parent path is a file (makedirs fallback), read-only directory (mkstemp fallback
  + permission restore), out-of-bounds no side effects, failed writes leave no temp files
- Encoding: gbk / latin-1 write and read-back, unencodable content intercepted early (before writing)
- diff truncation: over MAX_DIFF_SIZE (50) truncated with "\n... [truncated]", exactly 50 not truncated
- Response contract: ok branch fixed fields (status/message/path/diff{old,new}, no count/replace_all),
  error branch only status/message; message prefixes [CREATED]/[OVERWRITTEN]/[UNCHANGED] with line counts
- Atomic writes: inode replacement, no temp leftovers, per-path singleton lock objects (concurrency test prerequisite)
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
    r = read_json(await write_file(bad_path, "foo"))
    assert r["status"] == "error"
    assert r["message"] == "file_path must be a non-empty string."


@pytest.mark.parametrize("bad_content", [None, 0, False, [], ["foo"], 3.14])
@pytest.mark.asyncio
async def test_write_file_invalid_content_type(workspace, bad_content):
    r = read_json(await write_file("a.py", bad_content))
    assert r["status"] == "error"
    assert r["message"] == "content must be a string."


@pytest.mark.asyncio
async def test_write_file_empty_content_valid(workspace):
    r = read_json(await write_file("empty.txt", ""))
    assert r["status"] == "ok"
    assert r["message"].startswith("[CREATED]")
    assert "(0 lines)" in r["message"]
    assert os.path.getsize(r["path"]) == 0


@pytest.mark.asyncio
async def test_write_file_unknown_encoding(workspace):
    r = read_json(await write_file("a.py", "foo", encoding="not-a-codec"))
    assert r["status"] == "error"
    assert "Unknown encoding" in r["message"]


@pytest.mark.parametrize("bad_encoding", [123, None, ["utf-8"], 3.14])
@pytest.mark.asyncio
async def test_write_file_encoding_non_str(workspace, bad_encoding):
    r = read_json(await write_file("a.py", "foo", encoding=bad_encoding))
    assert r["status"] == "error"
    assert "Unknown encoding" in r["message"]


@pytest.mark.asyncio
async def test_write_file_workspace_not_configured(workspace, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", None)
    with pytest.raises(RuntimeError, match="WORKSPACE_DIR is not configured"):
        await write_file("a.py", "foo")


@pytest.mark.asyncio
async def test_write_file_exceeds_max_size(workspace, monkeypatch):
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    r = read_json(await write_file("big.txt", "x" * 11))
    assert r["status"] == "error"
    assert "exceeds" in r["message"]
    assert "limit" in r["message"]


@pytest.mark.asyncio
async def test_write_file_at_max_size_boundary(workspace, monkeypatch):
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    r = read_json(await write_file("ok.txt", "x" * 10))
    assert r["status"] == "ok"
    assert (workspace / "ok.txt").read_text(encoding="utf-8") == "x" * 10


@pytest.mark.asyncio
async def test_write_file_multibyte_bytes_semantics(workspace, monkeypatch):
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    r = read_json(await write_file("mb.txt", "中" * 4))
    assert r["status"] == "error"
    r = read_json(await write_file("mb.txt", "中" * 3))
    assert r["status"] == "ok"


@pytest.mark.asyncio
async def test_write_file_relative_path(workspace):
    r = read_json(await write_file("a.py", "foo"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")


@pytest.mark.asyncio
async def test_write_file_absolute_path_inside(workspace):
    r = read_json(await write_file(str(workspace / "a.py"), "foo"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")
    assert (workspace / "a.py").read_text(encoding="utf-8") == "foo"


@pytest.mark.asyncio
async def test_write_file_home_expansion(workspace, monkeypatch):
    monkeypatch.setenv("HOME", str(workspace))
    r = read_json(await write_file("~/a.py", "foo"))
    assert r["status"] == "ok"
    assert r["path"] == str(workspace.resolve() / "a.py")


@pytest.mark.asyncio
async def test_write_file_parent_traversal_denied(workspace):
    r = read_json(await write_file("../escape.py", "foo"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_write_file_absolute_outside_denied(workspace):
    r = read_json(await write_file("/etc/hosts", "foo"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_write_file_prefix_trap_denied(workspace):
    evil = workspace.parent / (workspace.name + "_evil")
    evil.mkdir(exist_ok=True)
    r = read_json(await write_file(str(evil / "a.py"), "foo"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_write_file_symlink_outside_denied(workspace):
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
    make_text_file(workspace, "target.txt", "old")
    link = workspace / "link.txt"
    link.symlink_to(workspace / "target.txt")
    r = read_json(await write_file("link.txt", "new"))
    assert r["status"] == "ok"
    assert link.is_symlink()
    assert (workspace / "target.txt").read_text(encoding="utf-8") == "new"


@pytest.mark.asyncio
async def test_write_file_create_new_file(workspace):
    r = read_json(await write_file("a.py", "hello\nworld\n"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[CREATED]")
    assert r["path"] == str(workspace.resolve() / "a.py")
    assert (workspace / "a.py").read_text(encoding="utf-8") == "hello\nworld\n"


@pytest.mark.asyncio
async def test_write_file_create_nested_dirs(workspace):
    r = read_json(await write_file("a/b/c/d.txt", "deep"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[CREATED]")
    assert (workspace / "a/b/c/d.txt").read_text(encoding="utf-8") == "deep"


@pytest.mark.asyncio
async def test_write_file_create_absolute_path(workspace):
    target = workspace / "sub" / "abs.py"
    r = read_json(await write_file(str(target), "abs"))
    assert r["status"] == "ok"
    assert r["path"] == str(target.resolve())
    assert target.read_text(encoding="utf-8") == "abs"


@pytest.mark.asyncio
async def test_write_file_create_umask_mode(workspace):
    old_umask = os.umask(0)
    os.umask(old_umask)
    r = read_json(await write_file("perm.py", "foo"))
    assert r["status"] == "ok"
    assert os.stat(workspace / "perm.py").st_mode & 0o777 == 0o666 & ~old_umask


@pytest.mark.asyncio
async def test_write_file_create_empty_file(workspace):
    r = read_json(await write_file("empty.txt", ""))
    assert r["status"] == "ok"
    assert r["message"].startswith("[CREATED]")
    assert "(0 lines)" in r["message"]
    assert os.path.exists(workspace / "empty.txt")
    assert os.path.getsize(workspace / "empty.txt") == 0


@pytest.mark.asyncio
async def test_write_file_create_whitespace_content(workspace):
    r = read_json(await write_file("ws.txt", "  "))
    assert r["status"] == "ok"
    assert os.path.getsize(workspace / "ws.txt") == 2


@pytest.mark.asyncio
async def test_write_file_overwrite_existing(workspace):
    make_text_file(workspace, "a.py", "old content\n")
    r = read_json(await write_file("a.py", "new content\n"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[OVERWRITTEN]")
    assert (workspace / "a.py").read_text(encoding="utf-8") == "new content\n"
    assert r["diff"]["old"] == "old content\n"
    assert r["diff"]["new"] == "new content\n"


@pytest.mark.asyncio
async def test_write_file_overwrite_keeps_mode(workspace):
    fp = make_text_file(workspace, "a.py", "old")
    os.chmod(fp, 0o640)
    r = read_json(await write_file("a.py", "new"))
    assert r["status"] == "ok"
    assert os.stat(fp).st_mode & 0o777 == 0o640


@pytest.mark.asyncio
async def test_write_file_overwrite_readonly_file(workspace):
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
    make_text_file(workspace, "a.py", "same\n")
    r = read_json(await write_file("a.py", "same\n"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[UNCHANGED]")
    assert r["path"] == str(workspace.resolve() / "a.py")
    assert r["diff"] == {"old": "same\n", "new": "same\n"}


@pytest.mark.asyncio
async def test_write_file_unchanged_mtime_inode(workspace):
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
    make_text_file(workspace, "a.py", "")
    r = read_json(await write_file("a.py", ""))
    assert r["status"] == "ok"
    assert r["message"].startswith("[UNCHANGED]")


@pytest.mark.asyncio
async def test_write_file_overwrite_large_old_file(workspace, monkeypatch):
    monkeypatch.setattr(_fs_mutate, "MAX_WRITE_SIZE", 10)
    make_text_file(workspace, "a.py", "x" * 20)
    r = read_json(await write_file("a.py", "small"))
    assert r["status"] == "ok"
    assert r["message"].startswith("[OVERWRITTEN]")
    assert (workspace / "a.py").read_text(encoding="utf-8") == "small"


@pytest.mark.asyncio
async def test_write_file_overwrite_undecodable_not_blocking(workspace):
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
    fp = workspace / "gbk.txt"
    fp.write_bytes("中文旧内容\n".encode("gbk"))
    r = read_json(await write_file("gbk.txt", ""))
    assert r["status"] == "ok"
    assert r["message"].startswith("[OVERWRITTEN]")
    assert os.path.getsize(fp) == 0


@pytest.mark.asyncio
async def test_write_file_target_is_directory(workspace):
    (workspace / "sub").mkdir()
    r = read_json(await write_file("sub", "foo"))
    assert r["status"] == "error"
    assert "is a directory" in r["message"]


@pytest.mark.asyncio
async def test_write_file_parent_path_is_file(workspace):
    (workspace / "block").write_text("x", encoding="utf-8")
    r = read_json(await write_file("block/x.txt", "y"))
    assert r["status"] == "error"
    assert "Cannot create directory" in r["message"]


@pytest.mark.asyncio
async def test_write_file_readonly_dir_graceful(workspace):
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
    r = read_json(await write_file("../escape/x.txt", "foo"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]
    assert not (workspace.parent / "escape").exists()


@pytest.mark.asyncio
async def test_write_file_failed_write_no_temp(workspace):
    (workspace / "block").write_text("x", encoding="utf-8")
    r = read_json(await write_file("block/x.txt", "y"))
    assert r["status"] == "error"
    assert sorted(p.name for p in workspace.iterdir()) == ["block"]


@pytest.mark.asyncio
async def test_write_file_gbk_write_read(workspace):
    r = read_json(await write_file("gbk.txt", "你好，世界", encoding="gbk"))
    assert r["status"] == "ok"
    assert (workspace / "gbk.txt").read_bytes() == "你好，世界".encode("gbk")


@pytest.mark.asyncio
async def test_write_file_latin1_write(workspace):
    r = read_json(await write_file("l1.txt", "café", encoding="latin-1"))
    assert r["status"] == "ok"
    assert (workspace / "l1.txt").read_bytes() == "café".encode("latin-1")


@pytest.mark.asyncio
async def test_write_file_ascii_unencodable_rejected(workspace):
    r = read_json(await write_file("a.py", "中文", encoding="ascii"))
    assert r["status"] == "error"
    assert "not encodable as ascii" in r["message"]
    assert not (workspace / "a.py").exists()


@pytest.mark.asyncio
async def test_write_file_diff_truncation(workspace):
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
    r = read_json(await write_file("lc.txt", content))
    assert r["status"] == "ok"
    assert r["message"] == f"[CREATED] {r['path']} ({expected_lines} lines)"


@pytest.mark.asyncio
async def test_write_file_success_contract(workspace):
    make_text_file(workspace, "a.py", "old\n")
    r = read_json(await write_file("a.py", "new\n"))
    assert set(r.keys()) == {"status", "message", "path", "diff"}
    assert r["status"] == "ok"
    assert set(r["diff"].keys()) == {"old", "new"}


@pytest.mark.parametrize("scenario", ["traversal", "directory", "oversize", "bad_content"])
@pytest.mark.asyncio
async def test_write_file_error_contract(workspace, scenario, monkeypatch):
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
    p1 = str(workspace.resolve() / "a.py")
    p2 = str(workspace.resolve() / "b.py")
    assert _fs_mutate._get_file_lock(p1) is _fs_mutate._get_file_lock(p1)
    assert _fs_mutate._get_file_lock(p1) is not _fs_mutate._get_file_lock(p2)


@pytest.mark.asyncio
async def test_write_file_inode_replaced(workspace):
    fp = make_text_file(workspace, "a.py", "old\n")
    ino_before = os.stat(fp).st_ino
    r = read_json(await write_file("a.py", "new\n"))
    assert r["status"] == "ok"
    assert os.stat(fp).st_ino != ino_before


@pytest.mark.asyncio
async def test_write_file_no_temp_left(workspace):
    r = read_json(await write_file("a.py", "foo"))
    assert r["status"] == "ok"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.py"]


@pytest.mark.asyncio
async def test_write_file_special_chars_fidelity(workspace):
    content = "  leading spaces\n\ttab\ttab\n\r\nmix\r\n😀 中文 混合\n\n\nend  \n"
    r = read_json(await write_file("special.txt", content))
    assert r["status"] == "ok"
    assert (workspace / "special.txt").read_bytes() == content.encode("utf-8")
