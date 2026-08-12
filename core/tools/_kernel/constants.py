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
- PLAN_MAX_PHASES:                      最大计划阶段数   默认 12
- PHASE_VALID_STATUSES:                 阶段有效状态集合
- PHASE_REQUIRED_FIELDS:                阶段必需字段集合
- PHASE_ALLOWED_UPDATE_FIELDS:          阶段允许更新字段集合
- MAX_RESPONSE_LENGTH:                  最大响应长度   默认 100K
- MAX_TASKS:                            最大任务数     默认 20, subagent 并发数量限制
- REQUIRED_TASK_FIELDS:                 任务必需字段集合
- ALLOWED_OPTIONAL_FIELDS:              任务允许的可选字段集合, 这个是给 subagent 的 system prompt 注入指定 working directory 用的
- AVAILABLE_SUBAGENT_PREFIXES:          可用的 subagent 前缀集合
- BLACKLIST_PATTERNS:                   bash 命令黑名单正则集合（纵深防御，Seatbelt 沙箱为第一道防线）
- BASH_MAX_OUTPUT_CHARS:                bash 单路（stdout/stderr）返回给模型的最大字符数   默认 806
- KILL_ALLOWED_PORTS:                   kill_specific_process 端口段白名单（含两端）   默认 (3000,3100)/(5000,5200)/(8000,8100)
- KILL_GRACE_SECONDS:                   SIGTERM 后等待优雅退出的秒数   默认 3
- KILL_CONFIRM_SECONDS:                 SIGKILL 后确认退出的秒数   默认 2
- KILL_POLL_INTERVAL:                   退出探测轮询间隔（秒）   默认 0.2
- KILL_SYSTEM_PROCESS_NAMES:            kill_specific_process 拒绝的系统进程名集合
- SANDBOX_MAX_OUTPUT_CHARS:             沙箱单路（stdout/stderr）输出内存保护上限   默认 5000
- SANDBOX_ENV_STRIP:                    子进程环境中剔除的代理相关变量集合（防误用代理 Python 环境）
- SANDBOX_SENSITIVE_ENV_KEYWORDS:       环境变量名含这些关键字即视为敏感，不传入子进程
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

# _plan
PLAN_MAX_PHASES = 12
PHASE_VALID_STATUSES = frozenset({"pending", "in_progress", "done"})
PHASE_REQUIRED_FIELDS = frozenset({"phase_id", "phase_name", "phase_status", "phase_description"})
PHASE_ALLOWED_UPDATE_FIELDS = frozenset({"phase_name", "phase_status", "phase_description"})

# _orch_control
MAX_RESPONSE_LENGTH = 100_000
MAX_TASKS = 20
REQUIRED_TASK_FIELDS = {
    "task_id", "task_name", "task_description",
    "task_completion_status", "subagent_id", "subagent_name",
}
ALLOWED_OPTIONAL_FIELDS = {"project_dir"}
AVAILABLE_SUBAGENT_PREFIXES = ["programmer", "reviewer", "researcher"]

# _bash
BLACKLIST_PATTERNS = [
    r"\brm\s+-rf\s+/",
    r"\brm\b.*--no-preserve-root",  # GNU rm 取消 / 保护：--no-preserve-root / 直删根
    r"\$[A-Za-z_][A-Za-z0-9_]*\s+-rf\s*/",  # 变量拆词：CMD=rm; $CMD -rf[/] 绕过
    r"\bsudo\b",
    r"\bchmod\s+777",
    r"\bmkfs\.",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r"\bcurl.*\|\s*(\$\(.*\)|(ba)?sh)",
    r"\bwget.*\|\s*(\$\(.*\)|(ba)?sh)",
    r"\bbase64\b.*\|\s*(ba)?sh",
    r"\bpython.*-c.*base64.*\|.*sh",
    r"\$\(\s*(curl|wget)\b",  # 命令替换直接执行网络工具：$(curl evil)
    r"\bshutdown\b",
    r"\breboot\b",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",
]
BASH_MAX_OUTPUT_CHARS = 806
KILL_ALLOWED_PORTS = ((3000, 3100), (5000, 5200), (8000, 8100))
KILL_GRACE_SECONDS = 3
KILL_CONFIRM_SECONDS = 2
KILL_POLL_INTERVAL = 0.2
KILL_SYSTEM_PROCESS_NAMES = frozenset({
    "kernel_task", "launchd", "WindowServer", "loginwindow",
    "syslogd", "notifyd", "cfprefsd", "configd", "syspolicyd",
    "amfid", "opendirectoryd", "mds", "mdworker", "backupd",
})

# sandbox
SANDBOX_MAX_OUTPUT_CHARS = 5000
SANDBOX_ENV_STRIP = frozenset({
    "VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "PYTHONHOME", "PYTHONPATH",
    "GOPATH", "NODE_PATH", "PERL5LIB", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
})
SANDBOX_SENSITIVE_ENV_KEYWORDS = [
    "API_KEY", "API_SECRET", "TOKEN", "SECRET", "PASSWORD",
    "CREDENTIAL", "PRIVATE_KEY",
]
