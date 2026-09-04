"""
temporary test file, will be deleted later
"""

import json
import asyncio
import logging
from venv import logger

from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage

from core.agents.graph import build_graph
from core.tools._kernel._web import close_crawler
from core.middleware.orchestration_callback import OrchestrationCallBack
from utils.logging import setup_logging, get_logger
from utils.console import render_plan_block, render_fanout_block

setup_logging(dev_mode=True, log_level=logging.DEBUG)

logger = get_logger(__name__)

# TEST_QUERY = """
# 请测试计划类工具，按顺序尽情调用（删除后要保留至少一个阶段）：
# 1. make_plan：创建一份 3 个阶段的执行计划，阶段内容自拟
# 2. edit_plan：修改其中一个阶段的 phase_name 或 phase_status
# 3. delete_plan：删除其中一个阶段
# 每个工具调用后，用一句话说明结果。
# """


# TEST_QUERY = """
# 测试任务，严格按以下步骤执行：

# 1. 创建计划，并用 bash 创建目录 run_test_v003_n001 在当前目录中

# 2. 并发3个 programmer subagent，分别写三篇文章，都保存到 run_test_v003_n001：
#    - 我的妈妈.md — 写一篇关于妈妈的文章（800字以上，有真情实感）
#    - 我的爸爸.md — 写一篇关于爸爸的文章（800字以上，有真情实感）
#    - 我的姥爷.md — 写一篇关于姥爷的文章（800字以上，有真情实感）

# 3. 等第2步全部完成后，并发5个 subagent：
#    - 3个 reviewer 分别审查 我的妈妈.md、我的爸爸.md、我的姥爷.md
#    - 2个 programmer 分别写 我的小猫.md、我的女朋友.md（都保存到同一目录，各800字以上）

# 4. 等第3步全部完成后，你自己审查 我的小猫.md 和 我的女朋友.md 的内容质量

# 5. 调用 end_orchestration 结束
# """


TEST_QUERY = """
请帮我开发一个「待办事项（todo）管理」的小型前后端项目，所有产出放在 run_test_v003_n002 目录，按下面的流程推进：

1. 先创建执行计划，然后你自己用命令创建好 run_test_v003_n002 目录。

2. 写一份「超级完整的项目规格说明书」（这一步你自己完成，不要派子代理）：定义清楚项目的一切——后端（Python 标准库 http.server，监听 8765 端口，提供待办的增/查/完成/删 REST API，数据持久化到本地 JSON 文件）、前端（纯静态 HTML/CSS/JS 页面，实现列表展示、新增、标记完成、删除）、前后端如何联动（页面调用哪些接口、请求与响应格式、每个字段的含义）、数据模型、目录结构与每个文件的职责、验收标准（后端必须自带可运行的自动化测试）。越细节越好，写成能直接照着开工的完整设计文档；内容很长的话可以拆成多个 markdown 文件（如总览 + 后端设计 + 前端设计 + API 契约），用一份总览把它们串起来，保证结构清晰。

3. 说明书完成后，并发派 2 个程序员，前后端各一人（文件互不重叠）：
   - 后端程序员：先读说明书，严格按其中的设计与 API 契约实现后端；写完把服务跑起来，用 curl 把增/查/完成/删全部实测一遍，并跑通自带测试，测完确认 8765 端口没有残留进程；
   - 前端程序员：先读说明书，严格按其中的设计与 API 契约实现页面；先做不依赖后端的自检（页面结构与 JS 逻辑自查），真实联调交给后面的验收环节。
   实现只用 Python 标准库与原生前端三件套，禁止任何第三方依赖。

4. 前后端都完成后，并发派 2 个审查员（各写一份独立审查报告）：
   - 审查员 A：验收后端——启动服务，用 curl 把全部接口走一遍，跑后端自带测试，核对数据文件的读写与异常处理，报告写明验收步骤、结果与问题清单；
   - 审查员 B：走查前端与整体——核对页面功能是否与说明书一致、JS 是否严格按 API 契约调用、有无 XSS/输入校验等安全与健壮性问题，必要时结合后端代码确认联动正确性。
   问题按严重程度分级，每条给出具体修改建议与文件位置。

5. 迭代修复：收到两份审查报告后，把必须修复的问题整理出来，派对应方向的程序员修复（后端问题→后端程序员，前端问题→前端程序员，修复前先读审查报告），修完再派审查员按上次的问题清单复核；如此循环直到没有必须修复的问题，最多迭代 2 个来回，每轮开工前记得更新计划状态。最终仍有遗留的小问题就在交付总结里说明。

6. 收尾：清点 run_test_v003_n002 里的全部产出（说明书、前后端代码、两份审查报告等）；清理运行产生的 __pycache__ 等临时文件（源码与文档保留）；确认 8765 端口已无进程占用；把计划阶段全部标为完成，做最终交付总结。
"""


def _safe_initial_state(**overrides) -> dict:
    defaults = {
        "conversation_id": "demo_001",
        "orchestration_id": "demo_001",
        "messages": [],
        "user_query": "",
        "plan": None,
        "active_sub_agent_count": 0,
        "sub_agent_round_tasks": [],
        "sub_agent_outputs": {},
        "orchestration_status": "running",
        "orchestration_iteration": 0,
        "should_orchestration_pause": False,
        "should_orchestration_stop": False,
        "response": "",
        "total_tokens": 0,
        "start_at": "",
        "time_elapsed": 0.0,
        "error_message": "",
    }
    defaults.update(overrides)
    if defaults["user_query"] and not defaults["messages"]:
        defaults["messages"] = [HumanMessage(content=defaults["user_query"])]
    return defaults


def _tool_summary(msg: ToolMessage) -> str | None:
    content = msg.content
    if not isinstance(content, str) or not content.strip():
        return None

    payload = None
    if content.lstrip().startswith("{"):
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            payload = None

    if isinstance(payload, dict):
        if msg.name in ("make_plan", "edit_plan", "delete_plan") and payload.get("plan"):
            return render_plan_block(payload["plan"])
        if msg.name == "fanout_subagents" and payload.get("tasks"):
            return render_fanout_block(payload["tasks"])
        if payload.get("message"):
            return f"  ⚙ {msg.name or 'tool'} → {payload['message'][:120]}"

    first_line = content.strip().splitlines()[0]
    return f"  ⚙ {msg.name or 'tool'} → {first_line[:120]}"


def _handle_updates(data: dict, header_ref: list):
    for node_name, output in data.items():
        if node_name == "tools":
            header_ref[0] = False
            items = output if isinstance(output, list) else [output]
            for item in items:
                if not isinstance(item, dict):
                    continue
                for msg in item.get("messages", []):
                    if isinstance(msg, ToolMessage):
                        summary = _tool_summary(msg)
                        if summary:
                            print(summary, flush=True)
            continue
        if node_name == "__error__":
            print(f"\n[ERROR] {output}", flush=True)
        elif node_name == "interrupt":
            print("\n[INTERRUPT] PAUSED — waiting for human input", flush=True)
        elif isinstance(output, dict) and output.get("error_message"):
            print(f"\n[NODE ERROR] {node_name}: {output['error_message']}", flush=True)


async def main():
    callback_handler = OrchestrationCallBack()
    graph = build_graph(callback_handler)
    state = _safe_initial_state(
        user_query=TEST_QUERY,
        conversation_id="demo_001",
        orchestration_id="demo_001",
    )

    print(f"[USER] {state['user_query']}\n")

    header = [False]
    ended_properly = [False]

    async for mode, data in graph.astream(
        state,
        config={
            "configurable": {"thread_id": state["conversation_id"]},
            "callbacks": [callback_handler],
        },
        stream_mode=["updates", "messages"],
    ):
        if mode == "updates":
            _handle_updates(data, header)
            continue

        chunk, _metadata = data
        if not isinstance(chunk, AIMessageChunk):
            continue
        if chunk.tool_call_chunks:
            for tc in chunk.tool_call_chunks:
                if tc.get("name") == "end_orchestration":
                    ended_properly[0] = True
            continue
        content = chunk.content
        if isinstance(content, str) and content:
            if not header[0]:
                print("\n[ORCHESTRATOR] ", end="", flush=True)
                header[0] = True
            print(content, end="", flush=True)
        elif not content and header[0]:
            print(flush=True)
            header[0] = False

    await close_crawler()
    if not ended_properly[0]:
        print("\n\n⚠️  Orchestrator did not call end_orchestration. Graph ended via fallback.")
    print("\n[DONE]")


if __name__ == "__main__":
    asyncio.run(main())
