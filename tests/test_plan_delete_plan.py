"""Comprehensive tests for delete_plan: deletion semantics, delete_all type protection, copy semantics, existence validation and the full lifecycle.

Test cases:
- test_delete_plan_single_phase:                     deleting a single phase succeeds
- test_delete_plan_middle_phase_order_kept:          deleting a middle phase keeps the order
- test_delete_plan_last_remaining_phase:             deleting the last phase leaves an empty plan
- test_delete_plan_id_with_spaces:                   phase_id matches after strip for deletion
- test_delete_plan_plan_id_with_spaces:              ids with spaces inside the plan can also be deleted
- test_delete_plan_message_reports_id:               ok message reports the deleted id
- test_delete_plan_original_plan_untouched:          copy semantics: the original plan is not modified
- test_delete_plan_remaining_phases_intact:          remaining phases keep all fields intact
- test_delete_plan_duplicate_ids_all_removed:        duplicate ids in a hand-built plan are all deleted
- test_delete_plan_delete_all_clears:                delete_all clears all phases
- test_delete_plan_delete_all_empty_plan_idempotent: delete_all on an empty plan is idempotent
- test_delete_plan_delete_all_ignores_phase_id:      phase_id is ignored when delete_all is set
- test_delete_plan_delete_all_message:               clear message is "All phases deleted."
- test_delete_plan_delete_all_response_contract:     clear response has an empty plan list
- test_delete_plan_delete_all_string_false_rejected: delete_all="false" rejected (prevents accidental clearing)
- test_delete_plan_delete_all_string_true_rejected:  delete_all="True" rejected
- test_delete_plan_delete_all_int_rejected:          parametrized: delete_all=1/0 rejected
- test_delete_plan_delete_all_none_rejected:         delete_all=None rejected
- test_delete_plan_delete_all_list_rejected:         delete_all=[] rejected
- test_delete_plan_delete_all_non_bool_error_first:  non-bool errors first and performs no deletion
- test_delete_plan_phase_id_invalid:                 parametrized: empty/blank/non-str/None/bool id rejected
- test_delete_plan_plan_none_rejected:               plan=None rejected
- test_delete_plan_plan_non_list_rejected:           parametrized: plan as str/dict/int rejected
- test_delete_plan_plan_empty_rejected:              empty plan rejected (make_plan required first)
- test_delete_plan_plan_element_invalid:             parametrized: non-dict/missing-id/empty-id/non-str-id elements rejected
- test_delete_plan_delete_all_plan_non_list_rejected: plan not a list also rejected under delete_all (prevents false clear claims)
- test_delete_plan_delete_all_plan_bad_element_clears: bad elements in the plan can still be cleared under delete_all (element validation skipped)
- test_delete_plan_not_found:                        nonexistent phase_id rejected
- test_delete_plan_not_found_plan_untouched:         the original plan is not modified on not found
- test_delete_plan_error_response_has_no_plan:       error response has no plan field
- test_delete_plan_ok_response_contract:             ok response has only status/message/plan fields
- test_delete_plan_lifecycle_make_delete_recreate:   lifecycle: make → delete single phase → re-make
- test_delete_plan_lifecycle_delete_twice_not_found: lifecycle: deleting the same id twice, second refused
- test_delete_plan_lifecycle_make_edit_delete_edit:  lifecycle: make → edit → delete → editing the deleted id refused
- test_delete_plan_lifecycle_delete_all_then_make:   lifecycle: re-make succeeds after delete_all
- test_delete_plan_lifecycle_full_flow:              lifecycle: make → edit → delete → clear → rebuild → edit
- test_delete_plan_lifecycle_delete_all_then_edit:   lifecycle: edit refused after clearing
- test_delete_plan_lifecycle_delete_all_then_delete: lifecycle: delete refused after clearing
- test_delete_plan_lifecycle_make_edit_delete_delete_again: mixed: make → edit → delete → deleting the same id again refused
- test_delete_plan_lifecycle_edit_failed_then_delete: mixed: edit failed (atomicity) → delete still works
- test_delete_plan_lifecycle_delete_then_edit_remaining: mixed: delete → editing remaining succeeds, editing deleted refused (comparison)
- test_delete_plan_lifecycle_delete_until_empty_then_error: mixed: delete one by one until empty → further delete reports No plan exists
- test_delete_plan_lifecycle_stale_snapshot_deletable: convention: stale snapshots are still deletable; the latest snapshot must be passed to make
- test_delete_plan_lifecycle_delete_view_full_chain:  mixed full chain: make → edit → delete → edit refused → clear → rebuild → delete

Covered scenarios:
- Parameter validation: phase_id empty/blank/non-str/None/bool rejected; plan None/non-list/empty/bad elements rejected (No plan exists semantics); error message reports the not-found id
- delete_all protection: True clears (phase_id ignored, bad-element plans still clearable, message All phases deleted.); "false"/"True"/1/0/None/[] etc. non-strict-bool all rejected (prevents accidental clearing); non-bool errors first and performs no deletion; plan not a list rejects false clear claims
- Deletion semantics: single/middle/last phase deletion; remaining order kept; duplicate ids all deleted; both id and plan ids matched after strip; remaining phases keep fields; message reports the deleted id
- Copy semantics: the original plan is not modified after deletion; not modified on not found either
- Response contract: ok has only status/message/plan fields; error has no plan
- Lifecycle mixed chains: make → delete to empty → rebuild; second consecutive delete not found; delete then edit remaining succeeds/deleted refused; edit failure does not block delete; deleting one by one to empty then error; edit/delete refused after clearing; stale snapshots still deletable (stateless convention); make → edit → delete → clear → rebuild → edit/delete full loop
"""

import json

import pytest

from core.tools._kernel._plan import delete_plan, edit_plan, make_plan
from tests.helpers import _phase, _plan3


def test_delete_plan_single_phase():
    result = json.loads(delete_plan("p2", _plan3()))
    assert result["status"] == "ok"
    assert [p["phase_id"] for p in result["plan"]] == ["p1", "p3"]


def test_delete_plan_middle_phase_order_kept():
    result = json.loads(delete_plan("p2", _plan3()))
    assert result["plan"][0]["phase_id"] == "p1"
    assert result["plan"][1]["phase_id"] == "p3"


def test_delete_plan_last_remaining_phase():
    result = json.loads(delete_plan("p1", [_phase()]))
    assert result["status"] == "ok"
    assert result["plan"] == []


def test_delete_plan_id_with_spaces():
    result = json.loads(delete_plan(" p2 ", _plan3()))
    assert result["status"] == "ok"
    assert [p["phase_id"] for p in result["plan"]] == ["p1", "p3"]


def test_delete_plan_plan_id_with_spaces():
    plan = [_phase(phase_id=" p1 "), _phase(phase_id="p2", phase_name="阶段二")]
    result = json.loads(delete_plan("p1", plan))
    assert result["status"] == "ok"
    assert [p["phase_id"] for p in result["plan"]] == ["p2"]


def test_delete_plan_message_reports_id():
    result = json.loads(delete_plan("p2", _plan3()))
    assert result["message"] == "Phase 'p2' deleted."


def test_delete_plan_original_plan_untouched():
    original = _plan3()
    delete_plan("p2", original)
    assert original == _plan3()


def test_delete_plan_remaining_phases_intact():
    result = json.loads(delete_plan("p2", _plan3()))
    assert result["plan"][0] == _phase()
    assert result["plan"][1] == _phase(phase_id="p3", phase_name="阶段三")


def test_delete_plan_duplicate_ids_all_removed():
    plan = [_phase(), _phase(), _phase(phase_id="p2", phase_name="阶段二")]
    result = json.loads(delete_plan("p1", plan))
    assert result["status"] == "ok"
    assert [p["phase_id"] for p in result["plan"]] == ["p2"]


def test_delete_plan_delete_all_clears():
    result = json.loads(delete_plan("p1", _plan3(), delete_all=True))
    assert result["status"] == "ok"
    assert result["plan"] == []


def test_delete_plan_delete_all_empty_plan_idempotent():
    result = json.loads(delete_plan("p1", [], delete_all=True))
    assert result["status"] == "ok"
    assert result["plan"] == []


def test_delete_plan_delete_all_ignores_phase_id():
    result = json.loads(delete_plan(123, _plan3(), delete_all=True))
    assert result["status"] == "ok"
    assert result["plan"] == []


def test_delete_plan_delete_all_message():
    result = json.loads(delete_plan("p1", _plan3(), delete_all=True))
    assert result["message"] == "All phases deleted."


def test_delete_plan_delete_all_response_contract():
    result = json.loads(delete_plan("p1", _plan3(), delete_all=True))
    assert set(result.keys()) == {"status", "message", "plan"}
    assert result["plan"] == []


def test_delete_plan_delete_all_string_false_rejected():
    result = json.loads(delete_plan("p1", _plan3(), delete_all="false"))
    assert result["status"] == "error"
    assert "delete_all must be a boolean" in result["message"]


def test_delete_plan_delete_all_string_true_rejected():
    result = json.loads(delete_plan("p1", _plan3(), delete_all="True"))
    assert result["status"] == "error"
    assert "delete_all must be a boolean" in result["message"]


@pytest.mark.parametrize("delete_all", [1, 0])
def test_delete_plan_delete_all_int_rejected(delete_all):
    result = json.loads(delete_plan("p1", _plan3(), delete_all=delete_all))
    assert result["status"] == "error"
    assert "delete_all must be a boolean" in result["message"]


def test_delete_plan_delete_all_none_rejected():
    result = json.loads(delete_plan("p1", _plan3(), delete_all=None))
    assert result["status"] == "error"
    assert "delete_all must be a boolean" in result["message"]


def test_delete_plan_delete_all_list_rejected():
    result = json.loads(delete_plan("p1", _plan3(), delete_all=[]))
    assert result["status"] == "error"
    assert "delete_all must be a boolean" in result["message"]


def test_delete_plan_delete_all_non_bool_error_first():
    plan = _plan3()
    result = json.loads(delete_plan("p2", plan, delete_all="false"))
    assert result["status"] == "error"
    assert [p["phase_id"] for p in plan] == ["p1", "p2", "p3"]


@pytest.mark.parametrize("phase_id", ["", "   ", 123, None, True])
def test_delete_plan_phase_id_invalid(phase_id):
    result = json.loads(delete_plan(phase_id, _plan3()))
    assert result["status"] == "error"
    assert "phase_id must be a non-empty string" in result["message"]


def test_delete_plan_plan_none_rejected():
    result = json.loads(delete_plan("p1", None))
    assert result["status"] == "error"
    assert "plan must be a list" in result["message"]


@pytest.mark.parametrize("plan", ["[{}]", {"a": 1}, 123])
def test_delete_plan_plan_non_list_rejected(plan):
    result = json.loads(delete_plan("p1", plan))
    assert result["status"] == "error"
    assert "plan must be a list" in result["message"]


def test_delete_plan_plan_empty_rejected():
    result = json.loads(delete_plan("p1", []))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


@pytest.mark.parametrize("plan", [["abc"], [{"phase_name": "x"}], [{"phase_id": "  "}], [{"phase_id": 1}]])
def test_delete_plan_plan_element_invalid(plan):
    result = json.loads(delete_plan("p1", plan))
    assert result["status"] == "error"
    assert "plan[0] must be a dict with a non-empty string phase_id" in result["message"]


def test_delete_plan_delete_all_plan_non_list_rejected():
    result = json.loads(delete_plan("p1", "garbage", delete_all=True))
    assert result["status"] == "error"
    assert "plan must be a list" in result["message"]


def test_delete_plan_delete_all_plan_bad_element_clears():
    result = json.loads(delete_plan("p1", [123, "abc"], delete_all=True))
    assert result["status"] == "ok"
    assert result["plan"] == []


def test_delete_plan_not_found():
    result = json.loads(delete_plan("nope", _plan3()))
    assert result["status"] == "error"
    assert "phase_id 'nope' not found in plan" in result["message"]


def test_delete_plan_not_found_plan_untouched():
    original = _plan3()
    delete_plan("nope", original)
    assert original == _plan3()


def test_delete_plan_error_response_has_no_plan():
    result = json.loads(delete_plan("nope", _plan3()))
    assert result["status"] == "error"
    assert "plan" not in result


def test_delete_plan_ok_response_contract():
    result = json.loads(delete_plan("p2", _plan3()))
    assert set(result.keys()) == {"status", "message", "plan"}


def test_delete_plan_lifecycle_make_delete_recreate():
    made = json.loads(make_plan([_phase()]))
    deleted = json.loads(delete_plan("p1", made["plan"]))
    assert deleted["plan"] == []
    recreated = json.loads(make_plan([_phase(phase_id="new")], existing_plan=deleted["plan"]))
    assert recreated["status"] == "ok"
    assert recreated["plan"][0]["phase_id"] == "new"


def test_delete_plan_lifecycle_delete_twice_not_found():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    first = json.loads(delete_plan("p1", made["plan"]))
    assert first["status"] == "ok"
    second = json.loads(delete_plan("p1", first["plan"]))
    assert second["status"] == "error"
    assert "not found" in second["message"]


def test_delete_plan_lifecycle_make_edit_delete_edit():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    deleted = json.loads(delete_plan("p2", edited["plan"]))
    result = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "x"}], deleted["plan"]))
    assert result["status"] == "error"
    assert "not found" in result["message"]
    assert deleted["plan"][0]["phase_status"] == "done"


def test_delete_plan_lifecycle_delete_all_then_make():
    made = json.loads(make_plan([_phase()]))
    cleared = json.loads(delete_plan("p1", made["plan"], delete_all=True))
    recreated = json.loads(make_plan([_phase(phase_id="new")], existing_plan=cleared["plan"]))
    assert recreated["status"] == "ok"
    assert recreated["plan"][0]["phase_id"] == "new"


def test_delete_plan_lifecycle_full_flow():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二"),
                                 _phase(phase_id="p3", phase_name="阶段三")]))
    assert made["status"] == "ok"
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    assert edited["plan"][0]["phase_status"] == "done"
    deleted = json.loads(delete_plan("p2", edited["plan"]))
    assert [p["phase_id"] for p in deleted["plan"]] == ["p1", "p3"]
    cleared = json.loads(delete_plan("p1", deleted["plan"], delete_all=True))
    assert cleared["plan"] == []
    rebuilt = json.loads(make_plan([_phase(phase_id="n1", phase_name="新计划")], existing_plan=cleared["plan"]))
    assert rebuilt["status"] == "ok"
    final = json.loads(edit_plan([{"phase_id": "n1", "phase_status": "in_progress"}], rebuilt["plan"]))
    assert final["status"] == "ok"
    assert final["plan"][0]["phase_status"] == "in_progress"


def test_delete_plan_lifecycle_delete_all_then_edit():
    made = json.loads(make_plan([_phase()]))
    cleared = json.loads(delete_plan("p1", made["plan"], delete_all=True))
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], cleared["plan"]))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


def test_delete_plan_lifecycle_delete_all_then_delete():
    made = json.loads(make_plan([_phase()]))
    cleared = json.loads(delete_plan("p1", made["plan"], delete_all=True))
    result = json.loads(delete_plan("p1", cleared["plan"]))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


def test_delete_plan_lifecycle_make_edit_delete_delete_again():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    first = json.loads(delete_plan("p1", edited["plan"]))
    assert first["status"] == "ok"
    assert first["message"] == "Phase 'p1' deleted."
    second = json.loads(delete_plan("p1", first["plan"]))
    assert second["status"] == "error"
    assert "not found" in second["message"]


def test_delete_plan_lifecycle_edit_failed_then_delete():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    failed = json.loads(edit_plan([{"phase_id": "p2", "phase_status": "bad"}], made["plan"]))
    assert failed["status"] == "error"
    deleted = json.loads(delete_plan("p2", made["plan"]))
    assert deleted["status"] == "ok"
    assert [p["phase_id"] for p in deleted["plan"]] == ["p1"]


def test_delete_plan_lifecycle_delete_then_edit_remaining():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二"),
                                 _phase(phase_id="p3", phase_name="阶段三")]))
    deleted = json.loads(delete_plan("p2", made["plan"]))
    ok = json.loads(edit_plan([
        {"phase_id": "p1", "phase_status": "done"},
        {"phase_id": "p3", "phase_status": "in_progress"},
    ], deleted["plan"]))
    assert ok["status"] == "ok"
    assert ok["message"] == "Updated 2 phase(s): p1, p3."
    gone = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "x"}], deleted["plan"]))
    assert gone["status"] == "error"
    assert "not found" in gone["message"]


def test_delete_plan_lifecycle_delete_until_empty_then_error():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    once = json.loads(delete_plan("p1", made["plan"]))
    assert once["status"] == "ok"
    twice = json.loads(delete_plan("p2", once["plan"]))
    assert twice["status"] == "ok"
    assert twice["plan"] == []
    third = json.loads(delete_plan("p1", twice["plan"]))
    assert third["status"] == "error"
    assert "No plan exists" in third["message"]


def test_delete_plan_lifecycle_stale_snapshot_deletable():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    deleted = json.loads(delete_plan("p2", made["plan"]))
    assert [p["phase_id"] for p in deleted["plan"]] == ["p1"]
    # 旧快照（make 的结果）中 p2 仍存在，基于旧快照删除 p2 仍成功且结果一致
    stale = json.loads(delete_plan("p2", made["plan"]))
    assert stale["status"] == "ok"
    assert [p["phase_id"] for p in stale["plan"]] == ["p1"]
    # 旧快照传给 make 仍被视为已有计划 → 拒绝；必须传清空后的最新快照
    rejected = json.loads(make_plan([_phase(phase_id="new")], existing_plan=made["plan"]))
    assert rejected["status"] == "error"
    # 最新快照仍含 p1（非空），make 同样拒绝；清空后才放行
    still_nonempty = json.loads(make_plan([_phase(phase_id="new")], existing_plan=deleted["plan"]))
    assert still_nonempty["status"] == "error"
    emptied = json.loads(delete_plan("p1", deleted["plan"]))
    assert emptied["plan"] == []
    recreated = json.loads(make_plan([_phase(phase_id="new")], existing_plan=emptied["plan"]))
    assert recreated["status"] == "ok"


def test_delete_plan_lifecycle_delete_view_full_chain():
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    deleted = json.loads(delete_plan("p2", edited["plan"]))
    assert [p["phase_id"] for p in deleted["plan"]] == ["p1"]
    edit_gone = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "x"}], deleted["plan"]))
    assert edit_gone["status"] == "error"
    cleared = json.loads(delete_plan("p1", deleted["plan"], delete_all=True))
    assert cleared["plan"] == []
    rebuilt = json.loads(make_plan([_phase(phase_id="n1", phase_name="新计划")], existing_plan=cleared["plan"]))
    assert rebuilt["status"] == "ok"
    final = json.loads(delete_plan("n1", rebuilt["plan"]))
    assert final["status"] == "ok"
    assert final["plan"] == []
    assert final["message"] == "Phase 'n1' deleted."
