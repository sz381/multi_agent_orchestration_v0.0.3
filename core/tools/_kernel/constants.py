"""Tool constants.

Constants provided:
- MAX_READ_SIZE:                        max read size per view_file call                          default 1MB
- VIEW_FILE_MAX_SKIP_BYTES:             soft byte limit when skipping in view_file                default 50MB
- BINARY_SNIFF_BYTES:                   binary sniff head sample bytes                            default 8KB
- EXCLUDE_DIRS:                         directories excluded from file tools
- EXCLUDE_FILES:                        files excluded from file tools
- GLOB_MAX_RESULTS:                     max glob_tool results                                     default 200
- GLOB_MAX_SCAN:                        max glob_tool entries scanned                             default 5000
- GREP_MAX_FILES:                       max files searched by grep_tool                           default 5000
- GREP_MAX_FILE_SIZE:                   per-file size cap for grep_tool                           default 10MB
- REGEX_MATCH_TIMEOUT_SECONDS:          regex timeout, blocks backtracking blowup                 default 2s
- GREP_TOTAL_TIMEOUT_SECONDS:           total wall-clock budget for one grep search               default 30s
- MAX_WRITE_SIZE:                       max write size                                            default 1MB
- MAX_DIFF_SIZE:                        max diff size                                             default 500
- CLEAN_MAX_ITEMS:                      max items cleaned per call                                default 500
- PLAN_MAX_PHASES:                      max plan phases                                           default 12
- PHASE_VALID_STATUSES:                 valid phase status set
- PHASE_REQUIRED_FIELDS:                required phase field set
- PHASE_ALLOWED_UPDATE_FIELDS:          phase fields allowed to update
- MAX_RESPONSE_LENGTH:                  max response length                                       default 100K
- MAX_TASKS:                            max fanout tasks, subagent concurrency cap                default 20
- REQUIRED_TASK_FIELDS:                 required task field set
- ALLOWED_OPTIONAL_FIELDS:              optional fields, inject a working dir into subagent prompts
- AVAILABLE_SUBAGENT_PREFIXES:          available subagent prefix set
- BLACKLIST_PATTERNS:                   bash command blacklist regexes, Seatbelt sandbox is the first line
- BASH_MAX_OUTPUT_CHARS:                max chars returned to the model per bash stream           default 806
- KILL_ALLOWED_PORTS:                   whitelisted port ranges for kill, inclusive              default (3000,3100)/(5000,5200)/(8000,8100)
- KILL_GRACE_SECONDS:                   grace wait after SIGTERM                                 default 3
- KILL_CONFIRM_SECONDS:                 confirm wait after SIGKILL                                default 2
- KILL_POLL_INTERVAL:                   exit probe poll interval, seconds                         default 0.2
- KILL_SYSTEM_PROCESS_NAMES:            system process names refused by kill_specific_process
- SANDBOX_MAX_OUTPUT_CHARS:             in-memory output cap per sandbox stream                   default 5000
- SANDBOX_ENV_STRIP:                    agent-related env vars stripped from child processes
- SANDBOX_SENSITIVE_ENV_KEYWORDS:       sensitive env var keywords, blocked from child processes
- MAX_QUERY_LENGTH:                     max query length                                          default 500
- MAX_SEARCH_RESULTS:                   max search results                                        default 20
- MAX_URL_LENGTH:                       max URL length                                            default 2048
- MAX_PROMPT_LENGTH:                    max prompt length                                         default 5000
- SUMMARIZE_LENGTH_THRESHOLD:           summary length threshold                                  default 10K
- MAX_CONTENT_CHARS:                    max content chars                                         default 100K
- PAGE_TIMEOUT_MS:                      page timeout                                              default 20s
- SSRF_BLOCKED_HOSTS:                   hosts blocked against SSRF
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
MAX_DIFF_SIZE = 500
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
    r"\brm\b.*--no-preserve-root",
    r"\$[A-Za-z_][A-Za-z0-9_]*\s+-rf\s*/",
    r"\bsudo\b",
    r"\bchmod\s+777",
    r"\bmkfs\.",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r"\bcurl.*\|\s*(\$\(.*\)|(ba)?sh)",
    r"\bwget.*\|\s*(\$\(.*\)|(ba)?sh)",
    r"\bbase64\b.*\|\s*(ba)?sh",
    r"\bpython.*-c.*base64.*\|.*sh",
    r"\$\(\s*(curl|wget)\b",
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

# _web
MAX_QUERY_LENGTH = 500 
MAX_SEARCH_RESULTS = 20
MAX_URL_LENGTH = 2048
MAX_PROMPT_LENGTH = 5000
SUMMARIZE_LENGTH_THRESHOLD = 10_000
MAX_CONTENT_CHARS = 100_000
PAGE_TIMEOUT_MS = 20_000
SSRF_BLOCKED_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"})
