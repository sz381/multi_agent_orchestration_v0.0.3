"""Announce node -- streams the final user-facing message after end_orchestration

Provides:
- make_announce_node:   factory returning the announce node
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from core.prompts.system_prompt_announce import (
    ANNOUNCE_HANDOFF_TEMPLATE,
    ANNOUNCE_SYSTEM_PROMPT,
)
from core.agents.state import OrchestrationState
from core.agents.model import init_model, ainvoke_with_content_guard
from core.middleware.constants import AGENT_ROLE_ORCHESTRATOR
from core.middleware.identity_injection import bind_identity
from utils.settings import settings
from utils.logging import get_logger

logger = get_logger(__name__)


def make_announce_node():
    """Create the announce node streaming the final user-facing message

    The node is a bare LLM call: no tools are bound, so it can neither call
    tools nor loop back into the graph -- a single shot with a static edge
    to END. This is the structural guard against ghost continuation
    (issue 8_02_005_v002).

    Returns:
        an async LangGraph node of type
        Callable[[OrchestrationState, RunnableConfig], dict]
    """
    async def announce_node(state: OrchestrationState, config: RunnableConfig) -> dict:
        logger.debug("announce_called")

        # announce speaks as the orchestrator persona, so the streamed
        # tokens are attributed to the orchestrator in the callback
        config = bind_identity(
            config,
            agent_name="orchestrator",
            agent_id="orchestrator",
            agent_role=AGENT_ROLE_ORCHESTRATOR,
        )

        # the handoff note leaves the system prompt and moves to the tail
        # of the messages, keeping the system prompt byte-stable; routed
        # here only when response is set, the fallback keeps the node total
        handoff_content = ANNOUNCE_HANDOFF_TEMPLATE.format(
            response=state.get("response") or ""
        )

        # system message first, then the full history, then the tail handoff
        messages = (
            [SystemMessage(content=ANNOUNCE_SYSTEM_PROMPT)]
            + list(state["messages"])
            + [HumanMessage(content=handoff_content)]
        )

        # bare model: streaming only, deliberately no tool binding
        model = init_model(
            model_name=settings.deepseek_model_name,
            temperature=0.3,
            max_tokens=16384,
            streaming=True,
        )

        try:
            response = await ainvoke_with_content_guard(
                model, messages, config=config, role="announce"
            )
            return {"messages": [response]}
        except Exception as e:
            logger.error("announce_invocation_failed", error=str(e))
            return {
                "messages": [AIMessage(
                    content="The orchestration finished, but the final message "
                            "could not be generated."
                )],
                "error_message": str(e),
            }

    return announce_node
