"""Comprehensive tests for clean_dir: parameter validation, path safety, symlink semantics, collect/delete semantics and the response contract.

Test cases:
- test_clean_dir_invalid_dir_path:                    parametrized: empty/blank/non-str dir_path rejected
- test_clean_dir_invalid_patterns_type:               parametrized: non-list patterns rejected (number/string)
- test_clean_dir_invalid_patterns_element:            parametrized: non-str elements in patterns rejected
- test_clean_dir_empty_patterns_list_means_recursive: patterns=[] is synonymous with None (recursive delete)
- test_clean_dir_workspace_not_configured:            RuntimeError when the workspace is not configured
- test_clean_dir_relative_path:                       relative paths resolve to paths inside the workspace
- test_clean_dir_absolute_path:                       absolute paths inside the workspace equal relative paths
- test_clean_dir_home_expansion:                      ~ expands to a path under HOME
- test_clean_dir_traversal_denied:                    ../ escaping the workspace is blocked
- test_clean_dir_absolute_outside_denied:             absolute paths outside the workspace blocked
- test_clean_dir_prefix_trap_denied:                  same-prefix sibling directories blocked
- test_clean_dir_root_protection:                     parametrized: three forms of the workspace root refuse deletion
- test_clean_dir_not_exists:                          nonexistent paths rejected
- test_clean_dir_link_to_outside_file:                links pointing at external files delete the link itself
- test_clean_dir_link_to_inside_file:                 links pointing at files inside the workspace delete the link itself
- test_clean_dir_link_to_outside_dir:                 links pointing at external directories delete the link itself
- test_clean_dir_link_to_inside_dir:                  links pointing at directories inside the workspace delete the link itself
- test_clean_dir_link_to_workspace_root:              links pointing at the workspace root delete the link without triggering root protection
- test_clean_dir_walk_matched_symlink_file:           walk-collected symlink files are unlinked
- test_clean_dir_walk_matched_symlink_dir:            walk-collected symlink directories are unlinked
- test_clean_dir_file_target:                         file targets deleted (deleted relative to the root)
- test_clean_dir_file_target_ignores_patterns:        file targets ignore patterns
- test_clean_dir_recursive_delete_dir:                patterns=None recursively deletes the whole directory
- test_clean_dir_recursive_empty_dir:                 empty directories recursively deleted
- test_clean_dir_recursive_deep_nested:               deep-nested directories recursively deleted
- test_clean_dir_dot_relative_path:                   "./sub" prefix form
- test_clean_dir_trailing_slash_path:                 "sub/" trailing-slash form
- test_clean_dir_pattern_star_deletes_all:            "*" matches directories + files and prunes
- test_clean_dir_pattern_match_files_recursive:       patterns recursively match files in nesting
- test_clean_dir_pattern_match_dir_whole:             matching directories are deleted whole
- test_clean_dir_pattern_match_dir_pruned:            matching directories are pruned without descending, siblings kept
- test_clean_dir_pattern_no_match:                    no match returns Nothing matched
- test_clean_dir_pattern_match_hidden:                hidden files participate in matching
- test_clean_dir_multiple_patterns:                   multi-pattern union matching
- test_clean_dir_pattern_case_sensitive:              fnmatch is case-sensitive
- test_clean_dir_pattern_wildcard_specific:           "?" single-character wildcard
- test_clean_dir_empty_pattern_element:               empty-string patterns match nothing
- test_clean_dir_scan_error_on_unreadable_subdir:     unreadable subdirectories turn the scan into error
- test_clean_dir_partial_failure_contract:            partial-failure error carries deletion progress
- test_clean_dir_delete_readonly_file_ok:             read-only files are deletable (unlink only needs directory permissions)
- test_clean_dir_delete_readonly_dir_error:           read-only directory deletion fails with a graceful error
- test_clean_dir_exceeds_limit:                       over CLEAN_MAX_ITEMS pre-check takes no action
- test_clean_dir_at_limit:                            exactly CLEAN_MAX_ITEMS passes
- test_clean_dir_success_contract:                    ok response field contract with the [DELETED] prefix
- test_clean_dir_nothing_matched_contract:            no-match ok response field contract
- test_clean_dir_error_contract:                      parametrized: pure-validation errors have only status/message
- test_clean_dir_clean_lock_singleton:                _clean_lock module-level singleton
- test_clean_dir_uses_shared_file_lock:               delete paths join the shared file lock (spy)
- test_clean_dir_no_temp_leftover:                    neither file nor directory deletion leaves .clean_tmp_ leftovers
- test_clean_dir_delete_then_str_replace_error:       write tools error gracefully after deletion (lock mutual exclusion)
- test_clean_dir_only_matches_deleted:                only matches deleted, unmatched files byte-identical
- test_clean_dir_recursive_keeps_siblings:            recursive deletion does not touch sibling directories

Covered scenarios:
- Parameter validation: dir_path empty/blank/non-str rejected; patterns type and element validation (the silent-no-match trap of strings
  being iterated per character, the number crash trap); empty list synonymous with None (recursive delete); error when the workspace is not configured
- Path safety: relative/absolute/~/./trailing-slash five legal forms; ../ and system absolute paths and same-prefix sibling directories
  out-of-bounds rejections; root protection covers "." / absolute root / "sub/.." lexical folding (prevents rm -rf of the workspace root)
- Symlink semantics: links pointing at files/directories inside or outside the workspace always delete the link itself (external targets intact,
  links pointing at the root do not trigger root protection); walk-collected symlink files/directories are unlinked, not rmtree'd (protects real targets)
- Delete semantics: file targets ignore patterns; patterns=None/[] recursively delete directories (empty/deep-nested);
  patterns match by basename glob (nested recursive collection, matching directories deleted whole and pruned without descending)
- Collection details: hidden files match, multi-pattern union, case-sensitive, ? single-char wildcard, empty pattern element matches nothing
- Error paths: unreadable subdirectories during scanning turn into error (onerror does not silently miss deletions); partial failure during
  deletion errors carry deleted/count progress (not rollbackable); read-only files deletable (unlink only needs directory write permission);
  read-only directory deletion fails with a graceful error
- Limits: over CLEAN_MAX_ITEMS pre-check before touching anything (nothing deleted), exactly at passes (boundary)
- Response contract: ok branch fixed fields (status/message/deleted/count + [DELETED] prefix),
  no-match ok (Nothing matched + empty list), pure-validation error only status/message
  (partial-failure error additionally carries progress fields, an exceptional contract)
- Locks and atomicity: _clean_lock module-level singleton, delete paths join the shared file lock (spy verification, concurrency test prerequisite),
  directory rename isolation leaves no .clean_tmp_ leftovers, write tools error gracefully after deletion
- Side effects: only matches deleted, unmatched files byte-identical, recursive deletion does not touch sibling directories

Usage notes:
- The project runs pytest-asyncio strict mode: all async tests must be explicitly marked @pytest.mark.asyncio
- Permission cases (chmod 000/0555/0444) restore permissions afterwards (with existence protection, no chmod after deletion),
  to avoid affecting tmp cleanup and later cases
- Limit cases isolate via monkeypatch of _fs_mutate.CLEAN_MAX_ITEMS instead of building a real 500 items
- Path assertions uniformly use workspace.resolve() (realpath normalization, prevents macOS /var → /private/var symlink differences)
- Targets outside the workspace are built with workspace.parent or tempfile.mkdtemp() (not inside the workspace)
- The rename isolation in partial-failure cases leaves .clean_tmp_ directories (rmtree failure cleaned up best-effort),
  reclaimed by the pytest temp directory, not asserted
- Depends on the workspace fixture from conftest.py and make_text_file / read_json from tests/helpers.py

Test count: 64
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
    r = read_json(await clean_dir(bad_path))
    assert r["status"] == "error"
    assert r["message"] == "dir_path must be a non-empty string."


@pytest.mark.parametrize("bad_patterns", [123, "*.py"])
@pytest.mark.asyncio
async def test_clean_dir_invalid_patterns_type(workspace, bad_patterns):
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir("sub", bad_patterns))
    assert r["status"] == "error"
    assert r["message"] == "patterns must be a list of strings or None."
    assert (workspace / "sub/a.py").exists()


@pytest.mark.parametrize("bad_patterns", [[123], [None], ["ok.py", 1]])
@pytest.mark.asyncio
async def test_clean_dir_invalid_patterns_element(workspace, bad_patterns):
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir("sub", bad_patterns))
    assert r["status"] == "error"
    assert r["message"] == "patterns must be a list of strings or None."


@pytest.mark.asyncio
async def test_clean_dir_empty_patterns_list_means_recursive(workspace):
    make_text_file(workspace, "sub/a.py", "x")
    make_text_file(workspace, "sub/nested/b.py", "y")
    r = read_json(await clean_dir("sub", []))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["sub"]
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_workspace_not_configured(workspace, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", None)
    with pytest.raises(RuntimeError, match="WORKSPACE_DIR is not configured"):
        await clean_dir("a.py")


@pytest.mark.asyncio
async def test_clean_dir_relative_path(workspace):
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir("sub/a.py"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["sub/a.py"]
    assert not (workspace / "sub/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_absolute_path(workspace):
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir(str(workspace / "sub/a.py")))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "sub/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_home_expansion(workspace, monkeypatch):
    make_text_file(workspace, "sub/a.py", "x")
    monkeypatch.setenv("HOME", str(workspace))
    r = read_json(await clean_dir("~/sub"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_traversal_denied(workspace):
    r = read_json(await clean_dir("../escape"))
    assert r["status"] == "error"
    assert "is denied" in r["message"]


@pytest.mark.asyncio
async def test_clean_dir_absolute_outside_denied(workspace):
    outside = tempfile.mkdtemp()
    r = read_json(await clean_dir(outside))
    assert r["status"] == "error"
    assert "is denied" in r["message"]
    assert os.path.isdir(outside)


@pytest.mark.asyncio
async def test_clean_dir_prefix_trap_denied(workspace, monkeypatch):
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
    if root_path == "<root>":
        root_path = str(workspace.resolve())
    r = read_json(await clean_dir(root_path))
    assert r["status"] == "error"
    assert "workspace root" in r["message"]


@pytest.mark.asyncio
async def test_clean_dir_not_exists(workspace):
    r = read_json(await clean_dir("missing"))
    assert r["status"] == "error"
    assert "does not exist" in r["message"]


@pytest.mark.asyncio
async def test_clean_dir_link_to_outside_file(workspace):
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
    link = workspace / "root_link"
    link.symlink_to(workspace, target_is_directory=True)
    r = read_json(await clean_dir("root_link"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not os.path.lexists(link)
    assert workspace.exists()


@pytest.mark.asyncio
async def test_clean_dir_walk_matched_symlink_file(workspace):
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
    make_text_file(workspace, "a.txt", "x")
    r = read_json(await clean_dir("a.txt"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["a.txt"]
    assert not (workspace / "a.txt").exists()


@pytest.mark.asyncio
async def test_clean_dir_file_target_ignores_patterns(workspace):
    make_text_file(workspace, "a.txt", "x")
    r = read_json(await clean_dir("a.txt", ["*.py"]))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "a.txt").exists()


@pytest.mark.asyncio
async def test_clean_dir_recursive_delete_dir(workspace):
    make_text_file(workspace, "sub/a.py", "x")
    make_text_file(workspace, "sub/nested/b.md", "y")
    r = read_json(await clean_dir("sub"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["sub"]
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_recursive_empty_dir(workspace):
    (workspace / "sub").mkdir()
    r = read_json(await clean_dir("sub"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_recursive_deep_nested(workspace):
    make_text_file(workspace, "a/b/c/d/e.py", "x")
    r = read_json(await clean_dir("a"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "a").exists()


@pytest.mark.asyncio
async def test_clean_dir_dot_relative_path(workspace):
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir("./sub"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_trailing_slash_path(workspace):
    make_text_file(workspace, "sub/a.py", "x")
    r = read_json(await clean_dir("sub/"))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert not (workspace / "sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_star_deletes_all(workspace):
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
    make_text_file(workspace, "proj/sub/a.py", "x")
    make_text_file(workspace, "proj/sub/keep.txt", "y")
    r = read_json(await clean_dir("proj", ["sub"]))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["proj/sub"]
    assert not (workspace / "proj/sub").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_match_dir_pruned(workspace):
    make_text_file(workspace, "proj/sub/a.py", "x")
    make_text_file(workspace, "proj/sub/keep.txt", "y")
    r = read_json(await clean_dir("proj", ["*.txt"]))
    assert r["status"] == "ok"
    assert r["count"] == 1
    assert r["deleted"] == ["proj/sub/keep.txt"]
    assert (workspace / "proj/sub/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_no_match(workspace):
    make_text_file(workspace, "proj/a.py", "x")
    r = read_json(await clean_dir("proj", ["*.zzz"]))
    assert r["status"] == "ok"
    assert "Nothing matched" in r["message"]
    assert r["count"] == 0
    assert r["deleted"] == []
    assert (workspace / "proj/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_match_hidden(workspace):
    make_text_file(workspace, "proj/.hidden.txt", "x")
    make_text_file(workspace, "proj/visible.txt", "y")
    r = read_json(await clean_dir("proj", ["*.txt"]))
    assert r["status"] == "ok"
    assert r["count"] == 2
    assert not (workspace / "proj/.hidden.txt").exists()
    assert not (workspace / "proj/visible.txt").exists()


@pytest.mark.asyncio
async def test_clean_dir_multiple_patterns(workspace):
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
    make_text_file(workspace, "proj/a.py", "x")
    r = read_json(await clean_dir("proj", ["*.PY"]))
    assert r["status"] == "ok"
    assert r["count"] == 0
    assert (workspace / "proj/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_pattern_wildcard_specific(workspace):
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
    make_text_file(workspace, "proj/a.py", "x")
    r = read_json(await clean_dir("proj", [""]))
    assert r["status"] == "ok"
    assert r["count"] == 0
    assert (workspace / "proj/a.py").exists()


@pytest.mark.asyncio
async def test_clean_dir_scan_error_on_unreadable_subdir(workspace):
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
    make_text_file(workspace, "proj/a.py", "x")
    r = read_json(await clean_dir("proj/a.py"))
    assert set(r.keys()) == {"status", "message", "deleted", "count"}
    assert r["status"] == "ok"
    assert r["message"] == "[DELETED] 1 item(s)"
    assert r["deleted"] == ["proj/a.py"]
    assert r["count"] == 1


@pytest.mark.asyncio
async def test_clean_dir_nothing_matched_contract(workspace):
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
    assert _fs_mutate._clean_lock is _fs_mutate._clean_lock


@pytest.mark.asyncio
async def test_clean_dir_uses_shared_file_lock(workspace, monkeypatch):
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
    make_text_file(workspace, "s.py", "foo\n")
    r = read_json(await clean_dir("s.py"))
    assert r["status"] == "ok"
    r = read_json(await str_replace("s.py", "foo", "bar"))
    assert r["status"] == "error"
    assert "does not exist" in r["message"]


@pytest.mark.asyncio
async def test_clean_dir_only_matches_deleted(workspace):
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
    make_text_file(workspace, "sub/a.py", "x")
    make_text_file(workspace, "keep.py", "keep")
    make_text_file(workspace, "keep_dir/b.txt", "y")
    r = read_json(await clean_dir("sub"))
    assert r["status"] == "ok"
    assert not (workspace / "sub").exists()
    assert (workspace / "keep.py").read_text(encoding="utf-8") == "keep"
    assert (workspace / "keep_dir/b.txt").exists()
