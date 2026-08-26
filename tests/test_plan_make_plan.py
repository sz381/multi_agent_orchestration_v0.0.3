"""Comprehensive tests for make_plan: parameter validation, field validation, dedup semantics, existing_plan protection and the response contract.

Test cases:
- test_make_plan_single_phase_success:               single-phase creation succeeds and returns the plan structure
- test_make_plan_multiple_phases_order_kept:         multi-phase creation keeps input order
- test_make_plan_max_phases_allowed:                 12 phases (upper boundary) created successfully
- test_make_plan_exceed_max_phases_rejected:         13 phases over the limit rejected
- test_make_plan_strips_phase_id:                    phase_id stored with leading/trailing whitespace removed
- test_make_plan_strips_name_description:            phase_name/description have leading/trailing whitespace removed
- test_make_plan_status_requires_exact_value:        phase_status is not stripped (exact set matching)
- test_make_plan_ok_message_reports_count:           ok message reports the phase count
- test_make_plan_ok_response_contract:               ok response has only status/message/plan fields
- test_make_plan_error_response_has_no_plan:         error response has no plan field
- test_make_plan_chinese_not_escaped:                ensure_ascii=False emits Chinese directly
- test_make_plan_phases_type_invalid:                parametrized: None/dict/int/bool rejected
- test_make_plan_phases_empty_list:                  an empty list is rejected
- test_make_plan_phases_json_string_success:         JSON-string input creates successfully
- test_make_plan_phases_json_string_invalid:         parametrized: all forms of invalid JSON strings rejected
- test_make_plan_phase_as_json_string:               an element as a JSON string succeeds
- test_make_plan_phase_as_invalid_json_string:       an element string that is not JSON is rejected
- test_make_plan_phase_type_invalid:                 parametrized: list/int/None/bool elements rejected
- test_make_plan_phase_non_string_keys_rejected:     non-string keys rejected (sorted crash protection)
- test_make_plan_phase_missing_fields:               parametrized: any missing required field rejected
- test_make_plan_phase_missing_multiple_reported:    all missing fields are listed
- test_make_plan_phase_extra_field_rejected:         extra fields rejected
- test_make_plan_phase_multiple_extra_sorted:        multiple extra fields listed sorted
- test_make_plan_extra_checked_before_missing:       extra check takes priority over missing
- test_make_plan_phase_id_invalid:                   parametrized: empty/blank/non-str/None/bool id rejected
- test_make_plan_phase_name_invalid:                 parametrized: empty/blank/non-str/None name rejected
- test_make_plan_phase_description_invalid:          parametrized: empty/blank/non-str/None desc rejected
- test_make_plan_phase_status_invalid:               parametrized: invalid value/list/dict/int/None/bool rejected
- test_make_plan_phase_status_all_valid_values:      parametrized: all three valid statuses pass
- test_make_plan_duplicate_phase_id_rejected:        fully duplicated ids rejected
- test_make_plan_duplicate_detected_after_strip:     duplicated ids after strip rejected
- test_make_plan_duplicate_case_sensitive:           different cases are not duplicates
- test_make_plan_error_reports_phase_index:          error messages localize the phase[i] index
- test_make_plan_second_phase_error_localization:    the second phase's error localizes phase[1]
- test_make_plan_existing_plan_rejected:             rebuilding with an existing plan rejected (prevents last-win)
- test_make_plan_existing_plan_message_counts:       rejection message includes the existing phase count
- test_make_plan_existing_plan_empty_list_allowed:   an empty list treated as no plan and passes
- test_make_plan_existing_plan_none_default:         None default passes
- test_make_plan_existing_plan_type_invalid:         parametrized: str/dict/int rejected
- test_make_plan_lifecycle_reject_while_plan_exists: make again after make without clearing is rejected
- test_make_plan_lifecycle_recreate_after_delete_all: rebuild succeeds after clearing
- test_make_plan_lifecycle_make_edit_make_rejected:   mixed: make → edit → make again rejected (edit does not unlock rebuilding)
- test_make_plan_lifecycle_make_delete_partial_then_recreate: mixed: make → partial delete → make rejected → clear → make succeeds
- test_make_plan_lifecycle_full_chain_rebuild:         mixed full chain: make → edit → delete → delete_all → rebuild
- test_make_plan_lifecycle_failed_edit_then_recreate:  mixed: make → edit failed (atomicity) → clear → make succeeds
- test_make_plan_lifecycle_mixed_input_formats:        mixed: dict-list make → JSON-string edit → regular delete

Covered scenarios:
- Parameter validation: phases not a list (None/dict/int/bool) and empty list rejected; non-dict elements (list/int/None/bool) rejected; non-string keys rejected (sorted crash protection); missing/extra field whitelist validation; id/name/desc empty, blank, non-str, None rejected; exact status-set matching with unhashable inputs (list/dict) rejected
- Input forms: phases supports dict lists and JSON strings (including element-level JSON strings); all invalid JSON forms (syntax error/parsed to dict/int/null/empty array) rejected
- Dedup semantics: fully duplicated and duplicated-after-strip both rejected; case-sensitive, no dedup across cases; error messages localize the phase[i] index
- Response contract: ok has only status/message/plan fields; error has no plan (no half-finished product); message reports the phase count; Chinese emitted directly with ensure_ascii=False
- Rebuild protection: non-empty existing_plan rejects rebuilding (message includes the existing phase count); empty list/None pass; str/dict/int types rejected
- Lifecycle mixed chains: make again after make without clearing rejected; rebuild succeeds after delete_all; edit does not unlock rebuilding; partial delete still rejects, only clearing passes; atomic edit failure does not pollute later delete/make; chained across input forms (dict lists/JSON strings)
"""

import json

import pytest

from core.tools._kernel._plan import delete_plan, edit_plan, make_plan
from tests.helpers import _ok_phases, _phase


def test_make_plan_single_phase_success():
    result = json.loads(make_plan([_phase()]))
    assert result["status"] == "ok"
    assert result["plan"] == [_phase()]
    assert result["message"] == "Plan created with 1 phases."


def test_make_plan_multiple_phases_order_kept():
    phases = [
        _phase(phase_id="p1"),
        _phase(phase_id="p2", phase_name="阶段二"),
        _phase(phase_id="p3"),
    ]
    result = json.loads(make_plan(phases))
    assert result["status"] == "ok"
    assert [p["phase_id"] for p in result["plan"]] == ["p1", "p2", "p3"]
    assert result["plan"] == phases


def test_make_plan_max_phases_allowed():
    result = json.loads(make_plan(_ok_phases(12)))
    assert result["status"] == "ok"
    assert len(result["plan"]) == 12


def test_make_plan_exceed_max_phases_rejected():
    result = json.loads(make_plan(_ok_phases(13)))
    assert result["status"] == "error"
    assert "Too many phases (13). Max 12." in result["message"]


def test_make_plan_strips_phase_id():
    result = json.loads(make_plan([_phase(phase_id="  p1  ")]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_id"] == "p1"


def test_make_plan_strips_name_description():
    result = json.loads(make_plan([_phase(phase_name="  阶段一  ", phase_description="  描述  ")]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "阶段一"
    assert result["plan"][0]["phase_description"] == "描述"


def test_make_plan_status_requires_exact_value():
    result = json.loads(make_plan([_phase(phase_status=" pending ")]))
    assert result["status"] == "error"
    assert "phase_status must be one of" in result["message"]


def test_make_plan_ok_message_reports_count():
    result = json.loads(make_plan(_ok_phases(3)))
    assert result["status"] == "ok"
    assert "Plan created with 3 phases." in result["message"]


def test_make_plan_ok_response_contract():
    result = json.loads(make_plan([_phase()]))
    assert set(result.keys()) == {"status", "message", "plan"}


def test_make_plan_error_response_has_no_plan():
    result = json.loads(make_plan([]))
    assert result["status"] == "error"
    assert "plan" not in result


def test_make_plan_chinese_not_escaped():
    raw = make_plan([_phase()])
    assert "阶段一" in raw
    assert "\\u" not in raw


@pytest.mark.parametrize("phases", [None, {"a": 1}, 123, True])
def test_make_plan_phases_type_invalid(phases):
    result = json.loads(make_plan(phases))
    assert result["status"] == "error"
    assert "non-empty list" in result["message"]


def test_make_plan_phases_empty_list():
    result = json.loads(make_plan([]))
    assert result["status"] == "error"
    assert "non-empty list" in result["message"]


def test_make_plan_phases_json_string_success():
    result = json.loads(make_plan(json.dumps([_phase()])))
    assert result["status"] == "ok"
    assert result["plan"] == [_phase()]


@pytest.mark.parametrize("phases, expected", [
    ("not json", "not a JSON string"),
    ("{bad", "not a JSON string"),
    ('"123"', "non-empty list"),
    ("null", "non-empty list"),
    ("{}", "non-empty list"),
    ("[]", "non-empty list"),
])
def test_make_plan_phases_json_string_invalid(phases, expected):
    result = json.loads(make_plan(phases))
    assert result["status"] == "error"
    assert expected in result["message"]


def test_make_plan_phase_as_json_string():
    result = json.loads(make_plan([json.dumps(_phase(phase_id="e1"))]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_id"] == "e1"


def test_make_plan_phase_as_invalid_json_string():
    result = json.loads(make_plan(["abc"]))
    assert result["status"] == "error"
    assert "must be a valid JSON string" in result["message"]


@pytest.mark.parametrize("phase", [[1], 123, None, True])
def test_make_plan_phase_type_invalid(phase):
    result = json.loads(make_plan([phase]))
    assert result["status"] == "error"
    assert "must be a dict" in result["message"]


def test_make_plan_phase_non_string_keys_rejected():
    result = json.loads(make_plan([{1: "x", "phase_id": "p1", "phase_name": "n",
                                    "phase_status": "pending", "phase_description": "d"}]))
    assert result["status"] == "error"
    assert "keys must be strings" in result["message"]


@pytest.mark.parametrize("field", ["phase_id", "phase_name", "phase_status", "phase_description"])
def test_make_plan_phase_missing_fields(field):
    phase = _phase()
    del phase[field]
    result = json.loads(make_plan([phase]))
    assert result["status"] == "error"
    assert "missing required fields" in result["message"]
    assert field in result["message"]


def test_make_plan_phase_missing_multiple_reported():
    result = json.loads(make_plan([{"phase_id": "p1"}]))
    assert result["status"] == "error"
    for field in ("phase_name", "phase_status", "phase_description"):
        assert field in result["message"]


def test_make_plan_phase_extra_field_rejected():
    result = json.loads(make_plan([_phase(extra_field=1)]))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "extra_field" in result["message"]


def test_make_plan_phase_multiple_extra_sorted():
    result = json.loads(make_plan([_phase(x_field=1, a_field=2)]))
    assert result["status"] == "error"
    assert "['a_field', 'x_field']" in result["message"]


def test_make_plan_extra_checked_before_missing():
    result = json.loads(make_plan([{"phase_id": "p1", "extra_field": 1}]))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "missing required" not in result["message"]


@pytest.mark.parametrize("phase_id", ["", "   ", 123, None, True])
def test_make_plan_phase_id_invalid(phase_id):
    result = json.loads(make_plan([_phase(phase_id=phase_id)]))
    assert result["status"] == "error"
    assert "phase_id must be a non-empty string" in result["message"]


@pytest.mark.parametrize("phase_name", ["", " ", 123, None])
def test_make_plan_phase_name_invalid(phase_name):
    result = json.loads(make_plan([_phase(phase_name=phase_name)]))
    assert result["status"] == "error"
    assert "phase_name must be a non-empty string" in result["message"]


@pytest.mark.parametrize("phase_description", ["", " ", 123, None])
def test_make_plan_phase_description_invalid(phase_description):
    result = json.loads(make_plan([_phase(phase_description=phase_description)]))
    assert result["status"] == "error"
    assert "phase_description must be a non-empty string" in result["message"]


@pytest.mark.parametrize("phase_status", [["pending"], {"a": 1}, 123, None, "donex", True])
def test_make_plan_phase_status_invalid(phase_status):
    result = json.loads(make_plan([_phase(phase_status=phase_status)]))
    assert result["status"] == "error"
    assert "phase_status must be one of" in result["message"]


@pytest.mark.parametrize("phase_status", ["pending", "in_progress", "done"])
def test_make_plan_phase_status_all_valid_values(phase_status):
    result = json.loads(make_plan([_phase(phase_status=phase_status)]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_status"] == phase_status


def test_make_plan_duplicate_phase_id_rejected():
    result = json.loads(make_plan([_phase(), _phase()]))
    assert result["status"] == "error"
    assert "duplicate phase_id: 'p1'" in result["message"]


def test_make_plan_duplicate_detected_after_strip():
    result = json.loads(make_plan([_phase(), _phase(phase_id=" p1 ")]))
    assert result["status"] == "error"
    assert "duplicate phase_id: 'p1'" in result["message"]


def test_make_plan_duplicate_case_sensitive():
    result = json.loads(make_plan([_phase(), _phase(phase_id="P1")]))
    assert result["status"] == "ok"
    assert len(result["plan"]) == 2


def test_make_plan_error_reports_phase_index():
    result = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_status="bad")]))
    assert result["status"] == "error"
    assert "phase[1]" in result["message"]


def test_make_plan_second_phase_error_localization():
    result = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="")]))
    assert result["status"] == "error"
    assert "phase[1]" in result["message"]
    assert "phase_name" in result["message"]


def test_make_plan_existing_plan_rejected():
    result = json.loads(make_plan([_phase()], existing_plan=[_phase(phase_id="old")]))
    assert result["status"] == "error"
    assert "already exists" in result["message"]


def test_make_plan_existing_plan_message_counts():
    result = json.loads(make_plan(
        [_phase()], existing_plan=[_phase(phase_id="a"), _phase(phase_id="b")]))
    assert result["status"] == "error"
    assert "already exists (2 phases)" in result["message"]


def test_make_plan_existing_plan_empty_list_allowed():
    result = json.loads(make_plan([_phase()], existing_plan=[]))
    assert result["status"] == "ok"


def test_make_plan_existing_plan_none_default():
    result = json.loads(make_plan([_phase()]))
    assert result["status"] == "ok"


@pytest.mark.parametrize("existing_plan", ["[{}]", {"a": 1}, 123])
def test_make_plan_existing_plan_type_invalid(existing_plan):
    result = json.loads(make_plan([_phase()], existing_plan=existing_plan))
    assert result["status"] == "error"
    assert "must be a list or None" in result["message"]


def test_make_plan_lifecycle_reject_while_plan_exists():
    first = json.loads(make_plan([_phase()]))
    result = json.loads(make_plan([_phase(phase_id="new")], existing_plan=first["plan"]))
    assert result["status"] == "error"
    assert "already exists" in result["message"]


def test_make_plan_lifecycle_recreate_after_delete_all():
    first = json.loads(make_plan([_phase()]))
    cleared = json.loads(delete_plan("p1", first["plan"], delete_all=True))
    result = json.loads(make_plan([_phase(phase_id="new")], existing_plan=cleared["plan"]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_id"] == "new"


def test_make_plan_lifecycle_make_edit_make_rejected():
    made = json.loads(make_plan([_phase()]))
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    assert edited["status"] == "ok"
    result = json.loads(make_plan([_phase(phase_id="new")], existing_plan=edited["plan"]))
    assert result["status"] == "error"
    assert "already exists" in result["message"]


def test_make_plan_lifecycle_make_delete_partial_then_recreate():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    partial = json.loads(delete_plan("p2", made["plan"]))
    assert [p["phase_id"] for p in partial["plan"]] == ["p1"]
    rejected = json.loads(make_plan([_phase(phase_id="new")], existing_plan=partial["plan"]))
    assert rejected["status"] == "error"
    cleared = json.loads(delete_plan("p1", partial["plan"]))
    assert cleared["plan"] == []
    recreated = json.loads(make_plan([_phase(phase_id="new")], existing_plan=cleared["plan"]))
    assert recreated["status"] == "ok"
    assert recreated["plan"][0]["phase_id"] == "new"


def test_make_plan_lifecycle_full_chain_rebuild():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    assert edited["plan"][0]["phase_status"] == "done"
    deleted = json.loads(delete_plan("p2", edited["plan"]))
    assert [p["phase_id"] for p in deleted["plan"]] == ["p1"]
    cleared = json.loads(delete_plan("p1", deleted["plan"], delete_all=True))
    assert cleared["plan"] == []
    rebuilt = json.loads(make_plan([_phase(phase_id="n1", phase_name="新计划")], existing_plan=cleared["plan"]))
    assert rebuilt["status"] == "ok"
    assert rebuilt["plan"][0]["phase_name"] == "新计划"


def test_make_plan_lifecycle_failed_edit_then_recreate():
    made = json.loads(make_plan([_phase()]))
    failed = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "bad"}], made["plan"]))
    assert failed["status"] == "error"
    deleted = json.loads(delete_plan("p1", made["plan"]))
    assert deleted["plan"] == []
    recreated = json.loads(make_plan([_phase(phase_id="new")], existing_plan=deleted["plan"]))
    assert recreated["status"] == "ok"
    assert recreated["plan"][0]["phase_id"] == "new"


def test_make_plan_lifecycle_mixed_input_formats():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    edited = json.loads(edit_plan(
        json.dumps([{"phase_id": "p2", "phase_status": "in_progress"}]), made["plan"]))
    assert edited["status"] == "ok"
    assert edited["plan"][1]["phase_status"] == "in_progress"
    deleted = json.loads(delete_plan("p2", edited["plan"]))
    assert deleted["status"] == "ok"
    assert [p["phase_id"] for p in deleted["plan"]] == ["p1"]
