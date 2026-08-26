"""Tool definitions owned by the researcher sub-agent.

Lightweight wrappers binding kernel implementations to the @tool decorator.

Tools provided:
    ├── view_file                        read file content by line numbers
    ├── glob_tool                        find files by glob pattern matching
    ├── grep_tool                        search file content with regex
    ├── str_replace                      replace exact text in a file
    ├── write_file                       create or overwrite a file's text
    ├── bash                             run shell commands in the sandbox
    ├── web_search                       search the web
    ├── web_fetch                        fetch a web page
    ├── make_plan                        create a new execution plan from phases
    ├── edit_plan                        modify one or more plan phases
    └── delete_plan                      remove a phase or clear the whole plan
"""

import json

from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.prebuilt import ToolRuntime

from core.tools.descriptions.fs_mutate import TOOL_DESCRIPTION as FS_MUTATE_DESCRIPTION
from core.tools.descriptions.fs_readonly import TOOL_DESCRIPTION as FS_READONLY_DESCRIPTION
from core.tools.descriptions.plan import TOOL_DESCRIPTION as PLAN_DESCRIPTION
from core.tools.descriptions.web import TOOL_DESCRIPTION as WEB_DESCRIPTION
from core.tools.descriptions.bash import TOOL_DESCRIPTION as BASH_DESCRIPTION
from core.tools._kernel._fs_mutate import (
    str_replace as _str_replace,
    write_file as _write_file,
)
from core.tools._kernel._fs_readonly import (
    view_file as _view_file,
    glob_tool as _glob_tool,
    grep_tool as _grep_tool,
)
from core.tools._kernel._plan import (
    make_plan as _make_plan,
    edit_plan as _edit_plan,
    delete_plan as _delete_plan,
)
from core.tools._kernel._web import (
    web_search as _web_search,
    web_fetch as _web_fetch,
)
from core.tools._kernel._bash import (
    bash as _bash,
)


@tool("view_file", description=FS_READONLY_DESCRIPTION["view_file"])
async def view_file(
    file_path: str,
    offset: int = 1,
    limit: int = 100,
    encoding: str = "utf-8",
    allow_external_reads: bool = False,
) -> str:
    return await _view_file(
        file_path,
        offset,
        limit,
        encoding,
        allow_external_reads,
    )


@tool("glob_tool", description=FS_READONLY_DESCRIPTION["glob_tool"])
async def glob_tool(
    pattern: str, 
    dir_path: str = ".",
    allow_external_reads: bool = False
) -> str:
    return await _glob_tool(
        pattern, 
        dir_path, 
        allow_external_reads
    )


@tool("grep_tool", description=FS_READONLY_DESCRIPTION["grep_tool"])
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
    return await _grep_tool(
        pattern, path,
        glob_pattern,
        output_mode,
        context_lines,
        head_limit,
        offset,
        case_sensitive,
        multiline,
        encoding,
        allow_external_reads
    )


@tool("str_replace", description=FS_MUTATE_DESCRIPTION["str_replace"])
async def str_replace(
    file_path: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
    encoding: str = "utf-8",
) -> str:
    return await _str_replace(
        file_path,
        old_str,
        new_str,
        replace_all,
        encoding,
    )


@tool("write_file", description=FS_MUTATE_DESCRIPTION["write_file"])
async def write_file(
    file_path: str,
    content: str,
    encoding: str = "utf-8",
) -> str:
    return await _write_file(
        file_path,
        content,
        encoding,
    )


@tool("bash", description=BASH_DESCRIPTION["bash"])
async def bash(
    cmd: str,
    cwd: str = ".",
    timeout: int = 30,
    allow_network: bool = True,
) -> str:
    return await _bash(
        cmd,
        cwd,
        timeout,
        allow_network,
    )


@tool("web_search", description=WEB_DESCRIPTION["web_search"])
async def web_search(
    query: str,
    max_results: int = 5,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> str:
    return await _web_search(
        query,
        max_results,
        allowed_domains,
        blocked_domains,
    )


@tool("web_fetch", description=WEB_DESCRIPTION["web_fetch"])
async def web_fetch(
    url: str,
    prompt: str,
) -> str:
    return await _web_fetch(
        url,
        prompt,
    )


@tool("make_plan", description=PLAN_DESCRIPTION["make_plan"])
def make_plan(phases: list[dict], runtime: ToolRuntime) -> Command | str:
    result = _make_plan(phases, existing_plan=runtime.state.get("plan") or [])
    
    r = json.loads(result)
    
    if r["status"] == "error":
        return r["message"]
    
    return Command(update={
        "plan": r["plan"],
        "messages": [ToolMessage(content=result, tool_call_id=runtime.tool_call_id)],
    })


@tool("edit_plan", description=PLAN_DESCRIPTION["edit_plan"])
def edit_plan(updates: list[dict], runtime: ToolRuntime) -> Command | str:
    result = _edit_plan(updates, runtime.state["plan"] or [])
    
    r = json.loads(result)
    
    if r["status"] == "error":
        return r["message"]
    
    return Command(update={
        "plan": r["plan"],
        "messages": [ToolMessage(content=result, tool_call_id=runtime.tool_call_id)],
    })


@tool("delete_plan", description=PLAN_DESCRIPTION["delete_plan"])
def delete_plan(
    runtime: ToolRuntime,
    phase_id: str = "",
    delete_all: bool = False,
) -> Command | str:
    result = _delete_plan(phase_id, runtime.state["plan"] or [], delete_all)
    
    r = json.loads(result)
    
    if r["status"] == "error":
        return r["message"]
    
    return Command(update={
        "plan": r["plan"],
        "messages": [ToolMessage(content=result, tool_call_id=runtime.tool_call_id)],
    })


RESEARCHER_TOOLS = [
    view_file,
    glob_tool,
    grep_tool,
    str_replace,
    write_file,
    bash,
    web_search,
    web_fetch,
    make_plan,
    edit_plan,
    delete_plan,
]
