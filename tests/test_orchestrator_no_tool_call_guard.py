"""Regression tests for the bounded no-tool-call orchestrator retry."""

from langchain_core.messages import AIMessage
from langgraph.graph import END

from core.agents.graph import (
    _orchestration_failure_after_no_tool_retry,
    _route_after_orchestrator,
    _route_after_orchestrator_retry,
    _route_after_tools,
)


def _state(**overrides):
    state = {
        "messages": [AIMessage(content="I will now delegate the work.")],
        "plan": [
            {
                "phase_id": "p2",
                "phase_name": "implementation",
                "phase_status": "in_progress",
                "phase_description": "Implement the requested feature.",
            }
        ],
        "should_orchestration_pause": False,
        "should_orchestration_stop": False,
        "response": "",
        "error_message": "",
        "orchestration_iteration": 4,
        "sub_agent_round_tasks": [],
    }
    state.update(overrides)
    return state


def _tool_call_response() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "fanout_subagents",
                "args": {"tasks": []},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )


def test_initial_text_only_response_gets_one_retry():
    assert _route_after_orchestrator(_state()) == "orchestrator_retry"


def test_initial_tool_call_still_enters_tool_node():
    assert _route_after_orchestrator(
        _state(messages=[_tool_call_response()])
    ) == "tools"


def test_retry_tool_call_still_enters_tool_node():
    assert _route_after_orchestrator_retry(
        _state(messages=[_tool_call_response()])
    ) == "tools"


def test_second_text_only_response_enters_explicit_failure_node():
    assert _route_after_orchestrator_retry(_state()) == "orchestration_failure"


def test_failure_node_reports_incomplete_phases():
    updates = _orchestration_failure_after_no_tool_retry(_state())

    assert updates["orchestration_status"] == "failed"
    assert "Incomplete phases: p2." in updates["error_message"]
    assert "end_orchestration" in updates["error_message"]


def test_pause_stop_and_invocation_error_keep_priority():
    assert _route_after_orchestrator(
        _state(should_orchestration_pause=True)
    ) == "interrupt"
    assert _route_after_orchestrator(
        _state(should_orchestration_stop=True)
    ) == END
    assert _route_after_orchestrator(
        _state(error_message="provider unavailable")
    ) == END


def test_successful_end_still_routes_to_announce_after_tools():
    assert _route_after_tools(_state(response="handoff note")) == "announce"
