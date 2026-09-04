"""LLM node factory -- model invocation with plan/budget tail snapshot

Provides:
- make_llm:                     factory returning the sub-agent LLM node
"""

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from core.agents.constants import (
    LLM_IDENTITY_FIELDS,
    SUB_AGENT_MAX_ITERATIONS,
    SUB_AGENT_ITERATION_BUDGET,
)
from core.middleware.constants import SUB_AGENT_ROLES
from core.middleware.identity_injection import bind_identity
from core.agents.utils import (
    build_state_snapshot,
    check_iteration_limit,
    validate_identity,
)
from core.agents.model import init_model, ainvoke_with_content_guard
from utils.settings import settings
from utils.logging import get_logger

logger = get_logger(__name__)

def make_llm(tools: list | None = None):
    """Create a sub-agent LLM node function

    Args:
        tools: @tool-decorated functions. None/[] → direct LLM call.

    Returns:
        Callable[[dict, RunnableConfig], dict] — async LangGraph node function
    """
    async def llm_node(state: dict, config: RunnableConfig) -> dict:
        # log the call with identity + iteration for traceability
        logger.info(
            "sub_agent_node_called",
            sub_agent_name=state.get("sub_agent_name", "N/A"),
            sub_agent_id=state.get("sub_agent_id", "N/A"),
            task_id=state.get("task_id", "N/A"),
            task_name=state.get("task_name", "N/A"),
            iteration=state.get("sub_agent_iteration", 0),
        )

        # validate identity fail-closed before touching the model
        identity = validate_identity(state, LLM_IDENTITY_FIELDS)
        sub_agent_name = identity["sub_agent_name"]

        # role derives from the sub_agent_id prefix, the same source as the
        # Send dispatch in _build_sub_agent_send; sub_agent_name is a display
        # label chosen by the orchestrator and must not drive role mapping
        role = identity["sub_agent_id"].split("_", 1)[0]
        if role not in SUB_AGENT_ROLES:
            raise RuntimeError(
                f"Unknown sub-agent role from sub_agent_id "
                f"{identity['sub_agent_id']!r}; expected one of "
                f"{sorted(SUB_AGENT_ROLES)}"
            )

        # bind the identity so every LLM/tool event can be attributed
        # by the orchestration callback (M6 contract)
        config = bind_identity(
            config,
            agent_name=sub_agent_name,
            agent_id=identity["sub_agent_id"],
            agent_role=role,
            task_id=identity["task_id"],
            task_name=identity["task_name"],
        )

        # build the tail state snapshot: plan and budget leave the system
        # prompt and move to the tail of the messages, keeping the system
        # message byte-stable across rounds for the prefix cache
        try:
            snapshot_content = build_state_snapshot(
                state.get("sub_agent_plan"),
                state["sub_agent_iteration"],
                role,
                budget=SUB_AGENT_ITERATION_BUDGET,
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to build state snapshot: {e.__class__.__name__}: {e}"
            ) from e

        # history first (never mutated), then the tail snapshot as a
        # HumanMessage so DeepSeek persists the cache unit at the
        # user-input boundary of every request
        messages = list(state["sub_agent_messages"]) + [
            HumanMessage(content=snapshot_content)
        ]

        # TODO: deferred for now
        # request pre-context pipeline: process the injected context before
        # calling the model, context engineering part

        # initialize the model; bind tools only when not past the hard
        # iteration limit -- tool-less soft landing makes the model wind
        # down and finish instead of starting new work
        model = init_model(
            model_name=settings.deepseek_model_name,
            temperature=0.3,
            max_tokens=16384,
            streaming=True,
        )
        hit_limit = check_iteration_limit(
            state["sub_agent_iteration"],
            max_iterations=SUB_AGENT_MAX_ITERATIONS,
        )
        if hit_limit:
            logger.warning(
                "sub_agent_iteration_limit",
                sub_agent_id=identity["sub_agent_id"],
                iteration=state["sub_agent_iteration"] + 1,
            )
        if tools and not hit_limit:
            model = model.bind_tools(tools)

        # call the LLM
        try:
            response = await ainvoke_with_content_guard(
                model, messages, config=config, role="sub_agent"
            )
            return {
                "sub_agent_messages": [
                    HumanMessage(content=snapshot_content),
                    response,
                ],
                "sub_agent_iteration": state["sub_agent_iteration"] + 1,
            }
        except Exception as e:
            logger.error("sub_agent_llm_invocation_failed", error=str(e))
            return {
                "sub_agent_messages": [
                    AIMessage(content="An internal error occurred. Please try again.")
                ],
                "sub_agent_error_message": str(e),
            }

    return llm_node
