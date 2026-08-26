"""Workspace read-only filesystem tools implementation.

Provides:
- view_file:  read file content by line numbers, chunked continuation, max 1MB per call
- glob_tool:  find files by glob pattern matching, recursive ** and fnmatch wildcards
- grep_tool:  regex search over file content, three output modes with paging

Key constraints:
- all tools return JSON strings with status ok or error and never raise,
  except one case: a missing workspace raises RuntimeError, a config
  error rather than a business error
- paths are confined to the workspace by default: realpath normalization
  plus a boundary prefix check, allow_external_reads=True lifts the
  limit; directory symlinks are not followed, preventing escapes
- returned paths are absolute paths inside the workspace after realpath
  normalization, consistent across all three tools
- EXCLUDE_DIRS and EXCLUDE_FILES are shared by glob and grep pruning,
  excluded entries are neither returned nor entered
- hard resource limits: MAX_READ_SIZE (1MB per read), GLOB_MAX_RESULTS
  (200 results), GLOB_MAX_SCAN / GREP_MAX_FILES (5000 scan cap),
  GREP_MAX_FILE_SIZE (10MB per file)
- binary guard: NUL byte sniffing before reads (BINARY_SNIFF_BYTES),
  UTF-16/32 whitelisted; on a hit view_file returns an error, grep
  skips silently (batch scan semantics)
- timeout fuses: REGEX_MATCH_TIMEOUT_SECONDS per regex match (guards
  against catastrophic backtracking), plus GREP_TOTAL_TIMEOUT_SECONDS
  as an overall wall-clock budget for the whole grep call

Usage notes:
- view_file reads large files in chunks: continue with offset=end_line+1
  until has_more=False
- glob_tool can search inside excluded directories by pointing dir_path
  directly at that directory
- grep_tool glob_pattern matches file names (basename) only, no ** and
  no path separators; scope a subdirectory with the path parameter
- grep_tool timeouts return the partial results already collected:
  timed_out_files counts per-line fuses, search_timed_out=True means
  the results are incomplete, not an error
- this module is read-only; use _fs_mutate for write operations
"""

import os
import regex as re
import json
import fnmatch
import time
import asyncio

from core.tools._kernel.constants import (
    MAX_READ_SIZE,
    VIEW_FILE_MAX_SKIP_BYTES,
    BINARY_SNIFF_BYTES,
    EXCLUDE_DIRS,
    EXCLUDE_FILES,
    GLOB_MAX_RESULTS,
    GLOB_MAX_SCAN,
    GREP_MAX_FILES,
    GREP_MAX_FILE_SIZE,
    GREP_TOTAL_TIMEOUT_SECONDS,
    REGEX_MATCH_TIMEOUT_SECONDS,
)
from utils.settings import settings


def _view_file_io(
    file_path: str,
    offset: int,
    limit: int,
    encoding: str,
) -> str:
    """Core read sync segment: binary sniff, skip offset-1 lines, then read
    truncated by limit and the 1MB cap, return JSON.

    Called by view_file via asyncio.to_thread, so disk IO and line
    processing run in a thread pool and never block the event loop;
    binary sniff hits, EOF and truncation semantics match the main
    function exactly.

    Args:
        file_path: absolute file path, already validated by the safety chain.
        offset:    first line to display, starting from 1.
        limit:     maximum lines to return (1-1000).
        encoding:  file encoding.

    Returns:
        JSON string with the same contract as view_file: on ok it carries
        path/read_lines/start_line/end_line/has_more/truncated/lines;
        on error only message.
    """
    try:
        # binary sniff: read the file head in binary mode and look for NUL bytes;
        # UTF-16/UTF-32 encodings naturally contain NUL, so they are whitelisted
        with open(file_path, "rb") as f:
            head = f.read(BINARY_SNIFF_BYTES)
        if b"\x00" in head and not encoding.lower().startswith(("utf-16", "utf-32")):
            return json.dumps({
                "status": "error",
                "message": (
                    f"'{file_path}' appears to be a binary file. "
                    "If it is a text file, it may use an encoding "
                    "that contains NUL bytes (e.g. UTF-16)."
                )
            }, ensure_ascii=False)

        with open(file_path, "r", encoding=encoding) as f:
            messages: list[str] = []            # holds advisory messages, non-fatal issues append here
            skipped_lines = 0                   # lines skipped so far
            skipped_bytes = 0                   # total bytes skipped so far
            skip_warned = False                 # whether the expensive-skip warning was already emitted

            # skip offset-1 lines first, so reading starts at line offset
            while skipped_lines < offset - 1:
                # read one line
                line = f.readline()

                # EOF: an empty read means the file ended early
                if not line:
                    return json.dumps({
                        "status": "error",
                        "message": (
                            f"Start line {offset} exceeds total lines "
                            f"(file has only {skipped_lines} lines)."
                        )
                    }, ensure_ascii=False)

                # skip the current line, bump the skipped line and byte counts
                skipped_lines += 1
                skipped_bytes += len(line.encode(encoding))

                # warn once when skipped bytes pass the threshold, the skip is expensive
                if not skip_warned and skipped_bytes > VIEW_FILE_MAX_SKIP_BYTES:
                    skip_warned = True
                    messages.append(
                        f"Skipped > {VIEW_FILE_MAX_SKIP_BYTES // 1024 // 1024} MB to reach "
                        f"offset {offset}; reading remains available but expensive."
                    )

            # read from line offset until limit lines, EOF, or MAX_READ_SIZE is exceeded
            lines: list[str] = []                # holds the read lines
            bytes_read = 0                       # bytes read so far
            truncated = False                    # whether the read was truncated

            # keep reading until the limit line count or EOF
            while len(lines) < limit:
                # read one line; an empty read means EOF, so stop
                line = f.readline()
                if not line:
                    break

                # line bytes; truncate and stop when the running total would pass MAX_READ_SIZE
                line_bytes = len(line.encode(encoding))
                if bytes_read + line_bytes > MAX_READ_SIZE:
                    truncated = True
                    break

                # append the line and bump the bytes read
                lines.append(line)
                bytes_read += line_bytes

            # has_more: always True when truncated; otherwise probe EOF when the full limit was read
            has_more = truncated
            if not truncated and len(lines) == limit:
                pos = f.tell()
                if f.read(1):
                    has_more = True
                f.seek(pos)

            # no lines were read at all:
            if not lines:
                if truncated:
                    messages.append(
                        f"Line at offset {offset} exceeds {MAX_READ_SIZE // 1024 // 1024} MB "
                        f"limit, cannot return any line. Use offset={offset + 1} to skip it."
                    )
                result = {
                    "status": "ok",
                    "path": file_path,
                    "read_lines": 0,
                    "start_line": offset,
                    "end_line": offset - 1,
                    "has_more": has_more,
                    "truncated": truncated,
                    "lines": [],
                }
                if messages:
                    result["message"] = " ".join(messages)
                return json.dumps(result, ensure_ascii=False)

            # assemble the response with path, line counts, range, truncation flag and line contents
            start_line = offset
            end_line = offset + len(lines) - 1
            numbered_lines = [
                {"line_no": i, "content": line.rstrip("\n")}
                for i, line in enumerate(lines, start=start_line)
            ]
            result = {
                "status": "ok",
                "path": file_path,
                "read_lines": len(lines),
                "start_line": start_line,
                "end_line": end_line,
                "has_more": has_more,
                "truncated": truncated,
                "lines": numbered_lines,
            }
            if truncated:
                messages.append(
                    f"Read limited to {MAX_READ_SIZE // 1024 // 1024} MB "
                    f"(showing {len(lines)} lines). Use offset={end_line + 1} to continue."
                )
            if messages:
                result["message"] = " ".join(messages)
            return json.dumps(result, ensure_ascii=False)

    # second defense: catch races that slipped past the earlier checks
    except FileNotFoundError:
        return json.dumps({
            "status": "error",
            "message": f"File '{file_path}' does not exist."
        }, ensure_ascii=False)
    except IsADirectoryError:
        return json.dumps({
            "status": "error",
            "message": f"'{file_path}' is a directory."
        }, ensure_ascii=False)
    except PermissionError:
        return json.dumps({
            "status": "error",
            "message": f"Permission denied: '{file_path}'."
        }, ensure_ascii=False)
    except UnicodeDecodeError:
        return json.dumps({
            "status": "error",
            "message": (
                f"{file_path} cannot be decoded as {encoding}. "
                f"Retry with encoding='gbk' or 'latin-1' if needed."
            )
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot read {file_path}: {exc}"
        }, ensure_ascii=False)


async def view_file(
    file_path: str,
    offset: int = 1,
    limit: int = 100,
    encoding: str = "utf-8",
    allow_external_reads: bool = False,
) -> str:
    """Read file content by line numbers, from a start line for a given count.

    Supports large files: each call reads at most 1MB of data, truncated
    at line boundaries; offset may point at any line and preceding lines
    are skipped (a skip beyond VIEW_FILE_MAX_SKIP_BYTES only warns and
    never aborts); callers continue with offset=end_line+1 until
    has_more=False.

    Execution model: argument validation and path safety checks run on
    the event loop (pure CPU); the core reading logic (binary sniff,
    line skipping, truncation) runs in a thread pool via
    asyncio.to_thread, keeping disk IO off the event loop.

    Args:
        file_path:             file path, workspace-relative or absolute.
        offset:                first line to display, starting from 1 (default 1).
        limit:                 maximum lines to return, 1-1000 (default 100).
        encoding:              file encoding (default utf-8).
        allow_external_reads:  whether to allow reading files outside the workspace.

    Returns:
        JSON string. On ok: path, read_lines, start_line, end_line,
        has_more, truncated, lines (a list of {line_no, content}); a
        message is added on truncation or an expensive skip. On error:
        only message.

    Notes:
        - has_more True means unreturned lines remain, always True when truncated
        - chunked continuation: the next call uses offset=end_line+1
        - offset beyond the total line count returns an error; pointing
          exactly at the line after the last one returns an empty result
    """
    # validate file_path: must not be empty
    if not file_path or not file_path.strip():
        return json.dumps({
            "status": "error",
            "message": "file_path must not be empty."
        }, ensure_ascii=False)

    # validate limit: integer in 1-1000 (bool is an int subclass, must be excluded)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 1000:
        return json.dumps({
            "status": "error",
            "message": "limit must be an integer between 1 and 1000."
        }, ensure_ascii=False)

    # validate offset: positive integer
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 1:
        return json.dumps({
            "status": "error",
            "message": "offset must be a positive integer."
        }, ensure_ascii=False)

    # get the workspace directory; this is a hard requirement, fail fast when missing
    workspace = settings.workspace_dir
    if not workspace:
        raise RuntimeError("WORKSPACE_DIR is not configured, please set it up.")
    workspace = os.path.abspath(workspace)

    # resolve all symlinks on top of abspath, returning the real path on disk
    try:
        safe_root = os.path.realpath(workspace)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot resolve workspace: {exc}"
        }, ensure_ascii=False)

    # expand the home directory, e.g. ~/Desktop/foo.py becomes /home/user/Desktop/foo.py
    file_path = os.path.expanduser(file_path)

    # resolve the passed path to an absolute real path
    try:
        if not os.path.isabs(file_path):
            file_path = os.path.realpath(os.path.join(safe_root, file_path))
        else:
            file_path = os.path.realpath(file_path)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Invalid path: {exc}"
        }, ensure_ascii=False)

    # normalize the boundary: the workspace root must end with exactly one
    # separator to prevent prefix-match traps; strip all trailing separators
    # (/Users/foo/// becomes /Users/foo), then add exactly one
    safe_root = safe_root.rstrip(os.sep) + os.sep

    # boundary check: file_path must stay inside the workspace
    if not allow_external_reads and not file_path.startswith(safe_root):
        return json.dumps({
            "status": "error",
            "message": f"Access to '{file_path}' is denied."
        }, ensure_ascii=False)

    # existence check: file_path must exist
    if not os.path.exists(file_path):
        return json.dumps({
            "status": "error",
            "message": f"File '{file_path}' does not exist."
        }, ensure_ascii=False)

    # type check: file_path must not be a directory
    if os.path.isdir(file_path):
        return json.dumps({
            "status": "error",
            "message": f"'{file_path}' is a directory."
        }, ensure_ascii=False)

    # the core read logic (binary sniff, line skipping, truncation) runs
    # entirely in a thread pool, keeping disk IO off the event loop
    return await asyncio.to_thread(_view_file_io, file_path, offset, limit, encoding)


def _glob_walk(
    root: str,
    parts: list[str],
    results: list[str],
    limits: dict[str, int | bool],
) -> None:
    """Recursive glob matching engine: matches directory entries segment by segment.

    Each recursion level consumes one part of the pattern:
    - plain segment: fnmatch against the current entry name, matched
      directories recurse into the remaining parts
    - ** segment: crosses any depth, first tries zero levels (skip **),
      then recurses into every subdirectory with the full pattern
    - EXCLUDE_DIRS / EXCLUDE_FILES prune both recursion and recording
    - limits is shared across recursion: total accumulates matches, once
      stop is set every in-flight call returns immediately

    Args:
        root:     absolute path of the directory being scanned.
        parts:    remaining pattern segments, e.g. ["**", "*.py"].
        results:  shared result list, matched paths append here, capped
                  by GLOB_MAX_RESULTS.
        limits:   shared counters and fuse flag, {"total": matches, "stop": fuse}.

    Returns:
        None; results are written to results and the fuse state to limits.
    """
    # fuse check: every recursion level first looks at whether the scan was stopped.
    # limits["total"] is shared; some branch pushed the count to 5000 and set
    # stop = True, but in-flight calls deeper in the tree are already on their
    # way, they see stop first thing and return immediately.
    if limits["stop"]:
        return

    # parts is empty: every segment is consumed, the current directory is a
    # full match, record it and return.
    if not parts:
        limits["total"] += 1
        if len(results) < GLOB_MAX_RESULTS:
            results.append(root)
        if limits["total"] >= GLOB_MAX_SCAN:
            limits["stop"] = True
        return

    # list every entry (files and subdirectories) of the current directory.
    # list() materializes the scandir iterator because the ** branch needs
    # multiple passes (zero levels then one level) and an iterator can only
    # be walked once.
    try:
        entries = list(os.scandir(root))
    except OSError:
        # silently skip unreadable or vanished directories: a search tool
        # should keep scanning elsewhere instead of aborting the whole search.
        return

    # head is the segment the current level must match, tail is the rest
    # example: parts: ["a", "b", "c"], head: "a", tails: ["b", "c"]
    head, *tail = parts

    # ** means "cross any depth": try zero levels (skip **) and one or more
    # levels (recurse into subdirectories).
    if head == "**":
        # zero levels: treat ** as absent and match the remaining pattern
        # against the current directory. When tail is empty, root itself is
        # recorded here; the one-level loop only recurses into directories
        # without recording, so each directory is recorded exactly once.
        _glob_walk(root, tail, results, limits)
        if limits["stop"]:
            return

        # one or more levels: subdirectories recurse with the full pattern;
        # files are recorded only when the pattern ends here
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in EXCLUDE_DIRS:
                    _glob_walk(entry.path, parts, results, limits)
            elif not tail:
                # ** matched the file itself (the pattern ends at **)
                if entry.name in EXCLUDE_FILES:
                    continue
                limits["total"] += 1
                if len(results) < GLOB_MAX_RESULTS:
                    results.append(entry.path)
                if limits["total"] >= GLOB_MAX_SCAN:
                    limits["stop"] = True

            if limits["stop"]:
                break
    else:
        # plain segment: fnmatch against entry names of the current level
        for entry in entries:
            if not fnmatch.fnmatch(entry.name, head):
                continue

            # segments remain: the matched entry must be a directory not in
            # the exclude list to recurse
            if tail:
                if entry.is_dir(follow_symlinks=False) and entry.name not in EXCLUDE_DIRS:
                    _glob_walk(entry.path, tail, results, limits)
            else:
                # the pattern ends here: skip excluded files and directories,
                # record the rest as matches
                if entry.name in EXCLUDE_FILES:
                    continue
                if entry.is_dir(follow_symlinks=False) and entry.name in EXCLUDE_DIRS:
                    continue

                limits["total"] += 1
                if len(results) < GLOB_MAX_RESULTS:
                    results.append(entry.path)
                if limits["total"] >= GLOB_MAX_SCAN:
                    limits["stop"] = True

            if limits["stop"]:
                break


def _glob_scan_io(
    search_dir: str,
    parts: list[str],
    pattern: str,
) -> str:
    """Core scan sync segment: recursive directory walk matching the pattern,
    tallying results and assembling the response JSON.

    Called by glob_tool via asyncio.to_thread; os.scandir traversal and
    fnmatch matching run in a thread pool and never block the event
    loop. _glob_walk is plain synchronous recursion and completes
    entirely inside this function, including RecursionError/OSError
    fallbacks and result tallying.

    Args:
        search_dir: absolute path of the search directory, validated by the safety chain.
        parts:      split pattern segments, e.g. ["**", "*.py"].
        pattern:    original glob pattern, used for the pattern field and message.

    Returns:
        JSON string with the same contract as glob_tool: on ok it carries
        pattern/count/files/truncated/message; on error only message.
    """
    # why list and dict instead of plain values?
    #     _glob_walk is recursive and every level wants to mutate the same
    #     result list and the same counter.
    #       - int and str are immutable: a copy is passed to the callee,
    #         changes inside one level are invisible to the others
    #       - list and dict are mutable: the same object reference is shared,
    #         appends from any level are visible to all
    #     so:
    #       - file_matches (list): every level appends its matches here
    #       - limits (dict): every level shares the scan counter and fuse flag
    #     limits is mutable state shared across recursion, which is why a dict
    #     is used instead of two ints, a child level mutating total would
    #     otherwise be invisible to the parent.
    file_matches: list[str] = []               # matched file paths
    limits = {"total": 0, "stop": False}       # scan counter and fuse flag

    try:
        _glob_walk(search_dir, parts, file_matches, limits)
    except RecursionError:
        # python recursion defaults to roughly 1k levels; on overflow, report
        # back to the LLM. Nobody should nest folders that deep anyway.
        return json.dumps({
            "status": "error",
            "message": "Scan failed: directory tree is too deep."
        }, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Scan failed: {exc}"
        }, ensure_ascii=False)

    # tally the match count, detect truncation, and return the JSON string
    total = min(limits["total"], GLOB_MAX_SCAN)
    file_matches.sort()
    truncated = total >= GLOB_MAX_SCAN or len(file_matches) >= GLOB_MAX_RESULTS
    return json.dumps({
        "status": "ok",
        "message": f"Found {total} files matching '{pattern}'" + (" (truncated)" if truncated else ""),
        "pattern": pattern,
        "count": total,
        "files": file_matches,
        "truncated": truncated,
    }, ensure_ascii=False)


async def glob_tool(
    pattern: str,
    dir_path: str = ".",
    allow_external_reads: bool = False,
) -> str:
    """Find files by glob pattern matching, returning matched file paths.

    The pattern must be relative; fnmatch wildcards (*, ?, [seq]) and **
    recursive subdirectory matching are supported. Excluded directories
    and files (EXCLUDE_DIRS / EXCLUDE_FILES) are pruned during the scan,
    and the result count and total scan are capped by GLOB_MAX_RESULTS
    and GLOB_MAX_SCAN.

    Execution model: argument validation and path safety checks run on
    the event loop (pure CPU); the directory scan (os.scandir recursion
    plus fnmatch matching) runs in a thread pool via asyncio.to_thread,
    keeping disk IO off the event loop.

    Args:
        pattern:              glob pattern, e.g. **/*.py or src/*.py, ** crosses any depth.
        dir_path:             search directory, default '.' (workspace root, or a subdirectory).
        allow_external_reads: whether to allow searching outside the workspace.

    Returns:
        JSON string. On ok: pattern, count (total matches), files (list
        of matched paths), truncated (whether a limit was hit), and a
        message summarizing the count. On error: only message.

    Notes:
        - ** is usually combined with other segments (e.g. **/*.py);
          a bare ** matches everything, files and directories
        - excluded directories (.git, .venv, node_modules, etc.) are
          neither returned nor entered; point dir_path at one to search inside it
        - files holds at most GLOB_MAX_RESULTS entries; truncated=True
          when the total exceeds the cap
    """
    # empty pattern: argument error
    if not pattern or not pattern.strip():
        return json.dumps({
            "status": "error",
            "message": "pattern must not be empty."
        }, ensure_ascii=False)

    # reject absolute path patterns
    if os.path.isabs(pattern):
        return json.dumps({
            "status": "error",
            "message": "pattern must be relative, absolute paths are not allowed."
        }, ensure_ascii=False)

    # reject path traversal components
    if ".." in pattern.split(os.sep):
        return json.dumps({
            "status": "error",
            "message": "pattern must not contain '..' components."
        }, ensure_ascii=False)

    # empty dir_path: argument error
    if not dir_path or not dir_path.strip():
        return json.dumps({
            "status": "error",
            "message": "dir_path must not be empty."
        }, ensure_ascii=False)

    # get the workspace directory; this is a hard requirement, fail fast when missing
    workspace = settings.workspace_dir
    if not workspace:
        raise RuntimeError("WORKSPACE_DIR is not configured, please set it up.")
    workspace = os.path.abspath(workspace)

    # resolve all symlinks on top of abspath, returning the real path on disk
    try:
        safe_root = os.path.realpath(workspace)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot resolve workspace: {exc}"
        }, ensure_ascii=False)

    # expand the user home directory
    dir_path = os.path.expanduser(dir_path)

    # join workspace + dir_path to locate the search directory `search_dir`
    try:
        if not os.path.isabs(dir_path):
            search_dir = os.path.realpath(os.path.join(safe_root, dir_path))
        else:
            search_dir = os.path.realpath(dir_path)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Invalid path: {exc}"
        }, ensure_ascii=False)

    # normalize the boundary: the workspace root ends with exactly one
    # separator, preventing prefix-match traps
    safe_root = safe_root.rstrip(os.sep) + os.sep

    # boundary check: without allow_external_reads, a search directory
    # outside the workspace is rejected
    if not allow_external_reads and not (search_dir + os.sep).startswith(safe_root):
        return json.dumps({
            "status": "error",
            "message": f"Access to '{dir_path}' is denied."
        }, ensure_ascii=False)

    # the search directory must exist
    if not os.path.isdir(search_dir):
        return json.dumps({
            "status": "error",
            "message": f"'{search_dir}' is not a directory."
        }, ensure_ascii=False)

    # prepare pattern segments for the recursive glob engine
    # example: **/*.py -> ['**', '*.py'], orchestration/tools/*.py -> ["orchestration", "tools", "*.py"]
    parts = [p for p in pattern.split("/") if p]

    # empty segment check
    if not parts:
        return json.dumps({
            "status": "error",
            "message": "pattern must not be empty."
        }, ensure_ascii=False)

    # the core scan (recursive tree walk plus result tallying) runs entirely
    # in a thread pool, keeping disk IO off the event loop
    return await asyncio.to_thread(_glob_scan_io, search_dir, parts, pattern)


def _grep_io(
    real_path: str,
    re_compiled: re.Pattern,
    pattern: str,
    glob_pattern: str | None,
    output_mode: str,
    context_lines: int,
    head_limit: int,
    offset: int,
    multiline: bool,
    encoding: str,
    allow_external_reads: bool,
    safe_root: str,
) -> str:
    """Core search sync segment: file collection (os.walk), per-file read
    and match, result rendering, return JSON.

    Called by grep_tool via asyncio.to_thread; directory traversal, file
    reads and regex matching run in a thread pool and never block the
    event loop. The GREP_TOTAL_TIMEOUT_SECONDS overall budget (shared by
    collection and search) and the REGEX_MATCH_TIMEOUT_SECONDS per-line
    fuse both take effect inside this function, matching the original
    semantics exactly.

    Args:
        real_path:            absolute search path (file or directory), validated by the safety chain.
        re_compiled:          precompiled regex with IGNORECASE/DOTALL flags.
        pattern:              original regex, used for the response message.
        glob_pattern:         basename filter pattern, None means no filtering.
        output_mode:          one of files_with_matches, content, count.
        context_lines:        context lines around each match (0-10).
        head_limit:           maximum result count (0-1000, 0 means unlimited).
        offset:               skip the first N results.
        multiline:            whether multiline matching is enabled (DOTALL).
        encoding:             file encoding.
        allow_external_reads: whether to allow searching outside the workspace, rechecked before reads.
        safe_root:            normalized workspace root, ending with a separator.

    Returns:
        JSON string with the same contract as grep_tool: on ok it carries
        output_mode-specific fields (files/results/total_matches/truncated,
        etc.); on error only message.
    """
    # file collection phase
    # before any regex matching, build the list of files to read
    # the user passes a path
    #   path is a single file: files = [that file], traversal skipped
    #   path is a directory: full os.walk traversal plus layered filters
    # then each file is read and matched (code after this section)
    # why two phases?
    #   filtering (excluded dirs, names, caps) must happen before file
    #   contents are read, otherwise a pile of never-searched files would
    #   be read, wasting a lot of IO
    files = []                              # collected files
    files_truncated = False                 # whether collection hit the GREP_MAX_FILES cap

    # total time budget: hard wall-clock cap for the whole call (collection
    # plus search), using a monotonic clock immune to system time changes;
    # on timeout the partial results are returned with search_timed_out set,
    # not an error
    _deadline = time.monotonic() + GREP_TOTAL_TIMEOUT_SECONDS
    search_timed_out = False

    if os.path.isfile(real_path):
        files.append(real_path)
    else:
        try:
            # walk the real_path directory, collecting all files and subdirectories
            for dirpath, dirnames, filenames in os.walk(real_path):
                # budget check: walking a huge tree also consumes the budget, stop collecting on timeout
                if time.monotonic() > _deadline:
                    search_timed_out = True
                    break
                # prune excluded directories
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

                # for every file name
                for fname in filenames:
                    # skip excluded file names
                    if fname in EXCLUDE_FILES:
                        continue
                    # hit the file cap: mark truncation and stop collecting
                    if len(files) >= GREP_MAX_FILES:
                        files_truncated = True
                        break

                    # build the full path
                    full_path = os.path.join(dirpath, fname)
                    # with a glob pattern, filter by file name (basename)
                    # never match on a path with segments: fnmatch '*' crosses
                    # '/', and an exact pattern without wildcards (e.g. "b.py")
                    # would be broken by path segments, silently dropping
                    # same-named files in subdirectories
                    if glob_pattern and not fnmatch.fnmatch(os.path.basename(full_path), glob_pattern):
                        continue
                    # append the full path to files[]
                    files.append(full_path)

                # stop the walk when the collection cap is hit
                if files_truncated:
                    break
        # catch traversal errors
        except OSError as exc:
            if not files:
                return json.dumps({
                    "status": "error",
                    "message": f"Cannot traverse directory: {exc}"
                }, ensure_ascii=False)

    # search execution phase
    # walk the collected files list, read, match and collect per file
    skipped_large_files: list[str] = []             # files skipped for exceeding GREP_MAX_FILE_SIZE, reported in the response
    timed_out_files: list[str] = []                 # files interrupted by regex timeout, reported in the response
    file_matches: list[dict] = []                   # matches, each {file, line_num, line_text}
    _content_cache: dict[str, str] = {}             # content cache, {file path: file content}

    # for every file in the files list
    for file_path in files:
        # fuse: stop processing remaining files once the budget is exhausted
        if search_timed_out:
            break
        try:
            # why check again when it was checked before?
            # 1. TOCTOU race: the file list was collected during traversal
            #    but reads happen afterwards. If a file was swapped for a
            #    symlink pointing outside, the sandbox check from collection
            #    time is stale, safe at check time, dangerous at use time.
            #    Rechecking before the read closes the race window.
            # 2. single-file branch gap: the previous section appended
            #    real_path directly after os.path.isfile without a sandbox
            #    check, collection only tested isfile. This recheck also
            #    covers the single-file path.
            # sandbox check: the file must stay under the workspace root, never escape
            if not allow_external_reads and not os.path.realpath(file_path).startswith(safe_root):
                continue

            # skip files larger than GREP_MAX_FILE_SIZE
            if os.path.getsize(file_path) > GREP_MAX_FILE_SIZE:
                skipped_large_files.append(file_path)
                continue

            # binary sniff: same policy as view_file, NUL bytes in the head;
            # UTF-16/UTF-32 encodings naturally contain NUL, so they are whitelisted.
            # grep is a batch scan: a binary hit counts as unreadable and is
            # silently skipped (same semantics as decode failure)
            with open(file_path, "rb") as f:
                head = f.read(BINARY_SNIFF_BYTES)
            if b"\x00" in head and not encoding.lower().startswith(("utf-16", "utf-32")):
                continue

            # read the file content
            with open(file_path, "r", encoding=encoding) as f:
                file_content = f.read()

        # silently skip undecodable files
        except UnicodeDecodeError:
            continue
        # silently skip unreadable files
        except OSError:
            continue
        # unexpected exception fallback: the regex library may raise
        # non-TimeoutError exceptions (e.g. overly nested patterns); a single
        # file failure is skipped silently, never aborting the whole search
        except Exception:
            continue

        # record the match count before this file
        _matches_before = len(file_matches)

        # multiline mode: append every match to file_matches
        if multiline:
            try:
                for _match_i, m in enumerate(re_compiled.finditer(
                        file_content, timeout=REGEX_MATCH_TIMEOUT_SECONDS), 1):
                    # budget check: wall clock every 1024 matches, fuse the whole
                    # search on timeout (huge match counts would otherwise
                    # accumulate unbounded time)
                    if _match_i % 1024 == 0 and time.monotonic() > _deadline:
                        search_timed_out = True
                        break
                    line_num = file_content[:m.start()].count("\n") + 1
                    # the full line at the match start: a match may begin
                    # mid-line (e.g. 'bar.*foo' hitting the middle of a line),
                    # group(0) would drop the line prefix, so slice by line
                    # boundaries from the source
                    line_start = file_content.rfind("\n", 0, m.start()) + 1
                    line_end = file_content.find("\n", m.start())
                    if line_end == -1:
                        line_end = len(file_content)
                    line_text = file_content[line_start:line_end]
                    file_matches.append({
                        "file": file_path,
                        "line_num": line_num,
                        "line_text": line_text.rstrip()
                    })
            # per-line regex fuse against catastrophic backtracking,
            # e.g. (a+)+$ against "aaaaaaaaaaaaaaaaaaaaaaaab" explodes
            # backtracking exponentially with input length and can hang
            # the process for tens of minutes
            except TimeoutError:
                timed_out_files.append(file_path)
        else:
            lines = file_content.split("\n")

            # walk every line and record matches
            for line_num, line_text in enumerate(lines, start=1):
                # budget check: wall clock every 1024 lines (monotonic is
                # ~100ns per call, negligible); fusing the whole search, the
                # per-line timeout only guards backtracking, not the
                # accumulated cost of many normal lines
                if line_num % 1024 == 0 and time.monotonic() > _deadline:
                    search_timed_out = True
                    break
                try:
                    if re_compiled.search(line_text, timeout=REGEX_MATCH_TIMEOUT_SECONDS):
                        file_matches.append({
                            "file": file_path,
                            "line_num": line_num,
                            "line_text": line_text.rstrip()
                        })
                # guard against catastrophic backtracking
                except TimeoutError:
                    timed_out_files.append(file_path)
                    break

        # search timeout: the whole-call budget is exhausted, stop processing
        # remaining files (partial results are returned)
        if search_timed_out:
            break

        # only content mode consumes the cache (others use file/line_num/line_text),
        # avoid caching for nothing
        if output_mode == "content" and len(file_matches) > _matches_before:
            _content_cache[file_path] = file_content

    # total match count (not file count): one file may contribute many
    # matches. It anchors every later decision: paging (offset >=
    # total_matches), truncation (truncated = offset + len(page) <
    # total_matches), and the three output modes.
    total_matches = len(file_matches)

    # no matches: return an empty result body
    if total_matches == 0:
        # build the empty-result message and return
        msg = f"No matches for '{pattern}' in {len(files)} files"
        if files_truncated:
            msg += f" (file list truncated at {GREP_MAX_FILES})"
        if skipped_large_files:
            msg += f", {len(skipped_large_files)} large files skipped (>{GREP_MAX_FILE_SIZE // 1024 // 1024} MB)"
        if timed_out_files:
            msg += f", {len(timed_out_files)} files timed out"
        if search_timed_out:
            msg += ", search timed out, results may be incomplete"
        return json.dumps({
            "status": "ok",
            "output_mode": output_mode,
            "message": msg,
            "total_matches": 0,
            "total_files": 0,
            "files_scanned": len(files),
            "files_truncated": files_truncated,
            "skipped_large_files": len(skipped_large_files),
            "timed_out_files": len(timed_out_files),
            "search_timed_out": search_timed_out,
        }, ensure_ascii=False)

    # paging out of range: return an error
    if offset >= total_matches:
        return json.dumps({
            "status": "error",
            "message": f"offset {offset} exceeds total matches {total_matches}"
        }, ensure_ascii=False)

    # result rendering phase
    # search done (total_matches known), now render file_matches into one
    # of three views for the LLM
    page_matches = file_matches[offset:offset + head_limit] if head_limit > 0 else file_matches[offset:]
    truncated = (offset + len(page_matches)) < total_matches
    _page_file_set = {m["file"] for m in page_matches}
    _content_cache = {k: v for k, v in _content_cache.items() if k in _page_file_set}

    # output mode A: only the matched file names
    if output_mode == "files_with_matches":
        # deduplicate while preserving order
        visited_files_set: set[str] = set()
        unique_files_list: list[str] = []

        # keep only the first occurrence for each file
        for m in page_matches:
            if m["file"] not in visited_files_set:
                visited_files_set.add(m["file"])
                unique_files_list.append(m["file"])

        return json.dumps({
            "status": "ok",
            "output_mode": "files_with_matches",
            "files": unique_files_list,
            "total_files": len(unique_files_list),
            "total_matches": total_matches,
            "truncated": truncated,
            "files_scanned": len(files),
            "files_truncated": files_truncated,
            "skipped_large_files": len(skipped_large_files),
            "timed_out_files": len(timed_out_files),
            "search_timed_out": search_timed_out,
            "page": {"offset": offset, "limit": head_limit},
        }, ensure_ascii=False)

    # output mode B: matched file names with occurrence counts
    if output_mode == "count":
        file_counts: dict[str, int] = {}

        for m in page_matches:
            fp = m["file"]
            file_counts[fp] = file_counts.get(fp, 0) + 1

        return json.dumps({
            "status": "ok",
            "output_mode": "count",
            "results": file_counts,
            "total_occurrences": sum(file_counts.values()),
            "total_files": len(file_counts),
            "total_matches": total_matches,
            "truncated": truncated,
            "files_scanned": len(files),
            "files_truncated": files_truncated,
            "skipped_large_files": len(skipped_large_files),
            "timed_out_files": len(timed_out_files),
            "search_timed_out": search_timed_out,
            "page": {"offset": offset, "limit": head_limit},
        }, ensure_ascii=False)

    # output mode C: matched content with context lines around each match
    if output_mode == "content":
        # line cache: one file may have many matches and context rendering
        # repeatedly fetches lines, so read from disk only once.
        # lookup order: the search-phase _content_cache (full content already
        # in memory) first, falling back to disk on a miss.
        _file_lines_cache: dict[str, list[str]] = {}

        def _get_lines(fp: str) -> list[str]:
            """Get the line list for a file path, cached; empty list on read failure.

            Cache priority: _content_cache first (files fully read during
            the search phase), falling back to disk on a miss.
            UnicodeDecodeError / OSError count as unreadable and return
            an empty list so the caller skips the file, matching the
            silent skip policy of the search phase.

            Args:
                fp: absolute path of the file.

            Returns:
                list of lines split on "\n"; empty list when the read fails.
            """
            if fp not in _file_lines_cache:
                if fp in _content_cache:
                    _file_lines_cache[fp] = _content_cache[fp].split("\n")
                else:
                    try:
                        with open(fp, "r", encoding=encoding) as f:
                            _file_lines_cache[fp] = f.readlines()
                    except (UnicodeDecodeError, OSError):
                        _file_lines_cache[fp] = []

            return _file_lines_cache[fp]

        # group by file: all matches of a file stay together, so each file
        # renders its context once
        file_groups: dict[str, list[dict]] = {}

        for m in page_matches:
            fp = m["file"]
            file_groups.setdefault(fp, []).append(m)

        results: dict[str, list[list[dict]]] = {}

        # render per file: expand each match into a context chunk (the match
        # line plus context_lines around it)
        for fp, matches in file_groups.items():
            file_lines = _get_lines(fp)

            # an empty line list means the file is unreadable (or undecodable),
            # skip rendering it
            if not file_lines:
                continue

            chunks: list[list[dict]] = []

            for m in matches:
                # convert the match line number to 0-based index, expand by
                # context_lines on both sides, clamp to file bounds
                line_idx = m["line_num"] - 1
                start = max(0, line_idx - context_lines)
                end = min(len(file_lines), line_idx + context_lines + 1)
                chunk: list[dict] = []

                # emit line by line: match marks the true hit line, for the LLM to locate
                for i in range(start, end):
                    chunk.append({
                        "line_num": i + 1,
                        "content": file_lines[i].rstrip("\n"),
                        "match": (i + 1 == m["line_num"]),
                    })

                chunks.append(chunk)

            # final shape: {absolute path: [context chunks, ...]}, one chunk per match
            results[fp] = chunks

        return json.dumps({
            "status": "ok",
            "output_mode": "content",
            "results": results,
            "total_matches": total_matches,
            "truncated": truncated,
            "files_scanned": len(files),
            "files_truncated": files_truncated,
            "skipped_large_files": len(skipped_large_files),
            "timed_out_files": len(timed_out_files),
            "search_timed_out": search_timed_out,
            "page": {"offset": offset, "limit": head_limit},
        }, ensure_ascii=False)

    # this branch is unreachable, every possible output_mode was handled above
    return json.dumps({
        "status": "error",
        "message": f"Invalid output_mode: {output_mode}"
    }, ensure_ascii=False)


async def grep_tool(
    pattern: str,
    path: str = ".",
    glob_pattern: str | None = None,
    output_mode: str = "files_with_matches",
    context_lines: int = 2,
    head_limit: int = 200,
    offset: int = 0,
    case_sensitive: bool = True,
    multiline: bool = False,
    encoding: str = "utf-8",
    allow_external_reads: bool = False,
) -> str:
    """Search file content with a regular expression.

    Execution model: argument validation, regex precompilation and path
    safety checks run on the event loop (pure CPU); file collection
    (os.walk), per-file reads, regex matching and result rendering run in
    a thread pool via asyncio.to_thread, keeping disk IO and CPU-heavy
    matching off the event loop.

    Args:
        pattern:              the regular expression to search for.
        path:                 file or directory to search, default '.' (workspace root).
        glob_pattern:         filter files by name before searching (glob pattern).
        output_mode:          output mode, one of ``files_with_matches``, ``content``, ``count``.
        context_lines:        context lines around each match (0-10).
        head_limit:           maximum result count (0-1000, 0 means unlimited).
        offset:               skip the first N results.
        case_sensitive:       whether matching is case-sensitive (default True).
        multiline:            whether ``.`` matches newlines (default False).
        encoding:             file encoding (default utf-8).
        allow_external_reads: whether to allow searching outside the workspace.

    Returns:
        JSON with matches, counts and paging information. The files key
        (files_with_matches) and the results keys (count/content) are
        absolute paths, consistent with view_file and glob_tool.

    Notes:
        - the whole search has a total time budget
          (GREP_TOTAL_TIMEOUT_SECONDS); on timeout the partial results
          already collected are returned with search_timed_out=True
          meaning the results are incomplete
        - a per-line regex timeout (REGEX_MATCH_TIMEOUT_SECONDS) fuses
          that file and counts it in timed_out_files
    """
    # required check: empty pattern, argument error
    if not pattern or not pattern.strip():
        return json.dumps({
            "status": "error",
            "message": "pattern must not be empty."
        }, ensure_ascii=False)

    # required check: empty path, argument error
    if not path or not path.strip():
        return json.dumps({
            "status": "error",
            "message": "path must not be empty."
        }, ensure_ascii=False)

    # optional check: glob_pattern, when given, must be a non-empty string
    if isinstance(glob_pattern, str) and not glob_pattern.strip():
        return json.dumps({
            "status": "error",
            "message": "glob_pattern must not be empty."
        }, ensure_ascii=False)

    # note: grep_tool glob_pattern only narrows the match scope, it does not
    # support complex features like **; '**' is equivalent to '*' in fnmatch
    # (basename matching) with no recursion semantics, reject it to avoid confusion
    if isinstance(glob_pattern, str) and "**" in glob_pattern.split("/"):
        return json.dumps({
            "status": "error",
            "message": (
                "glob_pattern does not support '**' (it matches file names only, "
                "'**' is equivalent to '*'). For recursive searches use glob_tool."
            )
        }, ensure_ascii=False)

    # glob_pattern matches file names (basename) only, reject absolute paths
    # and traversal components: a pattern with '/' can never match a
    # basename, fail early instead of returning confusing empty results
    if isinstance(glob_pattern, str):
        if os.path.isabs(glob_pattern):
            return json.dumps({
                "status": "error",
                "message": (
                    "glob_pattern must be relative (matches file names only), "
                    "absolute paths are not allowed."
                )
            }, ensure_ascii=False)
        if ".." in glob_pattern.split(os.sep):
            return json.dumps({
                "status": "error",
                "message": (
                    "glob_pattern must not contain '..' components "
                    "(matches file names only)."
                )
            }, ensure_ascii=False)
        # fallback: a plain relative pattern (e.g. "src/*.py") can never
        # match a basename either, point the user at the path parameter
        # instead of embedding directories in glob_pattern
        if "/" in glob_pattern:
            return json.dumps({
                "status": "error",
                "message": (
                    "glob_pattern matches file names only; path separators are not allowed. "
                    "To scope the search to a subdirectory, use the path parameter."
                )
            }, ensure_ascii=False)

    # optional check: output_mode must be one of the three
    if output_mode not in ("files_with_matches", "content", "count"):
        return json.dumps({
            "status": "error",
            "message": f"Unknown output_mode: '{output_mode}'. Available: files_with_matches | content | count"
        }, ensure_ascii=False)

    # optional check: context_lines must be an integer in 0-10
    # note: bool is an int subclass and True < 10 holds, exclude it explicitly
    if (not isinstance(context_lines, int) or isinstance(context_lines, bool)
            or context_lines < 0 or context_lines > 10):
        return json.dumps({
            "status": "error",
            "message": "context_lines must be an integer between 0 and 10."
        }, ensure_ascii=False)

    # optional check: head_limit must be an integer in 0-1000
    # (0 means unlimited, exclude bool)
    if (not isinstance(head_limit, int) or isinstance(head_limit, bool)
            or head_limit < 0 or head_limit > 1000):
        return json.dumps({
            "status": "error",
            "message": "head_limit must be an integer between 0 and 1000."
        }, ensure_ascii=False)

    # optional check: offset must be a non-negative integer (exclude bool)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return json.dumps({
            "status": "error",
            "message": "offset must be a non-negative integer."
        }, ensure_ascii=False)

    # validate the regex by compiling once, reused by the main logic (no
    # per-file recompilation across many files).
    # note: multiline means "let . match newlines", i.e. re.DOTALL, not
    # re.MULTILINE; case_sensitive=False enables IGNORECASE.
    try:
        flags = 0
        if not case_sensitive:
            flags |= re.IGNORECASE
        if multiline:
            flags |= re.DOTALL
        re_compiled = re.compile(pattern, flags)
    except re.error as exc:
        return json.dumps({
            "status": "error",
            "message": f"Invalid regex pattern: {exc}"
        }, ensure_ascii=False)

    # get the workspace directory; this is a hard requirement, fail fast when missing
    workspace = settings.workspace_dir
    if not workspace:
        raise RuntimeError("WORKSPACE_DIR is not configured, please set it up.")
    workspace = os.path.abspath(workspace)

    # resolve all symlinks on top of abspath, returning the real path on disk
    try:
        safe_root = os.path.realpath(workspace)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot resolve workspace: {exc}"
        }, ensure_ascii=False)

    # expand the user home directory
    path = os.path.expanduser(path)

    # join workspace + path to locate the search path `real_path`
    try:
        if not os.path.isabs(path):
            real_path = os.path.realpath(os.path.join(safe_root, path))
        else:
            real_path = os.path.realpath(path)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Invalid path: {exc}"
        }, ensure_ascii=False)

    # normalize the boundary: the workspace root ends with exactly one
    # separator, preventing prefix-match traps
    safe_root = safe_root.rstrip(os.sep) + os.sep

    # boundary check: file_path must stay inside the workspace
    if not allow_external_reads and not (real_path + os.sep).startswith(safe_root):
        return json.dumps({
            "status": "error",
            "message": f"Access to '{path}' is denied."
        }, ensure_ascii=False)

    # existence check: path may be a file or a directory, only existence is
    # tested, the type fork is handled by the main logic
    if not os.path.exists(real_path):
        return json.dumps({
            "status": "error",
            "message": f"'{real_path}' does not exist."
        }, ensure_ascii=False)

    # the core search (file collection, per-file read and match, result
    # rendering) runs entirely in a thread pool; the GREP_TOTAL_TIMEOUT_SECONDS
    # budget and per-line fuse take effect inside _grep_io, keeping disk IO
    # and regex matching off the event loop
    return await asyncio.to_thread(
        _grep_io,
        real_path, re_compiled, pattern, glob_pattern, output_mode,
        context_lines, head_limit, offset, multiline, encoding,
        allow_external_reads, safe_root,
    )
