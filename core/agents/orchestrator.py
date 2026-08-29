"""Orchestrator node factory -- the central LLM decision maker in the graph

Provides:
- make_orchestrator_node:           factory returning the orchestrator node
- make_interrupt_node:              factory returning the interrupt node for HITL
"""

from langchain_core.messages import SystemMessage, AIMessage
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
from utils.settings import settings
from utils.logging import get_logger

logger = get_logger(__name__)


def _inject_workspace_dir(system_content: str) -> str:
    """Inject the current workspace directory into the system prompt

    Args:
        system_content:     the original system prompt template.

    Returns:
        the system prompt with <CURRENT_WORKSPACE> replaced by the actual path.
    """
    return system_content.replace(
        "<CURRENT_WORKSPACE>",
        f"<CURRENT_WORKSPACE>\n"
            f"Your workspace root is: {settings.workspace_dir}\n"
        f"</CURRENT_WORKSPACE>",
    )


def _inject_plan(system_content: str, plan: list[dict]) -> str:
    """Inject the current plan status into the system prompt

    Args:
        system_content: the system prompt after workspace injection.
        plan:           the plan list of phase dicts, each with
                        phase_id, phase_name, phase_status.

    Returns:
        the system prompt with the plan injected into <CURRENT_PLAN>;
        a note saying no plan is set when the plan is empty.
    """
    if not plan:
        return system_content.replace(
            "<CURRENT_PLAN>",
            "<CURRENT_PLAN>\n"
                "You haven't set any plan yet\n"
            "</CURRENT_PLAN>",
        )

    lines = []
    for p in plan:
        icon = {"pending": "○", "in_progress": "◐", "done": "●"}[p["phase_status"]]
        lines.append(
            f"  {icon} [{p['phase_id']}] {p['phase_name']}"
        )
    lines.append("")
    lines.append(
        "Before ending, verify ALL phases are ●. "
        "If any are ○ or ◐, you MUST act on them first."
    )
    plan_content = "\n".join(lines)

    return system_content.replace(
        "<CURRENT_PLAN>",
        f"<CURRENT_PLAN>\n"
            f"{plan_content}\n"
        f"</CURRENT_PLAN>",
    )


def _inject_iteration_budget(system_content: str, iteration: int) -> str:
    """Inject the remaining iteration budget into the system prompt

    Args:
        system_content: the system prompt after plan injection.
        iteration:      iterations consumed, zero-based.

    Returns:
        the system prompt with live budget info so the model stays aware
        of the remaining budget and enters closeout mode when exhausted.
    """
    remaining = max(0, ORCHESTRATOR_ITERATION_BUDGET - iteration)

    if remaining <= 0:
        return system_content.replace(
            "<ITERATION_BUDGET>",
            f"<ITERATION_BUDGET>\n"
                f"You are PAST your ~{ORCHESTRATOR_ITERATION_BUDGET}-iteration work budget. "
                f"You are now in CLOSEOUT MODE. "
                f"Do NOT start or continue task work. "
                f"Only reconcile the plan with edit_plan/delete_plan if necessary, "
                f"then call end_orchestration as soon as possible.\n"
            f"</ITERATION_BUDGET>",
        )

    return system_content.replace(
        "<ITERATION_BUDGET>",
        f"<ITERATION_BUDGET>\n"
            f"Iterations consumed: {iteration} / ~{ORCHESTRATOR_ITERATION_BUDGET}. "
            f"Remaining: ~{remaining}. Verify with tests, then close out.\n"
        f"</ITERATION_BUDGET>",
    )


def _check_iteration_limit(state: OrchestrationState) -> bool:
    """Check whether the orchestrator has reached the max iteration count

    Args:
        state: the orchestrator state.

    Returns:
        True if the iteration limit is reached.
    """
    iteration_cnt = state["orchestration_iteration"] + 1
    hit_limit = iteration_cnt >= ORCHESTRATOR_MAX_ITERATIONS

    if hit_limit:
        logger.warning(
            "orchestrator_iteration_limit_reached",
            iteration_cnt=iteration_cnt,
        )

    return hit_limit


def make_orchestrator_node():
    """Create the orchestrator LLM decision node

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
            system_content = _inject_workspace_dir(ORCHESTRATOR_SYSTEM_PROMPT)
        except Exception as e:
            raise RuntimeError(
                f"Failed to inject workspace: {e.__class__.__name__}: {e}"
            ) from e

        # inject the plan into the system prompt
        try:
            system_content = _inject_plan(system_content, state["plan"])
        except Exception as e:
            raise RuntimeError(
                f"Failed to inject plan: {e.__class__.__name__}: {e}"
            ) from e

        # inject the iteration budget into the system prompt
        try:
            system_content = _inject_iteration_budget(
                system_content, state["orchestration_iteration"]
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to inject iteration budget: {e.__class__.__name__}: {e}"
            ) from e

        # prepend the system message to the existing messages
        messages = [SystemMessage(content=system_content)] + list(state["messages"])

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
        if not _check_iteration_limit(state):
            model = model.bind_tools(ORCHESTRATOR_BASE_TOOLS)
        else:
            # iteration limit reached: bind only end_orchestration, edit_plan, delete_plan
            # end_orchestration fails if a plan still exists, so the orchestrator
            # must edit or delete the plan before ending the orchestration
            model = model.bind_tools(ORCHESTRATOR_HARD_STOP_TOOLS)

        # call the LLM
        try:
            response = await ainvoke_with_content_guard(
                model, messages, config=config, role="orchestrator"
            )
            return {
                "messages": [response],
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
