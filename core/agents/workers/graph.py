"""ReAct agent factory for sub-agents.

Merges graph builder + agent assembler into one module.

Provides:
    build_react_agent(*, name, tools, system_prompt, state_cls,
                      control_tool_names) → CompiledStateGraph
"""

from typing import Literal

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage

from core.middleware.control_tool_node import ControlAwareToolNode
from core.agents.workers.state import SubAgentState
from core.agents.workers.nodes.prepare import make_prepare_node
from core.agents.workers.nodes.llm import make_llm
from core.agents.workers.nodes.summarize import make_summarize


def _build_react_graph(
    *,
    state_cls: type,
    prepare_node,
    llm_node,
    tools: list | None,
    summarize_node,
    control_tool_names: set[str] | None = None,
):
    """Build and compile the ReAct sub-agent graph.

    With tools:    prepare → llm ↔ tools → summarize
    Without tools: prepare → llm → summarize

    The llm node is followed by a conditional edge: tool-calling responses go
    to the tools node, plain responses go to the summarize node.

    Args:
        state_cls:      Sub-agent state schema (TypedDict).
        prepare_node:   Node that injects identity and system prompt.
        llm_node:       Node that invokes the LLM with bound tools.
        tools:          Tool list; None/empty builds a tool-less graph.
        control_tool_names: names of control tools (Command-writing) that must
                        run exclusively per turn; None means none, the tools
                        node then behaves exactly like a plain ToolNode.
        summarize_node: Node that extracts the final response and artifacts.

    Returns:
        Compiled StateGraph ready to run as a sub-graph node.
    """
    builder = StateGraph(state_cls)

    def _route(state) -> Literal["tools", "summarize"]:
        """Route the state to either the tools node or the summarize node."""
        if not state["sub_agent_messages"]:
            return "summarize"

        last_msg = state["sub_agent_messages"][-1]

        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            return "tools"

        return "summarize"

    builder.add_node("prepare", prepare_node)
    builder.add_node("llm", llm_node)
    builder.add_node("summarize", summarize_node)

    has_tools = tools and len(tools) > 0
    if has_tools:
        builder.add_node(
            "tools",
            ControlAwareToolNode(
                tools,
                control_tool_names=control_tool_names or frozenset(),
                messages_key="sub_agent_messages",
            ),
        )

    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "llm")

    if has_tools:
        builder.add_conditional_edges(
            "llm",
            _route,
            {
                "tools": "tools",
                "summarize": "summarize",
            },
        )
        builder.add_edge("tools", "llm")
    else:
        builder.add_edge("llm", "summarize")

    builder.add_edge("summarize", END)

    return builder.compile()


def build_react_agent(
    *,
    name: str,
    tools: list | None = None,
    system_prompt: str,
    state_cls: type = SubAgentState,
    control_tool_names: set[str] | None = None,
):
    """Build a ReAct agent sub-graph for a sub-agent.

    When tools are non-empty:  prepare → llm ↔ tools → summarize
    When tools are empty:      prepare → llm → summarize

    Args:
        name:          sub-agent type for logging (e.g. "programmer").
        tools:         @tool-decorated functions, or None/[] for no tools.
        system_prompt: sub-agent's system prompt string.
        state_cls:     TypedDict state schema (default SubAgentState).
        control_tool_names: names of control tools that own a turn exclusively
                        (e.g. PROGRAMMER_CONTROL_TOOL_NAME_SET); None means
                        the agent has no control tools.

    Returns:
        Compiled StateGraph, ready for use as a sub-graph node in the main
        graph via the LangGraph Send API.

    Example:
        researcher_graph = build_react_agent(
            name="researcher",
            tools=researcher_tools,
            system_prompt=RESEARCHER_SYSTEM_PROMPT,
            control_tool_names=RESEARCHER_CONTROL_TOOL_NAME_SET,
        )
    """
    prepare_node = make_prepare_node(system_prompt)
    llm_node = make_llm(tools)
    summarize_node = make_summarize(name)

    return _build_react_graph(
        state_cls=state_cls,
        prepare_node=prepare_node,
        llm_node=llm_node,
        tools=tools,
        summarize_node=summarize_node,
        control_tool_names=control_tool_names,
    )
