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

TEST_QUERY = """
测试控制工具互斥：请在同一个回复中同时调用 make_plan 和 edit_plan
（必须同一轮、一次输出两个工具调用，不要分开调用）。
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
