"""LangGraph state definitions for the workers subgraph.  

Provides:
- SubAgentState                 Base state shared by all sub-agents in the workers subgraph.
- ProgrammerSubAgentState       SubAgentState with a programmer execution plan.
- ResearcherSubAgentState       SubAgentState specialized for the researcher.
- ReviewerSubAgentState         SubAgentState specialized for the reviewer.
"""

from typing import TypedDict, Annotated, NotRequired

from langgraph.graph.message import add_messages

from core.agents.state import Plan


class SubAgentState(TypedDict):
    """Top-level state carried through the workers subgraph.

    Attributes:
        sub_agent_id:                     Unique identifier for this sub-agent.
        sub_agent_name:                   Short human-readable label for sub-agent.
        task_id:                          Unique identifier for sub-agent's task.
        task_name:                        Short human-readable label for task.
        task_description:                 What the sub-agent should do in this task.
        sub_agent_messages:               Full message history.
        sub_agent_outputs:                Merged outputs from completed sub-agents.
        file_changes:                     Real-time record of files written/modified
        prompt_tokens:                    Running prompt token usage counter.
        completion_tokens:                Running completion token usage counter.
        total_tokens:                     Running total token usage counter.
        sub_agent_iteration:              ReAct loop iteration count.
        sub_agent_start_at:               ISO timestamp when sub-agent started.
        sub_agent_time_elapsed:           Total elapsed time in seconds.
        sub_agent_error_message:          Last error message, if any.
    """
    sub_agent_id: str
    sub_agent_name: str
    task_id: str
    task_name: str
    task_description: str
    sub_agent_messages: Annotated[list, add_messages]
    sub_agent_outputs: Annotated[dict, lambda left, right: {**left, **right}]
    file_changes: Annotated[list, lambda left, right: left + [p for p in right if p not in left]]
    prompt_token: int
    completion_tokens: int
    total_tokens: int
    sub_agent_iteration: int
    sub_agent_start_at: str
    sub_agent_time_elapsed: float
    sub_agent_error_message: str


class ProgrammerSubAgentState(SubAgentState):
    """
    SubAgentState extended with an execution plan for the programmer.

    Attributes:
        sub_agent_plan:                 Execution plan for the programmer.
    """
    sub_agent_plan: Annotated[list[Plan] | None, lambda _left, right: right]


class ResearcherSubAgentState(SubAgentState):
    """
    SubAgentState specialised for the researcher sub-agent.
    """
    sub_agent_plan: Annotated[list[Plan] | None, lambda _left, right: right]


class ReviewerSubAgentState(SubAgentState):
    """
    SubAgentState specialised for the reviewer sub-agent.
    """
    pass
