"""Tests for glob_tool matching semantics and boundary scenarios.

Test cases:
- test_glob_star_py_matches_root:             single-segment *.py only matches root files, not recursing into subdirectories
- test_glob_star_matches_all_root_entries:    * matches all root entries (files + directories + hidden files)
- test_glob_exact_path:                       multi-segment exact pattern a/b.py hits a single file
- test_glob_multi_segment:                    deep exact path sub/nested/deep.py
- test_glob_dir_pattern:                      wildcard-free patterns can match directories themselves
- test_question_mark_wildcard:                ? single-character wildcard matches x.py
- test_char_class_wildcard:                   [hm] character-class wildcard matches hello.py/main.py
- test_hidden_file_matched_by_star:           under fnmatch semantics * matches dot-leading hidden files
- test_double_star_all:                       bare ** matches all files and directories (including the root itself), exactly once per directory
- test_double_star_py:                        **/*.py matches all .py across any depth
- test_double_star_txt:                       **/*.txt matches across depths and returns results at all levels
- test_double_star_note:                      **/note.txt locates by filename across depths
- test_dir_double_star:                       a/** matches a itself and every entry inside
- test_double_star_zero_level:                ** zero-level semantics (**/hello.py matches root files)
- test_excluded_dirs_not_returned:            excluded directories are neither returned nor entered (.venv/logs)
- test_excluded_files_filtered:               excluded file .DS_Store is filtered even when matched
- test_dir_path_into_excluded_dir:            dir_path pointing inside an excluded directory searches normally
- test_dir_path_subdir:                       dir_path pointing at a subdirectory searches only that directory
- test_dir_path_absolute_inside:              absolute dir_path inside the workspace equals the relative path
- test_dir_path_outside_denied:               dir_path ../ escaping the workspace is blocked
- test_dir_path_absolute_outside_denied:      system absolute dir_path like /etc is blocked
- test_dir_path_not_directory:                dir_path pointing at a file is rejected
- test_dir_path_missing:                      nonexistent dir_path rejected
- test_allow_external_reads:                  allow_external_reads switch allows/blocks external directories
- test_symlink_dir_not_entered:               symlinked directories are not followed (escape prevention), but matchable as entries themselves
- test_result_cap_truncated:                  files truncated to GLOB_MAX_RESULTS with count keeping the total
- test_scan_cap_truncated:                    scanning stops when total reaches GLOB_MAX_SCAN (circuit breaker)
- test_files_sorted:                          files returned in ascending lexicographic order
- test_absolute_paths_returned:               returned paths are all absolute paths inside the workspace
- test_empty_result:                          no match gives count=0/empty files/truncated=False
- test_message_summary:                       message summarizes the match count
- test_invalid_patterns:                      parametrized: empty/blank/absolute/traversal patterns all rejected
- test_invalid_dir_path:                      parametrized: empty/blank dir_path rejected

Covered scenarios:
- Root matching:            *.py only matches root files, subdirectory files like a/b.py do not appear
- All-entry matching:       * matches root files + directories (including hidden files), exclusion rules still apply
- Exact paths:              multi-segment exact patterns hit a single file
- Directory matching:       wildcard-free patterns can match directories themselves
- ? wildcard:               single-character wildcard matches exactly one character
- Character-class wildcard: [seq] matches characters starting with a set member
- Hidden files:             under fnmatch semantics * matches dot-leading files (locked difference from standard glob not matching hidden)
- Bare **:                  matches all files and directories (including the root itself), exactly once per directory, no duplicates
- **/*.py:                  matches all .py files across any depth
- ** zero level:            in **/hello.py the ** can be treated as absent, matching root files directly
- Directory + **:           a/** matches a itself and every entry inside
- Excluded directories:     .venv/logs are neither returned nor entered (internal files invisible)
- Excluded files:           .DS_Store is filtered even when matched (.DS_* patterns return empty)
- Excluded dir direct hit:  dir_path pointing inside .venv searches normally (Notes semantics)
- dir_path subdirectory:    only the given subdirectory is searched
- dir_path absolute path:   absolute paths inside the workspace equal relative paths
- Out-of-bounds rejection:  ../ or /etc prefix checks intercept before directory existence checks
- Non-directory:            dir_path pointing at a file or a nonexistent path reports is not a directory
- External pass:            allow_external_reads=True can search directories outside the workspace
- Symlinks:                 directory symlinks are not followed (escape prevention), matchable as ordinary entries themselves
- Result cap:               files truncated to GLOB_MAX_RESULTS (200), count keeps the total match count
- Scan circuit breaker:     scanning stops when total reaches GLOB_MAX_SCAN (5000), truncated=True
- Sorting:                  files returned in ascending lexicographic order
- Absolute paths:           returned paths are all absolute paths inside the workspace (realpath normalized)
- Empty result:             count=0, files=[], truncated=False
- Parameter validation:     empty/blank/absolute/.. patterns and empty dir_path all rejected with reasons
"""

import os

import pytest

from core.tools._kernel import _fs_readonly
from core.tools._kernel._fs_readonly import glob_tool
from tests.helpers import read_json, rels


@pytest.mark.asyncio
async def test_glob_star_py_matches_root(tree):
    resp = read_json(await glob_tool("*.py"))
    assert resp["status"] == "ok"
    assert resp["count"] == 3
    got = {os.path.basename(f) for f in resp["files"]}
    assert got == {"hello.py", "main.py", "x.py"}


@pytest.mark.asyncio
async def test_glob_star_matches_all_root_entries(tree):
    resp = read_json(await glob_tool("*"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {
        "hello.py", "main.py", "x.py", "README.md", "data.txt",
        ".hidden.txt", "a", "b", "sub",
    }
    assert resp["count"] == 9


@pytest.mark.asyncio
async def test_glob_exact_path(tree):
    resp = read_json(await glob_tool("a/b.py"))
    assert resp["status"] == "ok"
    assert resp["count"] == 1
    assert os.path.basename(resp["files"][0]) == "b.py"


@pytest.mark.asyncio
async def test_glob_multi_segment(tree):
    resp = read_json(await glob_tool("sub/nested/deep.py"))
    assert resp["status"] == "ok"
    assert resp["count"] == 1
    assert os.path.basename(resp["files"][0]) == "deep.py"


@pytest.mark.asyncio
async def test_glob_dir_pattern(tree):
    resp = read_json(await glob_tool("a"))
    assert resp["status"] == "ok"
    assert resp["count"] == 1
    assert os.path.basename(resp["files"][0]) == "a"


@pytest.mark.asyncio
async def test_question_mark_wildcard(tree):
    resp = read_json(await glob_tool("?.py"))
    assert resp["status"] == "ok"
    assert [os.path.basename(f) for f in resp["files"]] == ["x.py"]


@pytest.mark.asyncio
async def test_char_class_wildcard(tree):
    resp = read_json(await glob_tool("[hm]*.py"))
    assert resp["status"] == "ok"
    assert [os.path.basename(f) for f in resp["files"]] == ["hello.py", "main.py"]


@pytest.mark.asyncio
async def test_hidden_file_matched_by_star(tree):
    resp = read_json(await glob_tool("*"))
    got = {os.path.basename(f) for f in resp["files"]}
    assert ".hidden.txt" in got

    resp = read_json(await glob_tool(".*"))
    assert [os.path.basename(f) for f in resp["files"]] == [".hidden.txt"]


@pytest.mark.asyncio
async def test_double_star_all(tree):
    resp = read_json(await glob_tool("**"))
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


@pytest.mark.asyncio
async def test_double_star_py(tree):
    resp = read_json(await glob_tool("**/*.py"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"hello.py", "main.py", "x.py", "a/b.py", "sub/nested/deep.py"}
    assert resp["count"] == 5


@pytest.mark.asyncio
async def test_double_star_txt(tree):
    resp = read_json(await glob_tool("**/*.txt"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"data.txt", ".hidden.txt", "a/c/note.txt", "b/note.txt", "sub/data.txt"}
    assert resp["count"] == 5


@pytest.mark.asyncio
async def test_double_star_note(tree):
    resp = read_json(await glob_tool("**/note.txt"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"a/c/note.txt", "b/note.txt"}
    assert resp["count"] == 2


@pytest.mark.asyncio
async def test_dir_double_star(tree):
    resp = read_json(await glob_tool("a/**"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"a", "a/b.py", "a/c", "a/c/note.txt"}
    assert resp["count"] == 4


@pytest.mark.asyncio
async def test_double_star_zero_level(tree):
    resp = read_json(await glob_tool("**/hello.py"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"hello.py"}
    assert resp["count"] == 1


@pytest.mark.asyncio
async def test_excluded_dirs_not_returned(tree):
    resp = read_json(await glob_tool("**"))
    got = rels(tree, resp["files"])
    assert ".venv" not in got
    assert "logs" not in got
    assert ".venv/venv.py" not in got
    assert "logs/app.log" not in got


@pytest.mark.asyncio
async def test_excluded_files_filtered(tree):
    for pattern in ("*", "**", "**/*"):
        resp = read_json(await glob_tool(pattern))
        assert all(".DS_Store" not in os.path.basename(f) for f in resp["files"])

    resp = read_json(await glob_tool(".DS_*"))
    assert resp["status"] == "ok"
    assert resp["files"] == []


@pytest.mark.asyncio
async def test_dir_path_into_excluded_dir(tree):
    resp = read_json(await glob_tool("*.py", dir_path=".venv"))
    assert resp["status"] == "ok"
    assert [os.path.basename(f) for f in resp["files"]] == ["venv.py"]


@pytest.mark.asyncio
async def test_dir_path_subdir(tree):
    resp = read_json(await glob_tool("*.py", dir_path="a"))
    assert resp["status"] == "ok"
    got = rels(tree, resp["files"])
    assert got == {"a/b.py"}
    assert resp["count"] == 1


@pytest.mark.asyncio
async def test_dir_path_absolute_inside(tree):
    abs_ws = os.path.realpath(str(tree))
    resp = read_json(await glob_tool("*.py", dir_path=abs_ws))
    assert resp["status"] == "ok"
    assert resp["count"] == 3


@pytest.mark.asyncio
async def test_dir_path_outside_denied(tree):
    resp = read_json(await glob_tool("*.py", dir_path="../outside"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


@pytest.mark.asyncio
async def test_dir_path_absolute_outside_denied(tree):
    resp = read_json(await glob_tool("*.py", dir_path="/etc"))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]


@pytest.mark.asyncio
async def test_dir_path_not_directory(tree):
    resp = read_json(await glob_tool("*", dir_path="hello.py"))
    assert resp["status"] == "error"
    assert "is not a directory" in resp["message"]


@pytest.mark.asyncio
async def test_dir_path_missing(tree):
    resp = read_json(await glob_tool("*", dir_path="nope"))
    assert resp["status"] == "error"
    assert "is not a directory" in resp["message"]


@pytest.mark.asyncio
async def test_allow_external_reads(workspace):
    outside = workspace.parent / "ext"
    outside.mkdir()
    (outside / "out.py").write_text("print('out')\n", encoding="utf-8")

    resp = read_json(await glob_tool("*.py", dir_path=str(outside)))
    assert resp["status"] == "error"
    assert "denied" in resp["message"]

    resp = read_json(await glob_tool("*.py", dir_path=str(outside), allow_external_reads=True))
    assert resp["status"] == "ok"
    assert [os.path.basename(f) for f in resp["files"]] == ["out.py"]


@pytest.mark.asyncio
async def test_symlink_dir_not_entered(tree):
    outside = tree.parent / "secret_dir"
    outside.mkdir()
    (outside / "secret.py").write_text("print('secret')\n", encoding="utf-8")
    os.symlink(str(outside), str(tree / "link"), target_is_directory=True)

    resp = read_json(await glob_tool("**/*.py"))
    assert all("secret" not in f for f in resp["files"])
    assert all("link/" not in f for f in resp["files"])

    resp = read_json(await glob_tool("**"))
    got = {os.path.basename(f) for f in resp["files"]}
    assert "link" in got


@pytest.mark.asyncio
async def test_result_cap_truncated(tree, monkeypatch):
    monkeypatch.setattr(_fs_readonly, "GLOB_MAX_RESULTS", 20)
    for i in range(30):
        (tree / f"f{i:02d}.txt").write_text("x\n", encoding="utf-8")

    resp = read_json(await glob_tool("f*.txt"))
    assert resp["status"] == "ok"
    assert len(resp["files"]) == 20
    assert resp["count"] == 30
    assert resp["truncated"] is True
    assert "(truncated)" in resp["message"]


@pytest.mark.asyncio
async def test_scan_cap_truncated(tree, monkeypatch):
    monkeypatch.setattr(_fs_readonly, "GLOB_MAX_SCAN", 20)
    for i in range(30):
        (tree / f"g{i:02d}.txt").write_text("x\n", encoding="utf-8")

    resp = read_json(await glob_tool("g*.txt"))
    assert resp["status"] == "ok"
    assert resp["count"] == 20
    assert len(resp["files"]) == 20
    assert resp["truncated"] is True


@pytest.mark.asyncio
async def test_files_sorted(tree):
    for name in ("zeta.py", "alpha.py", "mid.py"):
        (tree / name).write_text("print(1)\n", encoding="utf-8")

    resp = read_json(await glob_tool("*.py"))
    assert resp["status"] == "ok"
    assert [os.path.basename(f) for f in resp["files"]] == [
        "alpha.py", "hello.py", "main.py", "mid.py", "x.py", "zeta.py",
    ]


@pytest.mark.asyncio
async def test_absolute_paths_returned(tree):
    resp = read_json(await glob_tool("*.py"))
    assert resp["status"] == "ok"
    abs_ws = os.path.realpath(str(tree))
    assert all(f.startswith(abs_ws) for f in resp["files"])


@pytest.mark.asyncio
async def test_empty_result(tree):
    resp = read_json(await glob_tool("*.xyz"))
    assert resp["status"] == "ok"
    assert resp["count"] == 0
    assert resp["files"] == []
    assert resp["truncated"] is False


@pytest.mark.asyncio
async def test_message_summary(tree):
    resp = read_json(await glob_tool("*.py"))
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
@pytest.mark.asyncio
async def test_invalid_patterns(tree, pattern, expect):
    resp = read_json(await glob_tool(pattern))
    assert resp["status"] == "error"
    assert expect in resp["message"]


@pytest.mark.parametrize("dir_path", ["", "   "])
@pytest.mark.asyncio
async def test_invalid_dir_path(tree, dir_path):
    resp = read_json(await glob_tool("*.py", dir_path=dir_path))
    assert resp["status"] == "error"
    assert "dir_path must not be empty" in resp["message"]
