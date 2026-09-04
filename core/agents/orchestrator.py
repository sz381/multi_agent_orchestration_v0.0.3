"""Orchestrator node factory -- the central LLM decision maker in the graph

Provides:
- make_orchestrator_node:           factory returning the orchestrator node
- make_interrupt_node:              factory returning the interrupt node for HITL
"""

from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from core.prompts.system_prompt_orchestrator import ORCHESTRATOR_SYSTEM_PROMPT
from core.tools.bundles.orchestrator import ORCHESTRATOR_BASE_TOOLS, ORCHESTRATOR_HARD_STOP_TOOLS
from core.agents.constants import (
    ORCHESTRATOR_MAX_ITERATIONS,
    ORCHESTRATOR_ITERATION_BUDGET,
)
from core.agents.state import OrchestrationState
from core.agents.model import init_model, ainvoke_with_content_guard
from core.middleware.constants import AGENT_ROLE_ORCHESTRATOR
from core.middleware.identity_injection import bind_identity
from core.agents.utils import (
    build_state_snapshot,
    check_iteration_limit,
    inject_workspace_dir,
)
from utils.settings import settings
from utils.logging import get_logger

logger = get_logger(__name__)


def make_orchestrator_node(*, retry_prompt: str | None = None):
    """Create the orchestrator LLM decision node

    Args:
        retry_prompt: A one-shot tail instruction used only by the bounded
            no-tool-call retry node.  It is sent to the model but is not
            written into the orchestration message history.

    Returns:
        an async LangGraph node of type
        Callable[[OrchestrationState, RunnableConfig], dict]
    """
    async def orchestrator_node(state: OrchestrationState, config: RunnableConfig) -> dict:
        # log the start of the orchestrator node call
        logger.debug(
            "orchestrator_called",
            agent_name="orchestrator",
            agent_id="orchestrator",
            iteration=state["orchestration_iteration"],
            sub_agent_cnt_active=state.get("active_sub_agent_count", "N/A"),
        )

        # bind the orchestrator identity so every LLM/tool event can be 
        # attributed by the orchestration callback
        config = bind_identity(
            config,
            agent_name="orchestrator",
            agent_id="orchestrator",
            agent_role=AGENT_ROLE_ORCHESTRATOR,
        )

        # inject the workspace directory into the system prompt
        try:
            system_content = inject_workspace_dir(ORCHESTRATOR_SYSTEM_PROMPT)
        except Exception as e:
            raise RuntimeError(
                f"Failed to inject workspace: {e.__class__.__name__}: {e}"
            ) from e

        # build the state snapshot: plan and budget leave the system prompt
        # and move to the tail of the messages, keeping the system prompt
        # byte-stable across rounds for the prefix cache
        try:
            snapshot_content = build_state_snapshot(
                state["plan"],
                state["orchestration_iteration"],
                AGENT_ROLE_ORCHESTRATOR,
                budget=ORCHESTRATOR_ITERATION_BUDGET,
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to build state snapshot: {e.__class__.__name__}: {e}"
            ) from e

        # System message first, then history, then the tail state snapshot;
        # HumanMessage so DeepSeek persists the cache unit at the user-input
        # boundary of every request.  The retry instruction is deliberately
        # request-local: persisting it would turn a one-turn correction into
        # stale conversation context.
        messages = (
            [SystemMessage(content=system_content)]
            + list(state["messages"])
            + [HumanMessage(content=snapshot_content)]
        )
        if retry_prompt:
            messages.append(HumanMessage(content=retry_prompt))

        # TODO: deferred for now
        # request pre-context pipeline: process the injected context before
        # calling the model, context engineering part

        # initialize the model and bind tools as needed
        model = init_model(
            model_name=settings.deepseek_model_name,
            temperature=0.3,
            max_tokens=16384,
            streaming=True,
        )
        hit_limit = check_iteration_limit(
            state["orchestration_iteration"],
            max_iterations=ORCHESTRATOR_MAX_ITERATIONS,
        )
        if hit_limit:
            logger.warning(
                "orchestrator_iteration_limit_reached",
                iteration_cnt=state["orchestration_iteration"] + 1,
            )
            # iteration limit reached: bind only end_orchestration, edit_plan, delete_plan
            # end_orchestration fails if a plan still exists, so the orchestrator
            # must edit or delete the plan before ending the orchestration
            model = model.bind_tools(ORCHESTRATOR_HARD_STOP_TOOLS)
        else:
            model = model.bind_tools(ORCHESTRATOR_BASE_TOOLS)

        # call the LLM
        try:
            response = await ainvoke_with_content_guard(
                model, messages, config=config, role="orchestrator"
            )
            return {
                "messages": [
                    HumanMessage(content=snapshot_content),
                    response,
                ],
                "orchestration_iteration": state["orchestration_iteration"] + 1,
            }
        except Exception as e:
            logger.error("orchestrator_invocation_failed", error=str(e))
            return {
                "messages": [AIMessage(content="An internal error occurred. Please try again.")],
                "error_message": str(e),
            }

    return orchestrator_node


def make_interrupt_node():
    """Create the interrupt node for human-in-the-loop

    Returns:
        an async LangGraph node of type
        Callable[[OrchestrationState, RunnableConfig], dict]
    """

    async def interrupt_node(state: OrchestrationState, config: RunnableConfig) -> dict:
        pass

    return interrupt_node
