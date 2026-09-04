"""Tool descriptions for the orchestration control toolset (_orch_control).

Tools described:
- end_orchestration      end the current orchestration
- pause_orchestration    pause the current orchestration
- fanout_subagents       dispatch subagents
"""

TOOL_DESCRIPTION = {
    "end_orchestration": (
        "Close the orchestration. MUST be the last tool you call. "
        "Do NOT call any other tool after end_orchestration.\n"
        "Parameters:\n"
        "- response: handoff note for the final announcer (non-empty string, "
        "max 100K chars): a micro-summary of what was done plus presentation "
        "guidance (tone, depth, emphasis) for the user-facing message\n"
        "\n"
        "Rejected if the current plan still has phases not marked 'done' — "
        "complete or delete them first."
    ),
    "pause_orchestration": (
        "Pause the current orchestration. MUST be the only tool called this round.\n"
        "Parameters:\n"
        "- should_orch_pause: set to true to allow pausing (bool; false → rejected)\n"
    ),
    "fanout_subagents": (
        "Delegate independent tasks to specialist agents in parallel. "
        "Good for: multiple files, research topics, mixed work types.\n"
        "Do NOT use when task B depends on task A's output — run sequentially.\n"
        "Call ONCE per round with ALL tasks (max 20) — a second call in the "
        "same round is REJECTED (5 tasks → ONE call).\n"
        "Exclusive with make_plan/edit_plan/delete_plan — one control tool per round max.\n"
        "Parameters:\n"
        "- tasks: dict list; ALL required fields:\n"
        "    task_id (unique string),\n"
        "    task_name (the task, e.g. 'Implement auth module'),\n"
        "    task_description (detailed instructions),\n"
        "    task_completion_status: false,\n"
        "    subagent_id: unique per fanout; 'programmer_1' style "
        "(prefix must be programmer|researcher|reviewer),\n"
        "    subagent_name (the agent's ROLE, e.g. 'Auth Developer', NOT task_name)\n"
    ),
}
