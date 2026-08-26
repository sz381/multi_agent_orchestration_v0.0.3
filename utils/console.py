"""Terminal rendering helpers

logging and other terminal rendering for better visualizing and debugging purposes

Functions Provides:
- render_plan_block:            Render a plan block
- render_fanout_block:          Render a fanout block   
"""

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
