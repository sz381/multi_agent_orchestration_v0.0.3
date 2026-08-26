"""Shared utility functions.

Provides:
- _merge_round_tasks: merge fan-out tasks by task ID
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.agents.state import SubAgentRoundTaskItem


def _merge_round_tasks(
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
