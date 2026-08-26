"""Comprehensive tests for edit_plan: parameter validation, partial-update semantics, copy semantics, atomicity, existence validation and the lifecycle.

Test cases:
- test_edit_plan_update_name_success:                updating phase_name succeeds
- test_edit_plan_update_status_success:              updating phase_status succeeds
- test_edit_plan_update_description_success:         updating phase_description succeeds
- test_edit_plan_update_all_fields_success:          all three fields updated at once
- test_edit_plan_multiple_phases_updated:            one call updates multiple phases
- test_edit_plan_same_phase_multiple_updates:        multiple updates to the same phase apply in order with deduped count
- test_edit_plan_unupdated_fields_kept:              unpassed fields stay unchanged (partial update)
- test_edit_plan_original_plan_untouched:            copy semantics: the original plan is not modified
- test_edit_plan_update_id_with_spaces:              update phase_id matches after strip
- test_edit_plan_plan_id_with_spaces:                ids with spaces inside the plan also match
- test_edit_plan_values_stripped_on_store:           name/description stored after strip
- test_edit_plan_status_requires_exact_value:        exact status-set matching
- test_edit_plan_ok_message_lists_updated_ids:       ok message lists the updated ids
- test_edit_plan_ok_message_dedup_same_phase:        multiple updates to one phase are deduped in the message
- test_edit_plan_ok_message_order_matches_updates:   message id order matches the updates
- test_edit_plan_ok_response_contract:               ok response has only status/message/plan fields
- test_edit_plan_error_response_has_no_plan:         error response has no plan field
- test_edit_plan_updates_empty_list:                 an empty updates list is rejected
- test_edit_plan_updates_type_invalid:               parametrized: None/dict/int rejected
- test_edit_plan_updates_json_string_success:        JSON-string input succeeds
- test_edit_plan_updates_json_string_invalid:        parametrized: all forms of invalid JSON strings rejected
- test_edit_plan_update_element_type_invalid:        parametrized: non-dict elements rejected
- test_edit_plan_update_missing_phase_id:            an update without phase_id is rejected
- test_edit_plan_update_phase_id_invalid:            parametrized: empty/blank/non-str/None id rejected
- test_edit_plan_update_phase_id_only_rejected:      phase_id-only without update fields rejected
- test_edit_plan_update_extra_field_rejected:        extra fields rejected
- test_edit_plan_update_multiple_extra_sorted:       multiple extra fields listed sorted
- test_edit_plan_update_rename_id_rejected:          trying to rename phase_id itself rejected (phase_id_new is an extra field)
- test_edit_plan_update_non_string_key_rejected:     non-string keys rejected
- test_edit_plan_update_status_invalid:              parametrized: invalid status value/list/dict/int/None rejected
- test_edit_plan_update_status_message_format:       status error message format "one of [...]"
- test_edit_plan_update_name_invalid:                parametrized: empty/blank/non-str/None name rejected
- test_edit_plan_update_description_invalid:         parametrized: empty/blank/non-str/None desc rejected
- test_edit_plan_plan_none_rejected:                 plan=None rejected
- test_edit_plan_plan_empty_rejected:                an empty plan is rejected
- test_edit_plan_plan_non_list_rejected:             parametrized: plan as str/dict/int rejected
- test_edit_plan_plan_element_invalid:               parametrized: non-dict/missing-id/empty-id/non-str-id elements rejected
- test_edit_plan_phase_id_not_found:                 nonexistent phase_id rejected
- test_edit_plan_one_invalid_update_aborts_all:      atomicity: any invalid update fails the whole operation
- test_edit_plan_failed_update_plan_untouched:       the original plan is not modified after a failure
- test_edit_plan_error_index_localization:           error messages localize the updates[i] index
- test_edit_plan_lifecycle_make_then_edit:           lifecycle: edit succeeds after make
- test_edit_plan_lifecycle_edit_after_edit:          lifecycle: two consecutive edits build on the previous result
- test_edit_plan_lifecycle_edit_deleted_phase:       lifecycle: editing a deleted id after delete is refused
- test_edit_plan_lifecycle_edit_empty_after_delete_all: lifecycle: edit refused after clearing
- test_edit_plan_lifecycle_make_edit_full_flow:      lifecycle: make 3 phases → one edit with 2 updates
- test_edit_plan_lifecycle_make_edit_delete_edit_remaining: mixed: make → edit → delete → editing remaining succeeds/deleted refused
- test_edit_plan_lifecycle_atomic_failure_then_retry: mixed: atomic edit failure → fixed and retried successfully
- test_edit_plan_lifecycle_progress_all_phases:       mixed: multiple edit rounds advance all phases to done
- test_edit_plan_lifecycle_make_delete_edit_remaining: mixed: make → delete → editing remaining phases succeeds
- test_edit_plan_lifecycle_rebuild_chain:             mixed: make → edit → delete → clear → rebuild → edit new phases
- test_edit_plan_lifecycle_stale_snapshot_editable:   convention: stale snapshots are still editable (stateless tool, caller passes the latest plan)

Covered scenarios:
- Parameter validation: updates not a list (None/dict/int) and empty list rejected; non-dict elements (str/int/None/list) rejected; missing/invalid phase_id rejected; phase_id-only without update fields rejected; extra fields and phase_id_new whitelist rejected; non-string keys rejected (sorted crash protection); name/desc empty, blank, non-str, None rejected; exact status-set matching with unhashable inputs (list/dict/bool) rejected (message format one of [...])
- Input forms: updates supports dict lists and JSON strings; all invalid JSON forms (syntax error/parsed to dict/null/empty array) rejected
- Partial-update semantics: single/multi/three-field updates; multiple updates to one phase apply in order with deduped count; unpassed fields stay unchanged; message id order matches updates; name/description stored after strip
- Existence validation: plan None/empty/non-list/bad elements rejected (No plan exists semantics); nonexistent phase_id rejected; error messages localize the updates[i] index
- Copy semantics and atomicity: the original plan is never modified (neither on success nor failure); any invalid update fails the whole operation and legal parts do not take effect
- Lifecycle mixed chains: edit after make; consecutive edits advance state; edit of a deleted id after delete refused while remaining phases editable; edit refused after clearing; atomic failure retryable; edit new phases after rebuild; stale snapshots still editable (stateless snapshot convention)
"""

import json

import pytest

from core.tools._kernel._plan import delete_plan, edit_plan, make_plan
from tests.helpers import _phase, _plan2


def test_edit_plan_update_name_success():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "新阶段一"}], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "新阶段一"
    assert result["plan"][0]["phase_status"] == "pending"
    assert result["plan"][1] == _phase(phase_id="p2", phase_name="阶段二")


def test_edit_plan_update_status_success():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "in_progress"}], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_status"] == "in_progress"


def test_edit_plan_update_description_success():
    result = json.loads(edit_plan([{"phase_id": "p2", "phase_description": "新描述"}], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][1]["phase_description"] == "新描述"


def test_edit_plan_update_all_fields_success():
    update = {"phase_id": "p1", "phase_name": "新名", "phase_status": "done",
              "phase_description": "新描述"}
    result = json.loads(edit_plan([update], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "新名"
    assert result["plan"][0]["phase_status"] == "done"
    assert result["plan"][0]["phase_description"] == "新描述"


def test_edit_plan_multiple_phases_updated():
    result = json.loads(edit_plan([
        {"phase_id": "p1", "phase_status": "done"},
        {"phase_id": "p2", "phase_name": "阶段二改"},
    ], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_status"] == "done"
    assert result["plan"][1]["phase_name"] == "阶段二改"


def test_edit_plan_same_phase_multiple_updates():
    result = json.loads(edit_plan([
        {"phase_id": "p1", "phase_name": "改名"},
        {"phase_id": "p1", "phase_status": "done"},
    ], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "改名"
    assert result["plan"][0]["phase_status"] == "done"
    assert result["message"] == "Updated 1 phase(s): p1."


def test_edit_plan_unupdated_fields_kept():
    result = json.loads(edit_plan([{"phase_id": "p2", "phase_status": "in_progress"}], _plan2()))
    assert result["plan"][1]["phase_name"] == "阶段二"
    assert result["plan"][1]["phase_description"] == "描述一"


def test_edit_plan_original_plan_untouched():
    original = _plan2()
    edit_plan([{"phase_id": "p1", "phase_name": "改名"}], original)
    assert original[0]["phase_name"] == "阶段一"
    assert original == _plan2()


def test_edit_plan_update_id_with_spaces():
    result = json.loads(edit_plan([{"phase_id": " p1 ", "phase_name": "改名"}], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "改名"


def test_edit_plan_plan_id_with_spaces():
    plan = [_phase(phase_id=" p1 "), _phase(phase_id="p2", phase_name="阶段二")]
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "改名"}], plan))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "改名"


def test_edit_plan_values_stripped_on_store():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "  改名  ",
                                    "phase_description": "  新描述  "}], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "改名"
    assert result["plan"][0]["phase_description"] == "新描述"


def test_edit_plan_status_requires_exact_value():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_status": " done "}], _plan2()))
    assert result["status"] == "error"
    assert "phase_status must be one of" in result["message"]


def test_edit_plan_ok_message_lists_updated_ids():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "a"}], _plan2()))
    assert result["message"] == "Updated 1 phase(s): p1."


def test_edit_plan_ok_message_dedup_same_phase():
    result = json.loads(edit_plan([
        {"phase_id": "p1", "phase_name": "a"},
        {"phase_id": "p1", "phase_status": "done"},
    ], _plan2()))
    assert result["message"] == "Updated 1 phase(s): p1."


def test_edit_plan_ok_message_order_matches_updates():
    result = json.loads(edit_plan([
        {"phase_id": "p2", "phase_name": "a"},
        {"phase_id": "p1", "phase_status": "done"},
    ], _plan2()))
    assert result["message"] == "Updated 2 phase(s): p2, p1."


def test_edit_plan_ok_response_contract():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "a"}], _plan2()))
    assert set(result.keys()) == {"status", "message", "plan"}


def test_edit_plan_error_response_has_no_plan():
    result = json.loads(edit_plan([{"phase_id": "nope", "phase_name": "a"}], _plan2()))
    assert result["status"] == "error"
    assert "plan" not in result


def test_edit_plan_updates_empty_list():
    result = json.loads(edit_plan([], _plan2()))
    assert result["status"] == "error"
    assert "non-empty list" in result["message"]


@pytest.mark.parametrize("updates", [None, {"a": 1}, 123])
def test_edit_plan_updates_type_invalid(updates):
    result = json.loads(edit_plan(updates, _plan2()))
    assert result["status"] == "error"
    assert "non-empty list" in result["message"]


def test_edit_plan_updates_json_string_success():
    result = json.loads(edit_plan(json.dumps([{"phase_id": "p1", "phase_name": "改名"}]), _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "改名"


@pytest.mark.parametrize("updates, expected", [
    ("not json", "Invalid updates: not a JSON string"),
    ("{bad", "Invalid updates: not a JSON string"),
    ("null", "non-empty list"),
    ("{}", "non-empty list"),
    ("[]", "non-empty list"),
])
def test_edit_plan_updates_json_string_invalid(updates, expected):
    result = json.loads(edit_plan(updates, _plan2()))
    assert result["status"] == "error"
    assert expected in result["message"]


@pytest.mark.parametrize("update", ["x", 123, None, [1]])
def test_edit_plan_update_element_type_invalid(update):
    result = json.loads(edit_plan([update], _plan2()))
    assert result["status"] == "error"
    assert "must be a dict" in result["message"]


def test_edit_plan_update_missing_phase_id():
    result = json.loads(edit_plan([{"phase_name": "x"}], _plan2()))
    assert result["status"] == "error"
    assert "missing 'phase_id'" in result["message"]


@pytest.mark.parametrize("phase_id", ["", "   ", 123, None])
def test_edit_plan_update_phase_id_invalid(phase_id):
    result = json.loads(edit_plan([{"phase_id": phase_id, "phase_name": "x"}], _plan2()))
    assert result["status"] == "error"
    assert "phase_id must be a non-empty string" in result["message"]


def test_edit_plan_update_phase_id_only_rejected():
    result = json.loads(edit_plan([{"phase_id": "p1"}], _plan2()))
    assert result["status"] == "error"
    assert "no fields to update" in result["message"]


def test_edit_plan_update_extra_field_rejected():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_extra": 1}], _plan2()))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "phase_extra" in result["message"]


def test_edit_plan_update_multiple_extra_sorted():
    result = json.loads(edit_plan([{"phase_id": "p1", "z_field": 1, "a_field": 2}], _plan2()))
    assert result["status"] == "error"
    assert "['a_field', 'z_field']" in result["message"]


def test_edit_plan_update_rename_id_rejected():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_id_new": "p9"}], _plan2()))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "phase_id_new" in result["message"]


def test_edit_plan_update_non_string_key_rejected():
    result = json.loads(edit_plan([{"phase_id": "p1", 1: "x"}], _plan2()))
    assert result["status"] == "error"
    assert "keys must be strings" in result["message"]


@pytest.mark.parametrize("phase_status", [["done"], {"a": 1}, 123, None, "donex", True])
def test_edit_plan_update_status_invalid(phase_status):
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_status": phase_status}], _plan2()))
    assert result["status"] == "error"
    assert "phase_status must be one of" in result["message"]


def test_edit_plan_update_status_message_format():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "xxx"}], _plan2()))
    assert result["status"] == "error"
    assert "one of ['done', 'in_progress', 'pending'], got 'xxx'" in result["message"]


@pytest.mark.parametrize("phase_name", ["", " ", 123, None])
def test_edit_plan_update_name_invalid(phase_name):
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": phase_name}], _plan2()))
    assert result["status"] == "error"
    assert "phase_name must be a non-empty string" in result["message"]


@pytest.mark.parametrize("phase_description", ["", " ", 123, None])
def test_edit_plan_update_description_invalid(phase_description):
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_description": phase_description}], _plan2()))
    assert result["status"] == "error"
    assert "phase_description must be a non-empty string" in result["message"]


def test_edit_plan_plan_none_rejected():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], None))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


def test_edit_plan_plan_empty_rejected():
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], []))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


@pytest.mark.parametrize("plan", ["[{}]", {"a": 1}, 123])
def test_edit_plan_plan_non_list_rejected(plan):
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], plan))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


@pytest.mark.parametrize("plan", [["abc"], [{"phase_name": "x"}], [{"phase_id": "  "}], [{"phase_id": 1}]])
def test_edit_plan_plan_element_invalid(plan):
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], plan))
    assert result["status"] == "error"
    assert "plan[0] must be a dict with a non-empty string phase_id" in result["message"]


def test_edit_plan_phase_id_not_found():
    result = json.loads(edit_plan([{"phase_id": "nope", "phase_name": "x"}], _plan2()))
    assert result["status"] == "error"
    assert "phase_id 'nope' not found in plan" in result["message"]


def test_edit_plan_one_invalid_update_aborts_all():
    original = _plan2()
    result = json.loads(edit_plan([
        {"phase_id": "p1", "phase_name": "合法改名"},
        {"phase_id": "nope", "phase_name": "非法"},
    ], original))
    assert result["status"] == "error"
    assert "not found" in result["message"]
    assert "plan" not in result
    assert original == _plan2()


def test_edit_plan_failed_update_plan_untouched():
    original = _plan2()
    edit_plan([{"phase_id": "p1", "phase_status": "bad"}], original)
    assert original == _plan2()


def test_edit_plan_error_index_localization():
    result = json.loads(edit_plan([
        {"phase_id": "p1", "phase_name": "a"},
        {"phase_id": "p2", "phase_status": "bad"},
    ], _plan2()))
    assert result["status"] == "error"
    assert "updates[1]" in result["message"]


def test_edit_plan_lifecycle_make_then_edit():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    result = json.loads(edit_plan([{"phase_id": "p2", "phase_status": "in_progress"}], made["plan"]))
    assert result["status"] == "ok"
    assert result["plan"][1]["phase_status"] == "in_progress"


def test_edit_plan_lifecycle_edit_after_edit():
    made = json.loads(make_plan([_phase()]))
    once = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "in_progress"}], made["plan"]))
    twice = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], once["plan"]))
    assert twice["status"] == "ok"
    assert twice["plan"][0]["phase_status"] == "done"


def test_edit_plan_lifecycle_edit_deleted_phase():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    deleted = json.loads(delete_plan("p2", made["plan"]))
    result = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "x"}], deleted["plan"]))
    assert result["status"] == "error"
    assert "not found" in result["message"]


def test_edit_plan_lifecycle_edit_empty_after_delete_all():
    made = json.loads(make_plan([_phase()]))
    cleared = json.loads(delete_plan("p1", made["plan"], delete_all=True))
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], cleared["plan"]))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


def test_edit_plan_lifecycle_make_edit_full_flow():
    made = json.loads(make_plan([
        _phase(), _phase(phase_id="p2", phase_name="阶段二"), _phase(phase_id="p3", phase_name="阶段三")]))
    result = json.loads(edit_plan([
        {"phase_id": "p1", "phase_status": "done"},
        {"phase_id": "p3", "phase_name": "阶段三改"},
    ], made["plan"]))
    assert result["status"] == "ok"
    assert result["message"] == "Updated 2 phase(s): p1, p3."
    assert result["plan"][0]["phase_status"] == "done"
    assert result["plan"][2]["phase_name"] == "阶段三改"
    assert result["plan"][1] == _phase(phase_id="p2", phase_name="阶段二")


def test_edit_plan_lifecycle_make_edit_delete_edit_remaining():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二"),
                                 _phase(phase_id="p3", phase_name="阶段三")]))
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    deleted = json.loads(delete_plan("p2", edited["plan"]))
    gone = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "x"}], deleted["plan"]))
    assert gone["status"] == "error"
    assert "not found" in gone["message"]
    result = json.loads(edit_plan([{"phase_id": "p3", "phase_status": "in_progress"}], deleted["plan"]))
    assert result["status"] == "ok"
    assert result["plan"][1]["phase_status"] == "in_progress"


def test_edit_plan_lifecycle_atomic_failure_then_retry():
    made = json.loads(make_plan([_phase()]))
    failed = json.loads(edit_plan([
        {"phase_id": "p1", "phase_name": "改名"},
        {"phase_id": "nope", "phase_name": "非法"},
    ], made["plan"]))
    assert failed["status"] == "error"
    assert made["plan"][0]["phase_name"] == "阶段一"
    retried = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "改名"}], made["plan"]))
    assert retried["status"] == "ok"
    assert retried["plan"][0]["phase_name"] == "改名"


def test_edit_plan_lifecycle_progress_all_phases():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    round1 = json.loads(edit_plan([
        {"phase_id": "p1", "phase_status": "in_progress"},
        {"phase_id": "p2", "phase_status": "in_progress"},
    ], made["plan"]))
    assert round1["status"] == "ok"
    round2 = json.loads(edit_plan([
        {"phase_id": "p1", "phase_status": "done"},
        {"phase_id": "p2", "phase_status": "done"},
    ], round1["plan"]))
    assert round2["status"] == "ok"
    assert round2["message"] == "Updated 2 phase(s): p1, p2."
    assert [p["phase_status"] for p in round2["plan"]] == ["done", "done"]


def test_edit_plan_lifecycle_make_delete_edit_remaining():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    deleted = json.loads(delete_plan("p2", made["plan"]))
    assert deleted["status"] == "ok"
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], deleted["plan"]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_status"] == "done"
    assert result["message"] == "Updated 1 phase(s): p1."


def test_edit_plan_lifecycle_rebuild_chain():
    made = json.loads(make_plan([_phase()]))
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    cleared = json.loads(delete_plan("p1", edited["plan"], delete_all=True))
    rebuilt = json.loads(make_plan([_phase(phase_id="n1", phase_name="新计划")], existing_plan=cleared["plan"]))
    assert rebuilt["status"] == "ok"
    result = json.loads(edit_plan([{"phase_id": "n1", "phase_status": "in_progress"}], rebuilt["plan"]))
    assert result["status"] == "ok"
    assert result["message"] == "Updated 1 phase(s): n1."
    assert result["plan"][0]["phase_status"] == "in_progress"


def test_edit_plan_lifecycle_stale_snapshot_editable():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    deleted = json.loads(delete_plan("p2", made["plan"]))
    assert [p["phase_id"] for p in deleted["plan"]] == ["p1"]
    stale = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "旧快照改名"}], made["plan"]))
    assert stale["status"] == "ok"
    assert stale["plan"][1]["phase_name"] == "旧快照改名"
    fresh = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "x"}], deleted["plan"]))
    assert fresh["status"] == "error"
    assert "not found" in fresh["message"]
