"""Comprehensive tests for end_orchestration: parameter validation, the state gate, plan-phase validation and the response contract.

Test cases:
- test_end_orchestration_success:                           normal termination with an exact message assertion
- test_end_orchestration_response_stripped:                 leading/trailing whitespace in response does not affect termination
- test_end_orchestration_response_max_length_boundary:      exactly at the MAX_RESPONSE_LENGTH boundary passes
- test_end_orchestration_plan_none_default:                 plan defaults to None and passes
- test_end_orchestration_plan_empty_list_allowed:           an empty list is treated as no plan and passes
- test_end_orchestration_plan_all_done_success:             termination succeeds when all phases are done
- test_end_orchestration_current_response_rejected:         non-empty current_response rejected (prevents last-win)
- test_end_orchestration_current_response_blank_rejected:   blank current_response treated as already invoked
- test_end_orchestration_current_response_empty_allowed:    empty-string current_response passes
- test_end_orchestration_should_orch_end_false_rejected:    the state gate False refuses termination
- test_end_orchestration_should_orch_end_type_invalid:      parametrized: all non-bool forms rejected
- test_end_orchestration_plan_type_invalid:                 parametrized: plan as str/dict/int/bool rejected
- test_end_orchestration_plan_element_type_invalid:         parametrized: non-dict plan elements rejected
- test_end_orchestration_plan_phase_id_invalid:             parametrized: empty/non-str phase_id rejected
- test_end_orchestration_plan_element_index_localization:   error messages localize the plan[j] index
- test_end_orchestration_plan_pending_status_rejected:      parametrized: incomplete statuses refuse termination
- test_end_orchestration_plan_multiple_pending_reported:    all incomplete phases are listed
- test_end_orchestration_response_type_invalid:             parametrized: non-str response rejected
- test_end_orchestration_response_empty_rejected:           parametrized: empty/blank response rejected
- test_end_orchestration_response_too_long_rejected:        overlong response rejected with the length reported
- test_end_orchestration_ok_response_contract:              ok response has only status/message fields
- test_end_orchestration_error_response_contract:           error response has only status/message fields
- test_end_orchestration_current_response_priority:         call-level guard takes priority over the state gate
- test_end_orchestration_should_orch_end_priority:          state gate takes priority over plan validation
- test_end_orchestration_plan_priority:                     plan validation takes priority over response validation
- test_end_orchestration_lifecycle_turn_semantics:          turn semantics: a second call after success is rejected

Covered scenarios:
- Parameter validation: response type/empty/blank/overlong (including the MAX_RESPONSE_LENGTH boundary); should_orch_end type and value gate (string "false" truthy trap); current_response prevents last-win (empty string passes / blank and non-empty rejected)
- Plan validation: type (list/None); element dict and non-empty str phase_id; incomplete phases (pending/in_progress/unknown status) refused with phase_ids listed; all done passes; error messages localize plan[j]
- Check-order contract: current_response → should_orch_end → plan → response; multiple violations on the same input report only the first in order
- Response contract: ok/error both have only status/message fields; no \\u escapes
- Turn semantics: first call succeeds → after simulating a state update, a second call is rejected
"""

import json

import pytest

from core.tools._kernel._orch_control import end_orchestration
from core.tools._kernel.constants import MAX_RESPONSE_LENGTH


def test_end_orchestration_success():
    result = json.loads(end_orchestration("final answer"))
    assert result == {"status": "ok", "message": "Orchestration ended."}


def test_end_orchestration_response_stripped():
    result = json.loads(end_orchestration("  final answer  "))
    assert result["status"] == "ok"


def test_end_orchestration_response_max_length_boundary():
    result = json.loads(end_orchestration("x" * MAX_RESPONSE_LENGTH))
    assert result["status"] == "ok"


def test_end_orchestration_plan_none_default():
    result = json.loads(end_orchestration("final"))
    assert result["status"] == "ok"


def test_end_orchestration_plan_empty_list_allowed():
    result = json.loads(end_orchestration("final", plan=[]))
    assert result["status"] == "ok"


def test_end_orchestration_plan_all_done_success():
    plan = [
        {"phase_id": "p1", "phase_status": "done"},
        {"phase_id": "p2", "phase_status": "done"},
    ]
    result = json.loads(end_orchestration("final", plan=plan))
    assert result["status"] == "ok"


def test_end_orchestration_current_response_rejected():
    result = json.loads(end_orchestration("final", current_response="old"))
    assert result["status"] == "error"
    assert "already called in this turn" in result["message"]


def test_end_orchestration_current_response_blank_rejected():
    result = json.loads(end_orchestration("final", current_response="   "))
    assert result["status"] == "error"
    assert "already called in this turn" in result["message"]


def test_end_orchestration_current_response_empty_allowed():
    result = json.loads(end_orchestration("final", current_response=""))
    assert result["status"] == "ok"


def test_end_orchestration_should_orch_end_false_rejected():
    result = json.loads(end_orchestration("final", should_orch_end=False))
    assert result["status"] == "error"
    assert "should_orch_end is False" in result["message"]


@pytest.mark.parametrize("should_orch_end", [None, "false", "False", 0, 1, [], {}])
def test_end_orchestration_should_orch_end_type_invalid(should_orch_end):
    result = json.loads(end_orchestration("final", should_orch_end=should_orch_end))
    assert result["status"] == "error"
    assert "must be a boolean" in result["message"]


@pytest.mark.parametrize("plan", ["[{}]", {"a": 1}, 123, True])
def test_end_orchestration_plan_type_invalid(plan):
    result = json.loads(end_orchestration("final", plan=plan))
    assert result["status"] == "error"
    assert "plan must be a list or None" in result["message"]


@pytest.mark.parametrize("element", ["abc", None, 123])
def test_end_orchestration_plan_element_type_invalid(element):
    result = json.loads(end_orchestration("final", plan=[element]))
    assert result["status"] == "error"
    assert "plan[0] must be a dict" in result["message"]


@pytest.mark.parametrize("phase_id", ["", "   ", 123, None, True])
def test_end_orchestration_plan_phase_id_invalid(phase_id):
    result = json.loads(end_orchestration(
        "final", plan=[{"phase_id": phase_id, "phase_status": "done"}]))
    assert result["status"] == "error"
    assert "plan[0] must be a dict with a non-empty string phase_id" in result["message"]


def test_end_orchestration_plan_element_index_localization():
    result = json.loads(end_orchestration(
        "final", plan=[{"phase_id": "p1", "phase_status": "done"}, {"phase_status": "done"}]))
    assert result["status"] == "error"
    assert "plan[1]" in result["message"]


@pytest.mark.parametrize("status", ["pending", "in_progress", "doing"])
def test_end_orchestration_plan_pending_status_rejected(status):
    result = json.loads(end_orchestration(
        "final", plan=[{"phase_id": "p1", "phase_status": status}]))
    assert result["status"] == "error"
    assert "still pending" in result["message"]
    assert "p1" in result["message"]


def test_end_orchestration_plan_multiple_pending_reported():
    plan = [
        {"phase_id": "p1", "phase_status": "pending"},
        {"phase_id": "p2", "phase_status": "in_progress"},
    ]
    result = json.loads(end_orchestration("final", plan=plan))
    assert result["status"] == "error"
    assert "2 phase(s) still pending" in result["message"]
    assert "['p1', 'p2']" in result["message"]


@pytest.mark.parametrize("response", [None, 123, {"a": 1}, ["x"], True])
def test_end_orchestration_response_type_invalid(response):
    result = json.loads(end_orchestration(response))
    assert result["status"] == "error"
    assert "response must be a string" in result["message"]


@pytest.mark.parametrize("response", ["", "   "])
def test_end_orchestration_response_empty_rejected(response):
    result = json.loads(end_orchestration(response))
    assert result["status"] == "error"
    assert "response must be a non-empty string" in result["message"]


def test_end_orchestration_response_too_long_rejected():
    result = json.loads(end_orchestration("x" * (MAX_RESPONSE_LENGTH + 1)))
    assert result["status"] == "error"
    assert f"response too long ({MAX_RESPONSE_LENGTH + 1} chars)" in result["message"]
    assert f"Max {MAX_RESPONSE_LENGTH}" in result["message"]


def test_end_orchestration_ok_response_contract():
    result = json.loads(end_orchestration("final"))
    assert set(result.keys()) == {"status", "message"}


def test_end_orchestration_error_response_contract():
    result = json.loads(end_orchestration("final", should_orch_end=False))
    assert set(result.keys()) == {"status", "message"}


def test_end_orchestration_current_response_priority():
    result = json.loads(end_orchestration(
        "final", current_response="old", should_orch_end=False))
    assert result["status"] == "error"
    assert "already called in this turn" in result["message"]
    assert "should_orch_end" not in result["message"]


def test_end_orchestration_should_orch_end_priority():
    result = json.loads(end_orchestration(
        "final", should_orch_end=False,
        plan=[{"phase_id": "p1", "phase_status": "pending"}]))
    assert result["status"] == "error"
    assert "should_orch_end is False" in result["message"]
    assert "still pending" not in result["message"]


def test_end_orchestration_plan_priority():
    result = json.loads(end_orchestration(
        123, plan=[{"phase_id": "p1", "phase_status": "pending"}]))
    assert result["status"] == "error"
    assert "still pending" in result["message"]
    assert "response" not in result["message"]


def test_end_orchestration_lifecycle_turn_semantics():
    first = json.loads(end_orchestration("final", current_response=""))
    assert first["status"] == "ok"
    second = json.loads(end_orchestration("final", current_response="final"))
    assert second["status"] == "error"
    assert "already called in this turn" in second["message"]
