"""Prepare node factory -- initialize a clean context for each sub-agent run

Provides:
- make_prepare_node:            factory returning the prepare node for sub-agent workflow
"""

import time

from langchain_core.messages import SystemMessage, HumanMessage

from core.agents.constants import PREPARE_IDENTITY_FIELDS
from core.agents.utils import inject_workspace_dir, validate_identity
from utils.logging import get_logger

logger = get_logger(__name__)


def make_prepare_node(system_prompt: str):
    """Create a prepare node that initializes sub-agent context

    Args:
        system_prompt:      the sub-agent's system prompt template.

    Returns:
        Callable[[dict], dict] -- async LangGraph node function
    """
    async def prepare_node(state: dict) -> dict:
        # validate identity fail-closed before anything else
        identity = validate_identity(state, PREPARE_IDENTITY_FIELDS)
        task_description = identity["task_description"]
        sub_agent_id = identity["sub_agent_id"]
        sub_agent_name = identity["sub_agent_name"]
        task_id = identity["task_id"]
        task_name = identity["task_name"]

        t_start = time.time()

        # log the sub-agent start with full identity context
        logger.info(
            "sub_agent_start",
            sub_agent_id=sub_agent_id,
            sub_agent_name=sub_agent_name,
            task_id=task_id,
            task_name=task_name,
        )

        # inject the workspace directory into the system prompt;
        # project_dir travels through the fanout task when provided
        try:
            system_content = inject_workspace_dir(
                system_prompt,
                str(state.get("project_dir", "") or "").strip(),
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to inject workspace: {e.__class__.__name__}: {e}"
            ) from e

        return {
            "sub_agent_messages": [
                SystemMessage(content=system_content),
                HumanMessage(content=task_description),
            ],
            "sub_agent_start_at": str(t_start),
            "sub_agent_iteration": 0,
            "file_changes": [],
        }

    return prepare_node
