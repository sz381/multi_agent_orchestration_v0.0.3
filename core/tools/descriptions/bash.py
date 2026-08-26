"""Tool descriptions for the shell command toolset (_bash).

Tools described:
- bash                     execute a shell command
- kill_specific_process    kill a specific process
"""

TOOL_DESCRIPTION = {
    "bash": (
        "Execute a shell command inside a macOS Seatbelt sandbox.\n"
        "Parameters:\n"
        "- cmd: the command to run (e.g. 'pytest tests/ -v')\n"
        "- cwd: dir relative to workspace (default '.')\n"
        "- timeout: max seconds (default 30)\n"
        "- allow_network: enable outbound network (default True)\n"
        "\n"
        "Calls are isolated: cd does NOT persist — pass cwd each time "
        "(e.g. cmd='npm install', cwd='frontend').\n"
        "Sandbox: writes limited to workspace+/tmp; rm -rf /, sudo, curl|sh blocked.\n"
        "macOS: no `timeout` cmd (use gtimeout/perl alarm); "
        "no apt-get/yum/snap — use brew/pip/npm.\n"
        "Python: always use project venv ('.venv/bin/python'/pip/pytest), never system python.\n"
        "For: tests, install deps, compile, git, lint, build.\n"
        "NOT for: long-running servers (dev server, uvicorn).\n"
        "Returns: exit_code, stdout, stderr, elapsed, sandbox_violations."
    ),
    "kill_specific_process": (
        "Kill the process listening on a TCP port (macOS only).\n"
        "Parameters:\n"
        "- port: the port to kill (int, 1-65535)\n"
        "\n"
        "The bash sandbox can only signal itself — this is the ONLY way to stop "
        "long-running dev servers (npm run dev, uvicorn, vite).\n"
        "Allowed ports (dev ranges): 3000-3100, 5000-5200, 8000-8100; "
        "system/agent processes are never killed.\n"
        "Graceful stop: SIGTERM first, auto-upgrade to SIGKILL after 3s.\n"
        "Returns: status, port, killed [{pid, name, signal_used, graceful}]."
    ),
}
