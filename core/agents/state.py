"""LangGraph state definitions for the orchestrator graph.

Provides:
- Plan                          Single phase in the orchestrator execution plan.
- SubAgentRoundTaskItem         One task assigned to a sub-agent in a fan-out round.
- OrchestrationState            Top-level state of the orchestrator graph.
"""

import operator
from typing import TypedDict, Annotated, NotRequired

from langgraph.graph.message import add_messages

from core.agents.utils import merge_round_tasks


class Plan(TypedDict):
    """A single phase in the orchestrator execution plan.

    Attributes:
        phase_id:                       the unique identifier of the phase.
        phase_name:                     a short human-readable label.
        phase_status:                   one of "pending", "in_progress", or "done".
        phase_description:              what the phase should accomplish.
    """
    phase_id: str
    phase_name: str
    phase_status: str
    phase_description: str


class SubAgentRoundTaskItem(TypedDict):
    """A task dispatched to a sub-agent during a fan-out round.

    Attributes:
        task_id:                        the unique identifier of the task.
        task_name:                      a short human-readable label.
        task_description:               what the sub-agent should do.
        task_completion_status:         whether the task is completed.
        subagent_id:                    the unique identifier of the sub-agent, e.g. `programmer_id_xxx`
        subagent_name:                  the name of the sub-agent, a short human-readable label.
    """
    task_id: str
    task_name: str
    task_description: str
    task_completion_status: bool
    subagent_id: str
    subagent_name: str


class OrchestrationState(TypedDict):
    """Top-level state passed through the orchestrator graph.

    Attributes:
        conversation_id:                identifier of the conversation thread.
        orchestration_id:               identifier of the current orchestration run.
        messages:                       full message history of the current orchestration.
        user_query:                     the original user request.
        plan:                           execution plan phases; fully replaced on update.
        active_sub_agent_count:         number of sub-agents currently running in this round.
        sub_agent_round_tasks:          tasks dispatched in the current round.
        sub_agent_outputs:              merged outputs from completed sub-agents.
        orchestration_status:           current status string.
        orchestration_iteration:        current iteration count.
        should_orchestration_pause:     flag to pause and wait for human input, HITL.
        should_orchestration_stop:      flag to stop the orchestration, HITL.
        response:                       the final response to deliver to the user.
        prompt_tokens:                  current prompt token usage counter.
        completion_tokens:              current completion token usage counter.
        total_tokens:                   current token usage counter.
        start_at:                       ISO timestamp of when the orchestration started.
        time_elapsed:                   total elapsed time in seconds.
        error_message:                  the most recent error message, if any.
    """ 
    conversation_id: str
    orchestration_id: str
    messages: Annotated[list, add_messages]
    user_query: str
    plan: Annotated[list[Plan] | None, lambda _left, right: right]
    active_sub_agent_count: Annotated[int, operator.add]
    sub_agent_round_tasks: Annotated[list[SubAgentRoundTaskItem], merge_round_tasks]
    sub_agent_outputs: Annotated[dict, lambda left, right: {**left, **right}]
    orchestration_status: str
    orchestration_iteration: int
    should_orchestration_pause: bool
    should_orchestration_stop: bool
    response: Annotated[str, lambda _left, right: right]
    prompt_tokens: Annotated[int, operator.add]
    completion_tokens: Annotated[int, operator.add]
    total_tokens: Annotated[int, operator.add]
    start_at: str
    time_elapsed: float
    error_message: str
