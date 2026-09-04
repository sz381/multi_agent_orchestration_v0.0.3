"""Orchestrator main graph: nodes, routing, and sub-agent fanout/collect.

Provides:
- build_graph: compile the full orchestration graph -- orchestrator ReAct
  loop, HITL interrupt, sub-agent fanout via Send, and the collect barrier.
"""

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langchain_core.messages import AIMessage

from core.agents.state import OrchestrationState
from core.agents.constants import MAX_RESULT_SUMMARY_CHARS, SUB_AGENT_RESULT_PREFIX
from core.agents.announce import make_announce_node
from core.agents.orchestrator import make_orchestrator_node, make_interrupt_node
from core.agents.workers.worker_registry import (
    PROGRAMMER_GRAPH,
    RESEARCHER_GRAPH,
    REVIEWER_GRAPH,
)
from core.middleware.constants import (
    AGENT_ROLE_PROGRAMMER,
    AGENT_ROLE_RESEARCHER,
    AGENT_ROLE_REVIEWER,
    SUB_AGENT_ROLES,
)
from core.middleware.control_tool_node import ControlAwareToolNode
from core.middleware.orchestration_callback import OrchestrationCallBack
from core.tools.bundles.orchestrator import (
    ORCHESTRATOR_BASE_TOOLS,
    ORCHESTRATOR_CONTROL_TOOL_NAME_SET,
)
from utils.logging import get_logger

logger = get_logger(__name__)


def _orchestrator_tool_call_detected(state: OrchestrationState) -> bool:
    """Whether the latest message requests tool calls.

    Used to decide if the orchestrator should continue into the tool node.

    Returns:
        True if the last message is an AIMessage carrying tool calls;
        False otherwise, including on empty history.
    """
    messages = state["messages"]
    if not messages:
        return False
    last_msg = messages[-1]
    return isinstance(last_msg, AIMessage) and bool(getattr(last_msg, "tool_calls", None))


def _route_after_orchestrator(state: OrchestrationState) -> str:
    """Route the orchestrator after an LLM step.

    Priority: human-in-the-loop pause, explicit stop, then tool-call
    continuation; otherwise the orchestration is complete.

    Returns:
        "interrupt", "tools", or END.
    """
    if state.get("should_orchestration_pause"):
        return "interrupt"

    if state.get("should_orchestration_stop"):
        return END

    if _orchestrator_tool_call_detected(state):
        return "tools"

    if state.get("response"):
        return END

    return "orchestrator"


def _build_sub_agent_send(task: dict) -> Send:
    """Build the Send dispatching one fanout task to its sub-agent node.

    The subgraph node name is the role prefix of `subagent_id`
    (e.g. `programmer_001` -> `programmer`). Fail fast on an unregistered
    prefix: raising here is far more diagnosable than LangGraph failing
    with an unknown-node error halfway through the run.

    Returns:
        A Send carrying the identity fields consumed by the prepare node.
    """
    subagent_id = task["subagent_id"]
    node = subagent_id.split("_", 1)[0]

    if node not in SUB_AGENT_ROLES:
        raise RuntimeError(
            f"unknown sub-agent node prefix {node!r} from subagent_id {subagent_id!r}"
        )

    return Send(
        node=node,
        arg={
            "sub_agent_id": subagent_id,
            "sub_agent_name": task["subagent_name"],
            "task_id": task["task_id"],
            "task_name": task["task_name"],
            "task_description": task["task_description"],
        },
    )


def _route_after_tools(state: OrchestrationState):
    """Route after the tool node runs.

    When `end_orchestration` has written the handoff note into the state
    (the tool updates `response` directly, so no message scanning is
    needed), hands over to the announce node to stream the final
    user-facing message; otherwise fans out sub-agents when round tasks
    are pending, or returns to the orchestrator for the next round.

    Returns:
        "announce", a list of Send for parallel sub-agent dispatch, or
        "orchestrator".
    """
    # end_orchestration succeeded -> the handoff note is in the state;
    # announce streams the final message while the orchestrator is never
    # re-awakened (ghost continuation, issue 8_02_005_v002)
    if state.get("response"):
        return "announce"

    tasks = state.get("sub_agent_round_tasks") or []
    if tasks:
        return [_build_sub_agent_send(t) for t in tasks]

    return "orchestrator"


def _format_sub_agent_result(task_id: str, out: dict) -> str:
    """Format one sub-agent result into a report injected into the parent context.

    Args:
        task_id:    sub-agent task id (key of sub_agent_outputs).
        out:        the result dict of this task in sub_agent_outputs.

    Returns:
        The individual report text.
    """
    summary = (out.get("result_summary") or "").strip()

    if not summary:
        logger.warning(
            "sub_agent_result_summary_missing",
            task_id=task_id,
            sub_agent=out.get("sub_agent", "N/A"),
            sub_agent_id=out.get("sub_agent_id", "N/A"),
            sub_agent_name=out.get("sub_agent_name", "N/A"),
            status=out.get("status", "unknown"),
        )

    if len(summary) > MAX_RESULT_SUMMARY_CHARS:
        summary = summary[:MAX_RESULT_SUMMARY_CHARS] + "... [truncated]"

    status = out.get("status", "unknown")
    elapsed = out.get("elapsed_seconds", 0)
    artifacts = out.get("artifacts") or []

    return (
        f"{SUB_AGENT_RESULT_PREFIX} task_id={task_id} "
        f"status={status} elapsed={elapsed}s artifacts={len(artifacts)}\n"
        f"summary: {summary}"
    )


def _build_result_injections(state: OrchestrationState) -> list:
    """Build the not-yet-injected sub-agent result messages.

    Iterate the accumulated sub_agent_outputs and build one AIMessage per
    task; skip tasks whose report is already present in the parent messages
    (matched by prefix), to avoid duplicate injection across fanout rounds.

    Returns:
        The AIMessage list (empty when nothing new is added).
    """
    outputs = state.get("sub_agent_outputs") or {}
    if not outputs:
        tasks = state.get("sub_agent_round_tasks") or []
        logger.warning(
            "collect_no_sub_agent_outputs",
            round_tasks_count=len(tasks),
            sub_agent_ids=[t.get("subagent_id", "N/A") for t in tasks],
            task_ids=[t.get("task_id", "N/A") for t in tasks],
            active_sub_agent_count=state.get("active_sub_agent_count", "N/A"),
            orchestration_iteration=state.get("orchestration_iteration", "N/A"),
            user_query=(state.get("user_query") or "")[:120],
        )
        return []

    # Collect the task ids whose report has already been injected into the
    # parent messages. sub_agent_outputs accumulates across rounds (the
    # reducer merges dicts, keyed by task_id), and _collect_sub_agent_results
    # runs at the end of every round -- without dedup, a second-round collect
    # would re-inject the first-round reports and duplicate them in the
    # orchestrator context.
    injected_ids = set()
    for m in state.get("messages") or []:
        content = str(getattr(m, "content", "") or "")
        for tid in outputs:
            if f"{SUB_AGENT_RESULT_PREFIX} task_id={tid} " in content:
                injected_ids.add(tid)

    injections = []
    for tid, out in outputs.items():
        if tid in injected_ids:
            continue

        # A stable message id keeps the injection idempotent: the
        # add_messages reducer replaces messages with the same id instead of
        # appending, so even a duplicate injection replaces the original
        # message rather than piling up copies.
        injections.append(
            AIMessage(
                content=_format_sub_agent_result(tid, out),
                id=f"collect-result-{tid}",
            )
        )

        logger.info(
            "inject_sub_agent_result",
            sub_agent=out.get("sub_agent", "N/A"),
            sub_agent_id=out.get("sub_agent_id", "N/A"),
            sub_agent_name=out.get("sub_agent_name", "N/A"),
            task_id=tid,
            task_name=out.get("task_name", "N/A"),
            status=out.get("status", "unknown"),
            artifacts_count=len(out.get("artifacts") or []),
            elapsed_seconds=out.get("elapsed_seconds", 0),
            summary_preview=(out.get("result_summary") or "")[:200],
        )

    return injections


def _collect_sub_agent_results(state: OrchestrationState) -> dict:
    """Collect barrier for a fanout round.

    Clears the round tasks and decrements the active sub-agent counter
    (operator.add); when the counter reaches zero, all sub-agents are done
    and the accumulated results are injected into the parent messages so the
    awakened orchestrator sees them.

    Returns:
        State updates dict (round tasks reset, counter decrement, and
        optionally the injected result messages).
    """
    tasks = state.get("sub_agent_round_tasks") or []

    logger.debug(
        "collect_sub_agent_results",
        task_count=len(tasks),
        counter_before=state.get("active_sub_agent_count", "N/A"),
    )

    counter = state.get("active_sub_agent_count", 0)
    remaining = counter - len(tasks)

    # Negative-counter drift (8_03_007_v002): when a previous collect failed to
    # clear the round tasks (merge-reducer reset regression), stale tasks
    # re-dispatch every round and each collect keeps subtracting -- the
    # counter spirals negative. Log it so the anomaly is visible; the
    # remaining <= 0 branch below still injects results and wakes the
    # orchestrator.
    if counter < 0:
        logger.warning(
            "collect_negative_counter",
            counter_before=counter,
            task_count=len(tasks),
            reason="counter drifted below zero -- stale round tasks were re-dispatched",
        )

    updates = {
        "sub_agent_round_tasks": [],
        "active_sub_agent_count": -len(tasks),
    }

    # Phantom-counter self-heal (8_03_006_v002): when the model fires several
    # fanout_subagents calls in one round, each Command adds its own task
    # count to the counter (operator.add) -- with an overwrite reducer the
    # tasks themselves got dropped, leaving a positive counter with no
    # branches behind. All branches have finished once collect runs
    # (LangGraph superstep barrier), so any remaining positive counter is a
    # phantom: zero it and still wake the orchestrator instead of ENDing
    # the graph mid-run.
    if remaining > 0:
        logger.warning(
            "collect_phantom_counter_self_heal",
            counter_before=counter,
            task_count=len(tasks),
            reason="counter exceeds dispatched tasks -- parallel fanout artifact, zeroed",
        )
        updates["active_sub_agent_count"] = -counter
        remaining = 0

    # All sub-agents of the round have completed: inject the summary results
    # into the parent messages, so the awakened orchestrator sees the
    # completion signals and results instead of assuming the tasks are still
    # running asynchronously.
    if remaining <= 0:
        injections = _build_result_injections(state)
        if injections:
            logger.info("collect_inject_sub_agent_results", count=len(injections))
            updates["messages"] = injections

    return updates


def _route_after_collect(state: OrchestrationState) -> str:
    """Route after the collect barrier.

    If the active sub-agent counter is still positive, more sub-agents are
    still running in this fanout round, so the chain ends and waits for the
    remaining branches; otherwise all results are in and the orchestrator is
    awakened.

    Returns:
        "orchestrator" when all sub-agents are done, else END.
    """
    # if we have more active sub-agents running in the background, and the current
    # sub-agent is done, we END the current chain, so that we can wait for the remaining branches
    if state.get("active_sub_agent_count", 0) > 0:
        logger.debug("route_after_collect", counter=state["active_sub_agent_count"], decision=END)
        return END

    # if we have no more active sub-agents running in the background, we route back to the orchestrator
    logger.debug("route_after_collect", counter=state["active_sub_agent_count"], decision="orchestrator")
    return "orchestrator"


def build_graph(callback_handler: OrchestrationCallBack):
    """Build and compile the orchestrator state graph.

    Nodes: orchestrator (LLM), tools, interrupt (HITL), announce (streams
    the final message after end_orchestration), the collect barrier, and
    one bare subgraph per sub-agent role (programmer / researcher /
    reviewer). No wrapper is needed: the subgraphs share only keys that all
    carry reducers in the parent state (sub_agent_outputs merge, token
    counters add), so the subgraph output can flow back safely.

    Conditional routing: orchestrator <-> tools loop, fanout via Send,
    collect barrier back to orchestrator, and the handover to announce
    once end_orchestration has written the handoff note.

    Returns:
        The compiled LangGraph ready for ainvoke/astream.
    """
    builder = StateGraph(OrchestrationState)

    orchestrator_node = make_orchestrator_node()
    interrupt_node = make_interrupt_node()
    announce_node = make_announce_node()
    tool_node = ControlAwareToolNode(
        list(ORCHESTRATOR_BASE_TOOLS),
        control_tool_names=ORCHESTRATOR_CONTROL_TOOL_NAME_SET,
        callback_handler=callback_handler,
    )

    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("tools", tool_node)
    builder.add_node("interrupt", interrupt_node)
    builder.add_node("announce", announce_node)
    builder.add_node("collect_sub_agent_results", _collect_sub_agent_results)

    SUBAGENT_MAP = {
        AGENT_ROLE_PROGRAMMER: PROGRAMMER_GRAPH,
        AGENT_ROLE_RESEARCHER: RESEARCHER_GRAPH,
        AGENT_ROLE_REVIEWER: REVIEWER_GRAPH,
    }
    for name, subgraph in SUBAGENT_MAP.items():
        builder.add_node(name, subgraph)

    builder.add_edge(START, "orchestrator")
    builder.add_edge("interrupt", "orchestrator")
    builder.add_edge("announce", END)

    for name in SUBAGENT_MAP:
        builder.add_edge(name, "collect_sub_agent_results")

    builder.add_conditional_edges(
        "collect_sub_agent_results",
        _route_after_collect,
        {
            "orchestrator": "orchestrator",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "orchestrator",
        _route_after_orchestrator,
        {
            "tools": "tools",
            "interrupt": "interrupt",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "tools",
        _route_after_tools,
        {
            "orchestrator": "orchestrator",
            "announce": "announce",
        },
    )

    return builder.compile()
