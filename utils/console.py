"""Terminal rendering helpers

logging and other terminal rendering for better visualizing and debugging purposes

Functions Provides:
- render_plan_block:            Render a plan block
- render_fanout_block:          Render a fanout block
- render_sub_agent_done:        Render a sub-agent completion block   
"""

from core.agents.constants import MAX_FILES_SHOWN
from core.agents.state import Plan, SubAgentRoundTaskItem


def render_plan_block(plan: list[Plan]) -> str:
    """Render a plan snapshot as a terminal status block.

    Args:
        plan: List of phase dicts (phase_id / phase_name / phase_description / phase_status).

    Returns:
        Multi-line block with one status icon per phase.
    """
    lines = ["\n" + "=" * 86, f"  📋 PLAN ({len(plan)} phases)", "=" * 86]
    for p in plan:
        icons = {"pending": "○", "in_progress": "◐", "done": "●"}
        lines.append(f"  {icons[p['phase_status']]} [{p['phase_id']}] {p['phase_name']}")
        if p['phase_description']:
            lines.append(f"      {p['phase_description']}")
    lines.append("=" * 86)
    return "\n".join(lines)


def render_fanout_block(tasks: list[SubAgentRoundTaskItem]) -> str:
    """Render a sub-agent fanout dispatch as a terminal status block.

    Args:
        tasks: List of task dicts (task_id / task_name / task_description / subagent_id / subagent_name / task_completion_status).

    Returns:
        Multi-line block with one status icon per dispatched task.
    """
    lines = ["\n" + "=" * 86, f"  🤖 FANOUT — {len(tasks)} task(s) dispatched", "=" * 86]
    for t in tasks:
        icon = "●" if t['task_completion_status'] else "○"
        lines.append(f"  {icon} [{t['task_id']}] {t['task_name']}")
        lines.append(f"      agent: {t['subagent_name']} ({t['subagent_id']})")
        if t['task_description']:
            lines.append(f"      {t['task_description']}")
    lines.append("=" * 86)
    return "\n".join(lines)


def render_sub_agent_done(
    sub_agent_type: str,
    sub_agent_name: str,
    sub_agent_id: str,
    task_id: str,
    task_name: str,
    elapsed: float,
    iteration: int,
    total_tokens: int,
    prompt_tokens: int,
    completion_tokens: int,
    artifacts: list[str],
) -> str:
    """Render a bordered completion block for a finished sub-agent.

    Args:
        sub_agent_type:     sub-agent type name, e.g. "programmer".
        sub_agent_name:     display name of the sub-agent instance.
        sub_agent_id:       unique sub-agent invocation ID.
        task_id:            parent task ID.
        task_name:          parent task name.
        elapsed:            total elapsed seconds.
        iteration:          ReAct loop iterations consumed.
        total_tokens:       total token usage.
        prompt_tokens:      prompt tokens consumed.
        completion_tokens:  completion tokens generated.
        artifacts:          file paths produced.

    Returns:
        the multi-line block ready to print to the terminal.
    """
    ratio = (
        f"{prompt_tokens / completion_tokens:.1f}:1"
        if completion_tokens > 0 else "N/A"
    )

    lines = [
        "=" * 86,
        f"  ✅ [{sub_agent_type}] SUBAGENT DONE  {task_id}  ({sub_agent_name})",
        "=" * 86,
        f"  agent:    {sub_agent_id} | {sub_agent_name} | {task_name}",
        f"  elapsed:  {elapsed:.1f}s    iters={iteration}",
        f"  tokens:   total={total_tokens}  prompt={prompt_tokens}  "
        f"completion={completion_tokens}  ratio={ratio}",
        f"  files:    {len(artifacts)}",
    ]
    for i, path in enumerate(artifacts[:MAX_FILES_SHOWN], 1):
        lines.append(f"            {i}. {path},")
    if len(artifacts) > MAX_FILES_SHOWN:
        lines.append(
            f"            ... {len(artifacts)} files total, "
            f"showing first {MAX_FILES_SHOWN}"
        )
    lines.append("=" * 86)
    return "\n".join(lines)
