"""Workspace write filesystem tools implementation.

Provides:
- str_replace:  atomically replace exact text in a file (CAS semantics, old_str must be unique or replace_all)
- write_file:   atomically create or overwrite a file (parent dirs auto-created, new file mode follows umask)
- clean_dir:    safely delete files or directories inside the workspace, workspace only

Key constraints:
- all tools return JSON strings with status ok or error and never raise,
  except one case: a missing workspace raises RuntimeError, a config
  error rather than a business error
- paths are strictly confined to the workspace (no escape switch):
  realpath normalization plus a boundary prefix check, sharing the same
  safety chain as _fs_readonly; clean_dir additionally protects the
  workspace root
- write atomicity: mkstemp temp file in the same directory plus mode
  restore plus os.replace (inode swap); finally cleans up the temp
  file, no failure ever leaves a half-written file
- concurrency: per-path asyncio.Lock cached by realpath in a
  WeakValueDictionary, shared by all three tools; clean_dir takes the
  same per-item locks before deleting, mutually excluding writes and
  replaces (prevents delete-then-resurrect); directory deletion first
  atomically renames it away, then recursively deletes (prevents new
  writes during deletion from being removed by mistake)
- hard resource limits: MAX_WRITE_SIZE (1MB content, byte semantics),
  MAX_DIFF_SIZE (50-char diff truncation), CLEAN_MAX_ITEMS (500 items
  per call, precheck before acting)
- encoding guard: invalid encodings (LookupError/TypeError) and
  unencodable characters (UnicodeEncodeError) are intercepted before
  touching the disk, no half-written files
- idempotency: write_file returns [UNCHANGED] without writing when the
  content matches the original; the original is fully read for
  comparison only when <= 1MB, larger files skip the read and are
  overwritten directly (byte counts must differ); diff.old is empty
  when the original content is unknown (read/stat failure or size cap),
  never blocking the write
- deletion is not rollback-able: on partial failure the error response
  carries deleted/count reporting the progress

Usage notes:
- str_replace old_str is an exact match; multiple occurrences require
  replace_all=True, otherwise an error is returned
- write_file content must be a string (empty string is legal, writing
  an empty file); size is measured in bytes
- clean_dir patterns match file/dir names only (fnmatch basename
  semantics), no ** and no path separators; None/[] deletes dir_path
  recursively as a whole (a file target deletes the file)
- clean_dir deletes the link itself, never what the link points to
- encoding errors echo the exception detail to help diagnose
- read-only tools live in _fs_readonly
"""

import os
import json
import asyncio
import tempfile
import weakref
import fnmatch
import shutil
import uuid

from core.tools._kernel.constants import (
    MAX_WRITE_SIZE,
    MAX_DIFF_SIZE,
    CLEAN_MAX_ITEMS,
)
from utils.settings import settings


# weakref dict holding a per-file async lock, so locks are garbage
# collected once no coroutine holds a reference
_file_locks: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_clean_lock = asyncio.Lock()


def _get_file_lock(file_path: str) -> asyncio.Lock:
    """Return a per-file async lock serializing writes to the same path.

    A WeakValueDictionary is used so a lock is garbage collected once no
    coroutine holds a reference, preventing unbounded growth in a
    long-running session.

    Args:
        file_path: absolute file path (already normalized), the lock key.

    Returns:
        the asyncio.Lock instance for that path.
    """
    lock = _file_locks.get(file_path)
    if lock is None:
        lock = asyncio.Lock()
        _file_locks[file_path] = lock
    return lock


def _str_replace_io(
    file_path: str,
    old_str: str,
    new_str: str,
    replace_all: bool,
    encoding: str,
) -> str:
    """Lock-critical-section sync segment: byte precheck, read, match,
    atomic replace, return JSON.

    Called by str_replace via asyncio.to_thread while holding the path
    lock, so disk IO and text processing run in a thread pool and never
    block the event loop. This function does not take the lock itself;
    it assumes the caller guarantees mutual exclusion on the same path
    (the critical section runs atomically as a whole, the
    mkstemp, write, chmod, replace sequence must not be split).

    Args:
        file_path:   target file path, workspace-internal absolute path validated by the safety chain.
        old_str:     exact text to replace, whitespace included, must match exactly.
        new_str:     replacement text (empty string is legal, meaning deletion).
        replace_all: whether to replace every occurrence.
        encoding:    file encoding.

    Returns:
        JSON string with status, path and a diff summary.
    """
    # byte-level size precheck: in multibyte encodings the char count is
    # always <= the byte count, so a char-level check could be bypassed by
    # a large file (e.g. 2MB of Chinese); getsize is byte semantics,
    # exactly matching the limit
    try:
        file_size = os.path.getsize(file_path)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot stat {file_path}: {exc}"
        }, ensure_ascii=False)

    # size check: the file must not exceed the limit
    if file_size > MAX_WRITE_SIZE:
        return json.dumps({
            "status": "error",
            "message": f"File '{file_path}' exceeds {MAX_WRITE_SIZE // 1024 // 1024}MB limit."
        }, ensure_ascii=False)

    # size is confirmed <= 1MB bytes, a full read cannot overload memory
    try:
        with open(file_path, "r", encoding=encoding) as f:
            content = f.read()
    except UnicodeDecodeError:
        return json.dumps({
            "status": "error",
            "message": f"{file_path} cannot be decoded as {encoding}. Retry with encoding='gbk' or 'latin-1'."
        }, ensure_ascii=False)
    except PermissionError:
        return json.dumps({
            "status": "error",
            "message": f"Permission denied: '{file_path}'."
        }, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot read {file_path}: {exc}"
        }, ensure_ascii=False)
    # unexpected exception fallback: never abort the whole call (same policy as _fs_readonly)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Unexpected error reading {file_path}: {exc}"
        }, ensure_ascii=False)

    # match check: old_str must exist in the file
    count = content.count(old_str)
    if count == 0:
        return json.dumps({
            "status": "error",
            "message": f"Text not found in {file_path}. Use view_file to verify file content."
        }, ensure_ascii=False)

    # special case: old_str and new_str identical, nothing to do; the
    # response contract matches a normal replace (path plus the same diff
    # shape, count is the actual occurrence count)
    if old_str == new_str:
        return json.dumps({
            "status": "ok",
            "message": f"[UNCHANGED] No changes to '{file_path}' — old_str and new_str are identical.",
            "path": file_path,
            "diff": {
                "old": old_str[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(old_str) > MAX_DIFF_SIZE else old_str,
                "new": new_str[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(new_str) > MAX_DIFF_SIZE else new_str,
                "count": count,
                "replace_all": replace_all,
            },
        }, ensure_ascii=False)

    # special case: multiple occurrences without replace_all, reject
    if count > 1 and not replace_all:
        return json.dumps({
            "status": "error",
            "message": f"Text matches {count} occurrences in {file_path}. Add more context to make it unique, or use replace_all=True."
        }, ensure_ascii=False)

    # build the new content: replace_all replaces every occurrence, otherwise only the first
    if replace_all:
        new_content = content.replace(old_str, new_str)
    else:
        new_content = content.replace(old_str, new_str, 1)

    # create the temp file in the same directory as the target, so
    # os.replace stays atomic on one filesystem
    # mkstemp / os.stat may raise OSError (read-only dir, file deleted
    # concurrently, etc.), must be covered by the fallback
    tmp_path: str | None = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(file_path))
        # save the original mode for restore
        orig_mode = os.stat(file_path).st_mode
        # write the temp file
        with os.fdopen(tmp_fd, "w", encoding=encoding) as f:
            f.write(new_content)
        # restore the original mode
        os.chmod(tmp_path, orig_mode)
        # atomically replace the original
        os.replace(tmp_path, file_path)
    except UnicodeEncodeError:
        return json.dumps({
            "status": "error",
            "message": f"new_str contains characters not encodable as {encoding}. Try encoding='utf-8'."
        }, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot write to {file_path}: {exc}"
        }, ensure_ascii=False)
    # unexpected exception fallback: a write-phase failure never aborts
    # (finally still cleans the temp file)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Unexpected error writing {file_path}: {exc}"
        }, ensure_ascii=False)
    finally:
        # clean up the temp file (None when mkstemp failed, skip)
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            # unlink failure is ignored: no other exception is pending, and
            # one cleanup error must not fail the whole replace
            except OSError:
                pass

    # return the result
    return json.dumps({
        "status": "ok",
        "message": f"[REPLACED{' ALL' if replace_all else ''}] {file_path}"
                   + (f" ({count} occurrences)" if replace_all and count > 0 else ""),
        "path": file_path,
        "diff": {
            "old": old_str[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(old_str) > MAX_DIFF_SIZE else old_str,
            "new": new_str[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(new_str) > MAX_DIFF_SIZE else new_str,
            "count": count if replace_all else 1,
            "replace_all": replace_all,
        },
    }, ensure_ascii=False)


async def str_replace(
    file_path: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
    encoding: str = "utf-8",
) -> str:
    """Atomically replace exact text in a file.

    old_str must occur exactly once in the file (or replace_all=True).

    Args:
        file_path:   target file path (workspace-relative or absolute).
        old_str:     exact text to replace, whitespace included, must match exactly.
        new_str:     replacement text.
        replace_all: whether to replace every occurrence (default False).
        encoding:    file encoding (default utf-8).

    Returns:
        JSON string with status, path and a diff summary.

    Execution model: argument validation and path safety checks run on
    the event loop (pure CPU); the lock-critical section (disk IO and
    text processing) runs in a thread pool via asyncio.to_thread; the
    path lock (asyncio.Lock) is acquired and released on the event loop.
    """
    # validate file_path: non-empty string
    # a non-str value (e.g. a number) would blow up with AttributeError at
    # strip(), LLM arguments are untrusted and must be intercepted
    if not isinstance(file_path, str) or not file_path.strip():
        return json.dumps({
            "status": "error",
            "message": "file_path must be a non-empty string."
        }, ensure_ascii=False)

    # validate old_str: non-empty string
    # note: only emptiness is checked, no strip, replacing whitespace or
    # indentation is a legitimate use (unlike regex pattern semantics)
    if not isinstance(old_str, str) or not old_str:
        return json.dumps({
            "status": "error",
            "message": "old_str must be a non-empty string."
        }, ensure_ascii=False)

    # validate new_str: must be a string (empty is legal, meaning deletion;
    # None/numbers would raise TypeError at replace())
    if not isinstance(new_str, str):
        return json.dumps({
            "status": "error",
            "message": "new_str must be a string."
        }, ensure_ascii=False)

    # validate encoding
    # note: a non-string encoding (None/number) raises TypeError, not
    # LookupError, intercept both
    try:
        "".encode(encoding)
    except (LookupError, TypeError):
        return json.dumps({
            "status": "error",
            "message": f"Unknown encoding: '{encoding}'. Try 'utf-8', 'gbk', or 'latin-1'."
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
    file_path = os.path.expanduser(file_path)

    # resolve the file path to an absolute one
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

    # normalize the boundary: the workspace root ends with exactly one
    # separator, preventing prefix-match traps
    safe_root = safe_root.rstrip(os.sep) + os.sep

    # boundary check: file_path must stay inside the workspace
    if not file_path.startswith(safe_root):
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

    # hold the file lock and run the whole critical section (byte precheck,
    # read, match, atomic replace) in a thread pool, keeping disk IO off the
    # event loop; the lock is acquired and released on the event loop
    async with _get_file_lock(file_path):
        return await asyncio.to_thread(
            _str_replace_io, file_path, old_str, new_str, replace_all, encoding
        )


def _write_file_io(
    file_path: str,
    content: str,
    encoding: str,
) -> str:
    """Lock-critical-section sync segment: existence check, read old
    content, UNCHANGED decision, atomic write, return JSON.

    Called by write_file via asyncio.to_thread while holding the path
    lock, so disk IO runs in a thread pool and never blocks the event
    loop. This function does not take the lock itself; it assumes the
    caller guarantees mutual exclusion on the same path.

    Args:
        file_path: target file path, workspace-internal absolute path validated by the safety chain.
        content:   full file content (max 1MB).
        encoding:  file encoding.

    Returns:
        JSON string with status, path and a diff summary.
    """
    # existence check: read the original content when present
    existed = os.path.exists(file_path)
    old_content = ""
    # read-failure flag: on failure skip the UNCHANGED decision (an empty
    # old != an empty original)
    read_failed = False

    # read the original when the file exists (only for diff and the UNCHANGED decision)
    if existed:
        # existence check: file_path must not be a directory
        if os.path.isdir(file_path):
            return json.dumps({
                "status": "error",
                "message": f"'{file_path}' is a directory."
            }, ensure_ascii=False)

        # byte-level precheck: read the original only when <= 1MB bytes
        # (for the UNCHANGED comparison and diff.old); larger files skip
        # the read and are overwritten directly, the encoded content is
        # always <= MAX_WRITE_SIZE so byte counts must differ, and a full
        # read of a huge file is saved; read_failed expands to "original
        # content unknown"
        try:
            old_size = os.path.getsize(file_path)
        except OSError:
            # stat failed: original unknown, conservatively overwrite and
            # never claim UNCHANGED
            old_size = None
        if old_size is None or old_size > MAX_WRITE_SIZE:
            read_failed = True
        else:
            # a read failure never blocks the write: diff.old is decorative,
            # overwriting an undecodable/binary file is legal
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    old_content = f.read()
            except Exception:
                read_failed = True

    # file exists and content unchanged: return UNCHANGED (response
    # contract matches the main branch: path + diff)
    if existed and not read_failed and old_content == content:
        return json.dumps({
            "status": "ok",
            "message": f"[UNCHANGED] {file_path} — content identical, no changes made.",
            "path": file_path,
            "diff": {
                "old": old_content[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(old_content) > MAX_DIFF_SIZE else old_content,
                "new": content[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(content) > MAX_DIFF_SIZE else content,
            },
        }, ensure_ascii=False)

    # atomic write: mkstemp in the same directory (keeps os.replace
    # atomic on one filesystem)
    # mkstemp / os.stat / os.umask may raise OSError, must be covered
    tmp_path: str | None = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(file_path))
        # mode: overwrite keeps the original; new files use 0o666 & ~umask
        # (mkstemp fixes 0600, leaving it would make the new file unreadable
        # to other users/processes; umask is read inside the lock, the race
        # window is acceptable)
        if existed:
            orig_mode = os.stat(file_path).st_mode
        else:
            old_umask = os.umask(0)
            os.umask(old_umask)
            orig_mode = 0o666 & ~old_umask
        # write the temp file
        with os.fdopen(tmp_fd, "w", encoding=encoding) as f:
            f.write(content)
        # restore the mode
        os.chmod(tmp_path, orig_mode)
        # atomically replace the original
        os.replace(tmp_path, file_path)
    except UnicodeEncodeError:
        # theoretically unreachable (encoding prechecked), kept as defense
        return json.dumps({
            "status": "error",
            "message": f"Content contains characters not encodable as {encoding}. Try encoding='utf-8'."
        }, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Cannot write to {file_path}: {exc}"
        }, ensure_ascii=False)
    # unexpected exception fallback: a write-phase failure never aborts
    # (finally still cleans the temp file)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Unexpected error writing {file_path}: {exc}"
        }, ensure_ascii=False)
    finally:
        # clean up the temp file (None when mkstemp failed, skip)
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # count lines, decide the action, return the response
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    action = "OVERWRITTEN" if existed else "CREATED"
    return json.dumps({
        "status": "ok",
        "message": f"[{action}] {file_path} ({line_count} lines)",
        "path": file_path,
        "diff": {
            "old": old_content[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(old_content) > MAX_DIFF_SIZE else old_content,
            "new": content[:MAX_DIFF_SIZE] + "\n... [truncated]" if len(content) > MAX_DIFF_SIZE else content,
        },
    }, ensure_ascii=False)


async def write_file(
    file_path: str,
    content: str,
    encoding: str = "utf-8",
) -> str:
    """Atomically create or overwrite a file.

    Parent directories are created on demand.

    Args:
        file_path: target file path (workspace-relative or absolute).
        content:   full file content (max 1MB).
        encoding:  file encoding (default utf-8).

    Returns:
        JSON string with status, path and a diff summary.

    Execution model: argument validation, path safety checks and parent
    directory creation (to_thread) are initiated on the event loop; the
    lock-critical section (existence check, read old content, UNCHANGED
    decision, atomic write) runs in a thread pool via asyncio.to_thread;
    the path lock (asyncio.Lock) is acquired and released on the event
    loop.
    """
    # validate file_path: non-empty string
    # a non-str value (e.g. a number) would blow up with AttributeError at
    # strip(), LLM arguments are untrusted and must be intercepted
    if not isinstance(file_path, str) or not file_path.strip():
        return json.dumps({
            "status": "error",
            "message": "file_path must be a non-empty string."
        }, ensure_ascii=False)

    # validate content: must be a string (empty is legal, writing an empty
    # file; None/0/False/[] would silently write an empty file or blow up)
    if not isinstance(content, str):
        return json.dumps({
            "status": "error",
            "message": "content must be a string."
        }, ensure_ascii=False)

    # validate encoding
    # note: a non-string encoding (None/number) raises TypeError, not
    # LookupError, intercept both
    try:
        "".encode(encoding)
    except (LookupError, TypeError):
        return json.dumps({
            "status": "error",
            "message": f"Unknown encoding: '{encoding}'. Try 'utf-8', 'gbk', or 'latin-1'."
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
    file_path = os.path.expanduser(file_path)

    # ensure an absolute path, resolve relative ones
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

    # normalize the boundary: the workspace root ends with exactly one
    # separator, preventing prefix-match traps
    safe_root = safe_root.rstrip(os.sep) + os.sep

    # boundary check: file_path must stay inside the workspace
    if not file_path.startswith(safe_root):
        return json.dumps({
            "status": "error",
            "message": f"Access to '{file_path}' is denied."
        }, ensure_ascii=False)

    # size check: the content must be under 1MB
    try:
        content_size = len(content.encode(encoding))
    except UnicodeEncodeError:
        return json.dumps({
            "status": "error",
            "message": f"Content contains characters not encodable as {encoding}. Try encoding='utf-8'."
        }, ensure_ascii=False)

    # size check: the content must be under 1MB
    if content_size > MAX_WRITE_SIZE:
        return json.dumps({
            "status": "error",
            "message": f"Content size exceeds {MAX_WRITE_SIZE // 1024 // 1024}MB limit."
        }, ensure_ascii=False)

    # ensure the parent directory exists, create it on demand (after the
    # safety chain: realpath already resolved symlinks, no detour escape)
    # makedirs may raise OSError (a middle path is a file, permission
    # denied), must be covered; whether file_path is a directory is left to
    # the in-lock check (existed branch), no need to repeat here; directory
    # creation is disk IO and runs in a thread pool, keeping the event loop
    # unblocked
    parent = os.path.dirname(file_path)
    if parent:
        try:
            await asyncio.to_thread(os.makedirs, parent, exist_ok=True)
        except OSError as exc:
            return json.dumps({
                "status": "error",
                "message": f"Cannot create directory {parent}: {exc}"
            }, ensure_ascii=False)

    # the file lock ensures atomicity (shared with str_replace on the same
    # path); the whole critical section (existence check, read old content,
    # UNCHANGED decision, atomic write) runs in a thread pool
    async with _get_file_lock(file_path):
        return await asyncio.to_thread(_write_file_io, file_path, content, encoding)


def _collect_delete_targets(
    target: str,
    patterns: list[str] | None,
) -> list[str]:
    """Scan and collect the paths to delete (sync segment).

    A file target or empty patterns returns the target itself; otherwise
    os.walk collects files and directories matching the basename glob
    (fnmatch semantics), matched directories are taken as a whole.

    Args:
        target:   target path validated by the safety chain (workspace-internal absolute path).
        patterns: basename match patterns; None/[] means delete the target itself.

    Returns:
        list of absolute paths to delete, unsorted; the caller sorts
        before deleting.
    """
    to_delete: list[str] = []
    # a file target or no patterns deletes only the target itself
    if os.path.isfile(target) or not patterns:
        to_delete.append(target)
    else:
        # os.walk onerror must raise explicitly: silently skipping an
        # unreadable subdirectory would leave the LLM believing the delete
        # happened, fail explicitly instead
        def _on_error(exc: OSError) -> None:
            raise exc

        # walk the tree, collecting matched files and directories
        for dirpath, dirnames, filenames in os.walk(target, onerror=_on_error):
            for d in [d for d in dirnames if any(fnmatch.fnmatch(d, p) for p in patterns)]:
                to_delete.append(os.path.join(dirpath, d))
                dirnames.remove(d)
            # collect matched files
            for f in filenames:
                if any(fnmatch.fnmatch(f, p) for p in patterns):
                    to_delete.append(os.path.join(dirpath, f))
    return to_delete


def _delete_one(path: str) -> None:
    """Delete a single path (sync segment).

    Directories are first atomically renamed away, then recursively
    deleted (TOCTOU guard against rmtree removing files written during
    the deletion), with leftovers cleaned up on failure; files and
    symlinks are unlinked directly (the link itself).

    Args:
        path: absolute path to delete.

    Returns:
        None; raises OSError on failure, the caller converts it into an
        error response.
    """
    if os.path.isdir(path) and not os.path.islink(path):
        # directory delete: atomically rename it away first, then rmtree,
        # closing the TOCTOU where files written after collection get
        # removed by rmtree; finally cleans up leftovers on failure
        tmp_dir = path + ".clean_tmp_" + uuid.uuid4().hex[:8]
        os.rename(path, tmp_dir)
        try:
            shutil.rmtree(tmp_dir)
        finally:
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        os.unlink(path)


async def clean_dir(
    dir_path: str,
    patterns: list[str] | None = None,
) -> str:
    """Safely delete files or directories inside the workspace (workspace only).

    None or an empty patterns list deletes dir_path recursively as a
    whole; otherwise files and directories are collected by basename
    glob matching (fnmatch semantics), and matched directories are
    deleted as a whole.

    Execution model: argument validation, path safety checks and target
    collection (os.walk) run in a thread pool via asyncio.to_thread; the
    _clean_lock and per-item path locks (asyncio.Lock) are acquired and
    released on the event loop; each single-path delete action
    (rename/rmtree/unlink) also runs via to_thread.

    Args:
        dir_path: target path (workspace-relative or absolute), file or directory.
        patterns: optional basename match patterns; None/[] deletes dir_path as a whole.

    Returns:
        JSON string with status, message, deleted (paths relative to the
        workspace root) and count. On partial failure the error response
        also carries deleted/count reporting progress, deletion is not
        rollback-able and the caller handles the half-deleted state as
        needed.
    """
    # validate dir_path: non-empty string
    # a non-str value (e.g. a number) would blow up with AttributeError at
    # strip(), LLM arguments are untrusted and must be intercepted
    if not isinstance(dir_path, str) or not dir_path.strip():
        return json.dumps({
            "status": "error",
            "message": "dir_path must be a non-empty string."
        }, ensure_ascii=False)

    # validate patterns: list of strings or None; a plain string would be
    # iterated per character and silently match nothing (the LLM believes
    # deletion happened), numbers would blow up, intercept both
    if patterns is not None and (
        not isinstance(patterns, list) or any(not isinstance(p, str) for p in patterns)
    ):
        return json.dumps({
            "status": "error",
            "message": "patterns must be a list of strings or None."
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

    # expand the home directory and keep a lexically normalized path
    # (symlinks unresolved, for the symlink special case)
    dir_path = os.path.expanduser(dir_path)
    raw_path = os.path.normpath(
        os.path.join(safe_root, dir_path) if not os.path.isabs(dir_path) else dir_path
    )

    # symlink special case: must run before realpath, a link pointing
    # outside the workspace would be blocked as an escape after realpath,
    # yet the link itself inside the workspace should be deletable (the
    # link is deleted, never the resolved target)
    if os.path.islink(raw_path):
        # lexical boundary check of the link itself (normpath already
        # folded .., prefix check is safe)
        safe_root_norm = safe_root.rstrip(os.sep)

        if raw_path == safe_root_norm:
            return json.dumps({
                "status": "error",
                "message": "Refusing to delete the workspace root."
            }, ensure_ascii=False)

        if not raw_path.startswith(safe_root_norm + os.sep):
            return json.dumps({
                "status": "error",
                "message": f"Access to '{dir_path}' is denied."
            }, ensure_ascii=False)

        to_delete = [raw_path]
    else:
        # ensure an absolute path, resolve relative ones (recursively
        # resolving symlinks)
        try:
            target = os.path.realpath(raw_path)
        except OSError as exc:
            return json.dumps({
                "status": "error",
                "message": f"Invalid path: {exc}"
            }, ensure_ascii=False)

        # normalize the boundary: the workspace root ends with exactly one
    # separator, preventing prefix-match traps
        safe_root = safe_root.rstrip(os.sep) + os.sep

        # refuse to delete the workspace root
        if target == safe_root.rstrip(os.sep):
            return json.dumps({
                "status": "error",
                "message": "Refusing to delete the workspace root."
            }, ensure_ascii=False)

        # boundary check: dir_path must stay inside the workspace
        if not target.startswith(safe_root):
            return json.dumps({
                "status": "error",
                "message": f"Access to '{dir_path}' is denied."
            }, ensure_ascii=False)
        # the target must exist
        if not os.path.exists(target):
            return json.dumps({
                "status": "error",
                "message": f"'{target}' does not exist."
            }, ensure_ascii=False)

        # collect the delete list (directory scanning is disk IO, runs in
        # a thread pool)
        try:
            to_delete: list[str] = await asyncio.to_thread(
                _collect_delete_targets, target, patterns
            )
        except OSError as exc:
            return json.dumps({
                "status": "error",
                "message": f"Cannot scan '{target}': {exc}"
            }, ensure_ascii=False)

    # nothing matched, return early
    if not to_delete:
        return json.dumps({
            "status": "ok",
            "message": f"Nothing matched in '{dir_path}'.",
            "deleted": [],
            "count": 0,
        }, ensure_ascii=False)

    # cap check after collection, before any deletion (safety-first order)
    if len(to_delete) > CLEAN_MAX_ITEMS:
        return json.dumps({
            "status": "error",
            "message": (
                f"Would delete {len(to_delete)} items, exceeding the "
                f"{CLEAN_MAX_ITEMS} per-call limit. Narrow the patterns "
                f"or target subdirectories."
            )
        }, ensure_ascii=False)

    to_delete.sort()
    deleted: list[str] = []

    # deletion phase: _clean_lock keeps concurrent clean_dir calls from
    # stepping on each other; the per-item _get_file_lock excludes
    # str_replace / write_file, so a file being written or replaced is
    # never deleted and then resurrected; locks are acquired/released on
    # the event loop, each single-path delete (rename/rmtree/unlink) runs
    # in a thread pool
    async with _clean_lock:
        for path in to_delete:
            async with _get_file_lock(path):
                try:
                    await asyncio.to_thread(_delete_one, path)
                except OSError as exc:
                    return json.dumps({
                        "status": "error",
                        "message": f"Cannot delete {path}: {exc}",
                        "deleted": [os.path.relpath(p, safe_root) for p in deleted],
                        "count": len(deleted),
                    }, ensure_ascii=False)
                deleted.append(path)

    # deletion done, return the result
    return json.dumps({
        "status": "ok",
        "message": f"[DELETED] {len(deleted)} item(s)",
        "deleted": [os.path.relpath(p, safe_root) for p in deleted],
        "count": len(deleted),
    }, ensure_ascii=False)
