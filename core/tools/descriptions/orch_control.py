"""编排控制工具集合（_orch_control）的工具描述

工具表述包括:
- end_orchestration                 结束当前编排
- pause_orchestration               暂停当前编排
- fanout_subagents                  派遣子代理
"""

TOOL_DESCRIPTION = {
    "end_orchestration": (
        "Deliver the final response to the user. MUST be the last tool you call. "
        "Do NOT call any other tool after end_orchestration.\n"
        "Parameters:\n"
        "- response: the final answer (non-empty string, max 100K chars)\n"
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
