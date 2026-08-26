"""Orchestrator ReAct graph: LLM decision node + tool execution loop.

Provides:
- build_graph: compile the orchestrator ReAct graph
"""

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from core.agents.state import OrchestrationState
from core.agents.orchestrator import make_orchestrator_node, make_interrupt_node
from core.tools.bundles.orchestrator import ORCHESTRATOR_BASE_TOOLS
from utils.logging import get_logger

logger = get_logger(__name__)


def _orchestrator_tool_call_detected(state: OrchestrationState) -> bool:
    """Whether the latest message requests tool calls.

    Used to decide if the orchestrator should continue into the tool node.

    Returns:
        True if the last message carries tool calls; False on empty history.
    """
    messages = state['messages']
    if not messages:
        return False
    return bool(getattr(messages[-1], "tool_calls", None))


def build_graph():
    """Compile the orchestrator ReAct graph

    Routes orchestrator output to the tool node when the latest message
    carries tool calls, and to END otherwise, forming the classic
    ReAct loop: reason → act → observe → repeat.

    Returns:
        a compiled LangGraph StateGraph ready for ainvoke/astream.
    """
    graph_builder = StateGraph(OrchestrationState)

    orchestrator_node = make_orchestrator_node()
    interrupt_node = make_interrupt_node()

    graph_builder.add_node("orchestrator", orchestrator_node)
    graph_builder.add_node("interrupt", interrupt_node)
    graph_builder.add_node("tools", ToolNode(list(ORCHESTRATOR_BASE_TOOLS)))

    graph_builder.add_edge(START, "orchestrator")
    graph_builder.add_edge("interrupt", "orchestrator")
    graph_builder.add_edge("tools", "orchestrator")

    graph_builder.add_conditional_edges(
        "orchestrator",
        _orchestrator_tool_call_detected,
        {True: "tools", False: END},
    )

    return graph_builder.compile()
