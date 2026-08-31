"""Shared helpers for the orchestrator and worker nodes

Provides:
- render_plan_block:            render the plan list into a <CURRENT_PLAN> block
- render_budget_block:          render the iteration budget into a <ITERATION_BUDGET> block
- build_state_snapshot:         assemble the per-round tail <STATE SNAPSHOT>
- check_iteration_limit:        pure predicate for the hard iteration limit
- validate_identity:            fail-closed identity field collection
- extract_artifacts:            collect file paths from file-producing tool calls
- count_tokens:                 aggregate token usage from usage_metadata
- merge_round_tasks:            merge fan-out round tasks by task ID
- inject_workspace_dir:         inject workspace/project dir into the system prompt
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage

from core.agents.constants import FILE_PRODUCING_TOOLS, PLAN_VISIBLE_ROLES
from core.middleware.constants import AGENT_ROLE_ORCHESTRATOR
from utils.settings import settings

if TYPE_CHECKING:
    from core.agents.state import SubAgentRoundTaskItem


def render_plan_block(plan: list[dict]) -> str:
    """Render the current plan status into a standalone text block

    Args:
        plan:   the plan list of phase dicts, each with
                phase_id, phase_name, phase_status.

    Returns:
        the plan block with the <CURRENT_PLAN> layout; a note saying
        no plan is set when the plan is empty.
    """
    if not plan:
        return (
            "<CURRENT_PLAN>\n"
            "You haven't set any plan yet\n"
            "</CURRENT_PLAN>"
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

    return (
        "<CURRENT_PLAN>\n"
        f"{plan_content}\n"
        "</CURRENT_PLAN>"
    )


def render_budget_block(iteration: int, *, budget: int, agent_role: str) -> str:
    """Render the remaining iteration budget into a standalone text block

    Args:
        iteration:   iterations consumed, zero-based.
        budget:      the iteration budget ceiling of the caller.
        agent_role:  role of the caller; selects the tail sentences.

    Returns:
        the budget block with the <ITERATION_BUDGET> layout; the closeout
        notice when the budget is exhausted.
    """
    remaining = max(0, budget - iteration)

    # per-role tail sentences: the orchestrator closes out via
    # end_orchestration, sub-agents wind down and summarize
    if agent_role == AGENT_ROLE_ORCHESTRATOR:
        closeout_tail = (
            "You are now in CLOSEOUT MODE. Do NOT start or continue task work. "
            "Only reconcile the plan with edit_plan/delete_plan if necessary, "
            "then call end_orchestration as soon as possible."
        )
        normal_tail = "Verify with tests, then close out."
    else:
        closeout_tail = (
            "Do NOT start new work — summarize results and finish immediately."
        )
        normal_tail = "Budget your turns — finish within budget."

    if remaining <= 0:
        return (
            "<ITERATION_BUDGET>\n"
            f"You are PAST your ~{budget}-iteration work budget. "
            f"{closeout_tail}\n"
            "</ITERATION_BUDGET>"
        )

    return (
        "<ITERATION_BUDGET>\n"
        f"Iterations consumed: {iteration} / ~{budget}. "
        f"Remaining: ~{remaining}. {normal_tail}\n"
        "</ITERATION_BUDGET>"
    )


def build_state_snapshot(
    plan: list[dict] | None,
    iteration: int,
    agent_role: str,
    *,
    budget: int,
) -> str:
    """Build the per-round state snapshot appended at the tail of each request

    Args:
        plan:        the plan list of phase dicts, or None.
        iteration:   iterations consumed, zero-based.
        agent_role:  role of the caller; roles in PLAN_VISIBLE_ROLES
                     always carry the plan block, others skip it.
        budget:      iteration budget of the caller; keyword-only so
                     call sites stay explicit about their ceiling.

    Returns:
        the snapshot text appended to the end of every request and
        persisted with the response, so each request is a strict prefix
        of the next one.
    """
    blocks = []
    if agent_role in PLAN_VISIBLE_ROLES:
        blocks.append(render_plan_block(plan or []))
    blocks.append(render_budget_block(iteration, budget=budget, agent_role=agent_role))
    return "<STATE SNAPSHOT>\n" + "\n".join(blocks) + "\n</STATE SNAPSHOT>"


def check_iteration_limit(iteration: int, *, max_iterations: int) -> bool:
    """Return True when the next round would reach the hard iteration limit

    Args:
        iteration:        iterations already consumed (the state value,
                          zero-based); the next round is iteration + 1.
        max_iterations:   the hard iteration ceiling.

    Returns:
        True if the next round would hit the limit.
    """
    return iteration + 1 >= max_iterations


def validate_identity(state: dict, fields: tuple) -> dict:
    """Collect identity fields from the state with defensive checks

    Args:
        state:   the incoming state dict.
        fields:  the identity field names to collect; callers pass
                 one of the *_IDENTITY_FIELDS tuples from constants.

    Returns:
        a dict holding exactly the requested fields.

    Raises:
        RuntimeError: when one or more fields are missing or empty.
    """
    missing = [
        field
        for field in fields
        if not str(state.get(field, "") or "").strip()
    ]
    if missing:
        raise RuntimeError(
            f"Sub-agent state missing identity fields: {missing}; "
            f"available keys: {sorted(state.keys())}"
        )
    return {field: state[field] for field in fields}


def extract_artifacts(messages: list) -> list[str]:
    """Collect file paths written or modified by file-producing tools

    Args:
        messages:   the message history to scan.

    Returns:
        deduplicated file paths extracted from the tool-call arguments
        of FILE_PRODUCING_TOOLS, in first-seen order.
    """
    seen = set()
    artifacts = []

    for msg in messages:
        if not isinstance(msg, AIMessage) or not msg.tool_calls:
            continue

        for tc in msg.tool_calls:
            param_name = FILE_PRODUCING_TOOLS.get(tc["name"])
            if not param_name:
                continue

            path = tc.get("args", {}).get(param_name, "")
            if path and path not in seen:
                seen.add(path)
                artifacts.append(path)

    return artifacts


def count_tokens(messages: list) -> dict:
    """Aggregate token usage across the message history

    Args:
        messages:   the message history to scan.

    Returns:
        a dict with prompt_tokens / completion_tokens / total_tokens,
        aggregated from AIMessage.usage_metadata; messages without
        usage_metadata contribute zero.
    """
    prompt_tokens = 0
    completion_tokens = 0
    for msg in messages:
        if not isinstance(msg, AIMessage) or not msg.usage_metadata:
            continue
        usage = msg.usage_metadata
        prompt_tokens += usage.get("input_tokens", 0) or 0
        completion_tokens += usage.get("output_tokens", 0) or 0
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def merge_round_tasks(
    left: list[SubAgentRoundTaskItem] | None,
    right: list[SubAgentRoundTaskItem] | None,
) -> list[SubAgentRoundTaskItem]:
    """Merge fan-out tasks by task ID.

    Must support two write semantics:
    - dispatch, right is non-empty: merge by task ID with the current list so that all
            parallel fan-out sub-agent calls in a round survive;
    - reset, right is empty: clear the round tasks once all branches complete;
            the empty write must actually clear the list, otherwise stale tasks linger and get rescheduled indefinitely.
    """
    if right is None:
        return list(left or [])
    if not right:
        return []
    if not left:
        return list(right)
    merged: dict[str, SubAgentRoundTaskItem] = {t["task_id"]: t for t in left}
    for t in right:
        merged[t["task_id"]] = t
    return list(merged.values())


def inject_workspace_dir(system_content: str, project_dir: str = "") -> str:
    """Inject the workspace directory into the system prompt

    Args:
        system_content:     the original system prompt template.
        project_dir:        optional project directory; when set, file
                            operations are scoped to it. Leave empty for
                            the orchestrator.

    Returns:
        the system prompt with <CURRENT_WORKSPACE> replaced by the
        actual path block.
    """
    workspace_info = f"Your workspace root is: {settings.workspace_dir}"
    if project_dir:
        workspace_info += (
            f"\nYour project directory is: {project_dir}\n"
            "All file operations should be scoped to this directory."
        )
    return system_content.replace(
        "<CURRENT_WORKSPACE>",
        f"<CURRENT_WORKSPACE>\n{workspace_info}\n</CURRENT_WORKSPACE>",
    )
