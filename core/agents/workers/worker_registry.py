"""Sub-Agent Graph Registry and subgraph provider.

Sub-Graph Provides:
    PROGRAMMER_GRAPH  — full coding toolkit
    RESEARCHER_GRAPH  — web search + fetch + filesystem
    REVIEWER_GRAPH    — review code & content + verification
"""

from core.agents.workers.graph import build_react_agent
from core.agents.workers.state import (
    ProgrammerSubAgentState,
    ResearcherSubAgentState,
    ReviewerSubAgentState,
)
from core.prompts.system_prompt_programmer import PROGRAMMER_SYSTEM_PROMPT
from core.prompts.system_prompt_researcher import RESEARCHER_SYSTEM_PROMPT
from core.prompts.system_prompt_reviewer import REVIEWER_SYSTEM_PROMPT
from core.tools.bundles.programmer import PROGRAMMER_BASE_TOOLS, PROGRAMMER_CONTROL_TOOL_NAME_SET
from core.tools.bundles.researcher import RESEARCHER_BASE_TOOLS, RESEARCHER_CONTROL_TOOL_NAME_SET
from core.tools.bundles.reviewer import REVIEWER_BASE_TOOLS


PROGRAMMER_GRAPH = build_react_agent(
    name="programmer",
    tools=PROGRAMMER_BASE_TOOLS,
    system_prompt=PROGRAMMER_SYSTEM_PROMPT,
    state_cls=ProgrammerSubAgentState,
    control_tool_names=PROGRAMMER_CONTROL_TOOL_NAME_SET,
)

RESEARCHER_GRAPH = build_react_agent(
    name="researcher",
    tools=RESEARCHER_BASE_TOOLS,
    system_prompt=RESEARCHER_SYSTEM_PROMPT,
    state_cls=ResearcherSubAgentState,
    control_tool_names=RESEARCHER_CONTROL_TOOL_NAME_SET,
)

REVIEWER_GRAPH = build_react_agent(
    name="reviewer",
    tools=REVIEWER_BASE_TOOLS,
    system_prompt=REVIEWER_SYSTEM_PROMPT,
    state_cls=ReviewerSubAgentState,
)

__all__ = [
    "PROGRAMMER_GRAPH",
    "RESEARCHER_GRAPH",
    "REVIEWER_GRAPH",
]
