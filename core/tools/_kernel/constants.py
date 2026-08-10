""" 工具常量

提供常量：
- MAX_READ_SIZE:                        最大读取大小   默认 1MB
- VIEW_FILE_MAX_SKIP_BYTES:             view_file 跳过目标行时的软限制字节数   默认 50MB
- BINARY_SNIFF_BYTES:                   view_file 二进制嗅探的头部采样字节数   默认 8KB
- EXCLUDE_DIRS:                         排除的目录
- EXCLUDE_FILES:                        排除的文件
- GLOB_MAX_RESULTS:                     glob_tool 最大结果数   默认 200
- GLOB_MAX_SCAN:                        glob_tool 最大扫描数   默认 5000
- GREP_MAX_FILES:                       grep_tool 最大搜索文件数   默认 5000
- GREP_MAX_FILE_SIZE:                   grep_tool 单文件大小上限   默认 10MB
- REGEX_MATCH_TIMEOUT_SECONDS:          正则单次匹配操作超时（防灾难性回溯）   默认 2s
- GREP_TOTAL_TIMEOUT_SECONDS:           grep_tool 整次搜索总时长预算（wall-clock）   默认 30s
- MAX_WRITE_SIZE:                       最大写入大小   默认 1MB
- MAX_DIFF_SIZE:                        最大差异大小   默认 50
- CLEAN_MAX_ITEMS:                      最大清理项目数   默认 500
"""

# _fs_readonly
MAX_READ_SIZE = 1 * 1024 * 1024
VIEW_FILE_MAX_SKIP_BYTES = 50 * 1024 * 1024
BINARY_SNIFF_BYTES = 8 * 1024
EXCLUDE_DIRS = frozenset({
    ".git", ".svn", ".hg", ".bzr",
    "venv", ".venv",
    "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".hypothesis", ".pyre", ".eggs", ".pdm-build",
    "node_modules", "bower_components", "jspm_packages", ".npm", ".yarn",
    ".pnpm-store", ".turbo", ".next", ".nuxt", ".svelte-kit", ".vite",
    ".parcel-cache", ".webpack",
    ".vscode", ".idea", ".intellij", ".cursor", ".eclipse", ".fleet", ".zed",
    ".qoder", ".cache", ".langchain", ".langsmith", ".chroma", ".streamlit",
    ".gradle", ".m2", ".cargo", ".rustup", ".terraform", ".serverless",
    ".amplify", ".trash", ".Trash",
    "dist", "build", "out", "target", "coverage", "htmlcov",
    "log", "logs", ".log", "tmp", "temp",
})
EXCLUDE_FILES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
GLOB_MAX_RESULTS = 200
GLOB_MAX_SCAN = 5000
GREP_MAX_FILES = 5000
GREP_MAX_FILE_SIZE = 10 * 1024 * 1024
REGEX_MATCH_TIMEOUT_SECONDS = 2.0
GREP_TOTAL_TIMEOUT_SECONDS = 30.0

# _fs_mutate
MAX_WRITE_SIZE = 1 * 1024 * 1024
MAX_DIFF_SIZE = 50
CLEAN_MAX_ITEMS = 500
