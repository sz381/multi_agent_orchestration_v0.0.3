"""Summarize node factory -- extract final response, artifacts, and metadata

Provides:
- make_summarize:               factory returning the sub-agent summarize node
"""

import time

from langchain_core.messages import AIMessage

from core.agents.constants import SUMMARIZE_IDENTITY_FIELDS
from core.agents.utils import count_tokens, extract_artifacts, validate_identity
from utils.console import render_sub_agent_done
from utils.settings import settings
from utils.logging import get_logger

logger = get_logger(__name__)


def make_summarize(name: str):
    """Create a summarize node that extracts sub-agent results

    Args:
        name:   sub-agent type for logging and console rendering,
                e.g. "programmer".

    Returns:
        Callable[[dict], dict] -- async LangGraph node function
    """
    async def summarize_node(state: dict) -> dict:
        # validate identity fail-closed before touching the history
        identity = validate_identity(state, SUMMARIZE_IDENTITY_FIELDS)
        task_id = identity["task_id"]
        messages = identity["sub_agent_messages"]
        sub_agent_id = identity["sub_agent_id"]
        sub_agent_name = identity["sub_agent_name"]
        task_name = identity["task_name"]

        # the last AIMessage with content is the sub-agent's final response;
        # a missing one raises and fails the run (fail-closed) -- an empty
        # result would cause the orchestrator to hallucinate
        final_text = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                final_text = msg.content
                break
        if not final_text:
            raise ValueError(
                f"No AIMessage with content found in sub-agent message history "
                f"({len(messages)} messages total). The sub-agent produced no "
                f"usable response, which would cause the orchestrator to hallucinate."
            )

        # real-time file_changes written by the tools node come first;
        # fall back to scanning the message history for tool calls
        artifacts = state.get("file_changes") or []
        if not artifacts:
            artifacts = extract_artifacts(messages)

        # time elapsed since the prepare node stamped the start
        start_at = float(state.get("sub_agent_start_at", 0))
        elapsed = time.time() - start_at if start_at else 0

        # token usage aggregated from AIMessage usage_metadata
        token_counts = count_tokens(messages)
        total_prompt_tokens = token_counts["prompt_tokens"]
        total_completion_tokens = token_counts["completion_tokens"]
        total_tokens = token_counts["total_tokens"]

        # log completion with full metadata
        logger.info(
            "sub_agent_done",
            sub_agent_type=name,
            sub_agent_name=sub_agent_name,
            sub_agent_id=sub_agent_id,
            task_id=task_id,
            task_name=task_name,
            elapsed=round(elapsed, 1),
            artifacts_count=len(artifacts),
            total_tokens=total_tokens,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            status="success",
        )

        # print the bordered completion block when the console is on
        if settings.console_print:
            print(render_sub_agent_done(
                name, sub_agent_name, sub_agent_id, task_id, task_name,
                elapsed, state.get("sub_agent_iteration", 0),
                total_tokens, total_prompt_tokens, total_completion_tokens,
                artifacts,
            ))

        return {
            "sub_agent_outputs": {
                task_id: {
                    "task_id": task_id,
                    "task_name": task_name,
                    "sub_agent": name,
                    "sub_agent_id": sub_agent_id,
                    "sub_agent_name": sub_agent_name,
                    "result_summary": final_text,
                    "artifacts": artifacts,
                    "token_used": total_tokens,
                    "status": "success",
                    "elapsed_seconds": round(elapsed, 1),
                }
            },
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "sub_agent_time_elapsed": round(elapsed, 1),
            "sub_agent_error_message": "",
        }

    return summarize_node
