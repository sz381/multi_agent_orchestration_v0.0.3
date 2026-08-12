"""只读工具集合（_fs_readonly）的工具描述

工具表述包括:
- glob_tool                     按模式匹配查找文件
- view_file                     按行号读取文件内容
- grep_tool                     正则搜索文件内容
"""

TOOL_DESCRIPTION = {
    "glob_tool": (
        "Find files by glob pattern (e.g. '**/*.py'). Returns absolute paths.\n"
        "Params:\n"
        "- pattern: glob pattern. ** = recursive (crosses /), * = one level (no /, matches dots)\n"
        "- dir_path: directory to search (default '.')\n"
        "- allow_external_reads: read outside workspace (default False)\n"
        "EXCLUDED by default (not searched): dependency (venv, .venv, node_modules), "
        "version control (.git, .svn), IDE (.vscode, .idea), caches "
        "(__pycache__, .cache, .gradle, .m2), build (dist, build, target, coverage), "
        "logs/tmp (log, logs, tmp), noise (.DS_Store).\n"
        "To scan inside an excluded dir, set dir_path to it directly.\n"
        "Limits: max 200 results, 5000 scanned. Check 'truncated' in response.\n"
        "No {a,b} braces or !() extglob — use multiple calls or regex via grep."
    ),
    "view_file": (
        "Read a file with line numbers. ALWAYS read before editing.\n"
        "Params:\n"
        "- file_path: path to the file\n"
        "- offset: start line, 1-based — first line is 1, NOT 0 (default 1)\n"
        "- limit: max lines to return, range 1-1000 (default 100)\n"
        "- encoding: file encoding (default 'utf-8', try 'gbk'/'latin-1')\n"
        "- allow_external_reads: read outside workspace (default False)\n"
        "EFFICIENCY (save turns): files under ~1000 lines → one call with limit=1000 "
        "(no pagination); multiple files → parallel view_file calls in ONE turn; "
        "never re-read files already in context.\n"
        "Limits: max 1MB read. If 'truncated', continue with offset=end_line+1. "
        "If 'has_more' is true, you have NOT seen the whole file."
    ),
    "grep_tool": (
        "Search file contents with regex. NAVIGATION tool — FIND where code lives, "
        "then use view_file to read. Do NOT edit based on grep output alone.\n"
        "Params:\n"
        "- pattern: regex pattern\n"
        "- path: file or dir to search (default '.')\n"
        "- glob_pattern: filter WHICH FILES by name, e.g. '*.py' (not the regex)\n"
        "- output_mode: files_with_matches|content|count (default files_with_matches)\n"
        "- context_lines: N lines before AND after each match, symmetric (default 2, range 0-10)\n"
        "- head_limit: max results (default 200, range 0-1000, 0=unlimited)\n"
        "- offset: skip first N match results, NOT line numbers (default 0)\n"
        "- case_sensitive: match case (default True)\n"
        "- multiline: . matches newlines, patterns can span lines; slower on large files (default False)\n"
        "- encoding: file encoding (default 'utf-8', try 'gbk'/'latin-1')\n"
        "- allow_external_reads: search outside workspace (default False)\n"
        "Strategy: start with files_with_matches to locate files, then content on a "
        "specific path to see matched lines. Limits: files >10MB skipped, max 5000 "
        "scanned. Response has 'files_truncated', 'skipped_large_files', 'timed_out_files'. "
        "If 'truncated' is true, increase offset for more."
    ),
}
