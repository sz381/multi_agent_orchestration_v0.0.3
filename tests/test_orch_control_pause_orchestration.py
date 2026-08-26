"""Comprehensive tests for pause_orchestration: boolean type validation, the state gate and the response contract.

Test cases:
- test_pause_orchestration_success:                       pausing with True succeeds with an exact message assertion
- test_pause_orchestration_false_rejected:                the state gate False refuses to pause
- test_pause_orchestration_type_invalid:                  parametrized: all non-bool forms rejected
- test_pause_orchestration_bool_not_int_subclass:         exact bool matching: 1 rejected while True passes
- test_pause_orchestration_ok_response_contract:          ok response has only status/message fields
- test_pause_orchestration_error_response_contract:       error response has only status/message fields
- test_pause_orchestration_chinese_not_escaped:           ensure_ascii=False emits no \\u escapes

Covered scenarios:
- Parameter validation: should_orch_pause must be a bool (the string "false" is truthy and would wrongly pass; ints like 0/1 are rejected)
- State gate: pausing is refused when False; the blocking state must be cleared first
- Exact bool matching: bool is an int subclass, so 1 and True must be distinguished
- Response contract: ok/error both have only status/message fields; no \\u escapes
"""

import json

import pytest

from core.tools._kernel._orch_control import pause_orchestration


def test_pause_orchestration_success():
    result = json.loads(pause_orchestration(True))
    assert result == {"status": "ok", "message": "Orchestration paused."}


def test_pause_orchestration_false_rejected():
    result = json.loads(pause_orchestration(False))
    assert result["status"] == "error"
    assert "should_orch_pause is False" in result["message"]


@pytest.mark.parametrize("should_orch_pause", [None, "false", "False", 0, 1, [], {}])
def test_pause_orchestration_type_invalid(should_orch_pause):
    result = json.loads(pause_orchestration(should_orch_pause))
    assert result["status"] == "error"
    assert "must be a boolean" in result["message"]


def test_pause_orchestration_bool_not_int_subclass():
    assert json.loads(pause_orchestration(1))["status"] == "error"
    assert json.loads(pause_orchestration(True))["status"] == "ok"


def test_pause_orchestration_ok_response_contract():
    result = json.loads(pause_orchestration(True))
    assert set(result.keys()) == {"status", "message"}


def test_pause_orchestration_error_response_contract():
    result = json.loads(pause_orchestration(False))
    assert set(result.keys()) == {"status", "message"}


def test_pause_orchestration_chinese_not_escaped():
    raw = pause_orchestration(True)
    assert "\\u" not in raw
