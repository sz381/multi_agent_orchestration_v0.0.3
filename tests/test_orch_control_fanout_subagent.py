"""Comprehensive tests for fanout_subagents: parameter validation, the field whitelist, dedup semantics, prefix validation and the response contract.

Test cases:
- test_fanout_single_task_success:                        single-task success with an exact clean-structure assertion
- test_fanout_multiple_tasks_order_kept:                  multiple tasks keep input order
- test_fanout_project_dir_kept_stripped:                  project_dir is kept with leading/trailing whitespace removed
- test_fanout_project_dir_blank_dropped:                  empty/blank project_dir drops the field
- test_fanout_max_tasks_boundary:                         20 tasks (MAX_TASKS upper boundary) succeed
- test_fanout_exceed_max_tasks:                           21 tasks over the limit are rejected
- test_fanout_tasks_json_string_success:                  tasks as a JSON string creates successfully
- test_fanout_tasks_type_invalid:                         parametrized: dict/int/None/bool rejected
- test_fanout_tasks_empty_list:                           an empty list is rejected
- test_fanout_tasks_json_invalid:                         parametrized: all forms of invalid JSON strings rejected
- test_fanout_element_type_invalid:                       parametrized: list/int/None/bool/str elements rejected
- test_fanout_missing_fields:                             parametrized: any missing required field rejected
- test_fanout_missing_multiple_reported:                  all missing fields are listed
- test_fanout_unknown_field_rejected:                     extra fields rejected
- test_fanout_multiple_extra_sorted:                      multiple extra fields listed sorted
- test_fanout_extra_checked_before_missing:               extra check takes priority over missing
- test_fanout_task_id_invalid:                            parametrized: empty/blank/non-str/None/bool id rejected
- test_fanout_duplicate_task_id_rejected:                 fully duplicated task_id rejected
- test_fanout_duplicate_task_id_after_strip:              duplicated task_id after strip rejected
- test_fanout_task_id_case_sensitive:                     different cases are not duplicates
- test_fanout_strips_text_fields:                         task_id/name/desc/subagent_name stored after strip
- test_fanout_task_name_invalid:                          parametrized: empty/blank/non-str/None name rejected
- test_fanout_task_description_invalid:                   parametrized: empty/blank/non-str/None desc rejected
- test_fanout_completion_status_invalid:                  parametrized: all non-False forms rejected
- test_fanout_subagent_id_invalid:                        parametrized: empty/blank/non-str/None/bool id rejected
- test_fanout_subagent_id_stripped_stored:                subagent_id stored after strip
- test_fanout_subagent_prefix_invalid:                    parametrized: invalid prefix/no underscore/empty prefix rejected
- test_fanout_prefix_valid:                               parametrized: all three legal prefixes pass
- test_fanout_subagent_id_prefix_only_allowed:            prefix-only without suffix passes
- test_fanout_subagent_name_invalid:                      parametrized: empty/blank/non-str/None name rejected
- test_fanout_duplicate_subagent_id_rejected:             duplicated subagent_id in one round rejected
- test_fanout_duplicate_subagent_id_after_strip:          duplicated subagent_id after strip rejected
- test_fanout_project_dir_invalid:                        parametrized: non-str project_dir rejected
- test_fanout_current_tasks_rejected:                     non-empty current_tasks rejected (prevents last-win)
- test_fanout_current_tasks_none_default:                 None default passes
- test_fanout_current_tasks_empty_list_allowed:           an empty list passes
- test_fanout_current_tasks_priority:                     call-level guard takes priority over parameter validation
- test_fanout_ok_message_reports_count:                   ok message reports the task count
- test_fanout_error_localization_index:                   error messages localize the task[i] index
- test_fanout_ok_response_contract:                       ok response has only status/message/tasks fields
- test_fanout_error_response_has_no_tasks:                error response has no tasks field
- test_fanout_chinese_not_escaped:                        ensure_ascii=False emits Chinese directly
- test_fanout_lifecycle_turn_semantics:                   turn semantics: a second call after success is rejected

Covered scenarios:
- Parameter validation: tasks not a list (dict/int/None/bool) and empty list rejected; JSON-string compatibility (including all invalid JSON forms); non-dict elements rejected
- Field whitelist: missing/extra field validation (full allowed list reported); task_id/name/desc/subagent_name empty, blank, non-str, None rejected; task_completion_status only exactly False passes; project_dir optional and non-str rejected
- Dedup semantics: fully duplicated and duplicated-after-strip both rejected; case-sensitive, no dedup across cases; subagent_id unique per round (one task per subagent)
- Prefix validation: programmer/reviewer/researcher legal (checked after strip); invalid prefix/no underscore/empty prefix rejected; prefix-only without suffix passes
- Normalization: task_id/name/desc/subagent_name/project_dir/subagent_id stored with leading/trailing whitespace removed
- Response contract: ok has only status/message/tasks (cleaned list); error has no tasks; message reports the task count; Chinese emitted directly with ensure_ascii=False
- Call-level guard: non-empty current_tasks rejected (priority over parameter validation); None/[] pass; turn semantics simulated
"""

import json

import pytest

from core.tools._kernel._orch_control import fanout_subagents
from core.tools._kernel.constants import MAX_TASKS
from tests.helpers import _ok_tasks, _task


def test_fanout_single_task_success():
    result = json.loads(fanout_subagents([_task()]))
    assert result["status"] == "ok"
    assert result["tasks"] == [_task()]


def test_fanout_multiple_tasks_order_kept():
    tasks = [_task(), _task(task_id="t2", subagent_id="reviewer_b")]
    result = json.loads(fanout_subagents(tasks))
    assert result["status"] == "ok"
    assert [t["task_id"] for t in result["tasks"]] == ["t1", "t2"]
    assert result["tasks"] == tasks


def test_fanout_project_dir_kept_stripped():
    result = json.loads(fanout_subagents([_task(project_dir="  /tmp/x  ")]))
    assert result["status"] == "ok"
    assert result["tasks"][0]["project_dir"] == "/tmp/x"


def test_fanout_project_dir_blank_dropped():
    result = json.loads(fanout_subagents([_task(project_dir="   ")]))
    assert result["status"] == "ok"
    assert "project_dir" not in result["tasks"][0]


def test_fanout_max_tasks_boundary():
    result = json.loads(fanout_subagents(_ok_tasks(MAX_TASKS)))
    assert result["status"] == "ok"
    assert len(result["tasks"]) == MAX_TASKS


def test_fanout_exceed_max_tasks():
    result = json.loads(fanout_subagents(_ok_tasks(MAX_TASKS + 1)))
    assert result["status"] == "error"
    assert f"Too many tasks ({MAX_TASKS + 1}). Max {MAX_TASKS}." in result["message"]


def test_fanout_tasks_json_string_success():
    result = json.loads(fanout_subagents(json.dumps([_task()])))
    assert result["status"] == "ok"
    assert result["tasks"] == [_task()]


@pytest.mark.parametrize("tasks", [{"a": 1}, 123, None, True])
def test_fanout_tasks_type_invalid(tasks):
    result = json.loads(fanout_subagents(tasks))
    assert result["status"] == "error"
    assert "tasks must be a list" in result["message"]


def test_fanout_tasks_empty_list():
    result = json.loads(fanout_subagents([]))
    assert result["status"] == "error"
    assert "tasks must be a non-empty list" in result["message"]


@pytest.mark.parametrize("tasks, expected", [
    ("not json", "must be a list"),
    ("{bad", "must be a list"),
    ('"123"', "must be a list"),
    ("null", "must be a list"),
    ("{}", "must be a list"),
    ("[]", "must be a non-empty list"),
])
def test_fanout_tasks_json_invalid(tasks, expected):
    result = json.loads(fanout_subagents(tasks))
    assert result["status"] == "error"
    assert expected in result["message"]


@pytest.mark.parametrize("element", [[1], 123, None, True, "json-str"])
def test_fanout_element_type_invalid(element):
    result = json.loads(fanout_subagents([element]))
    assert result["status"] == "error"
    assert "task[0] must be a dict" in result["message"]


@pytest.mark.parametrize("field", [
    "task_id", "task_name", "task_description",
    "task_completion_status", "subagent_id", "subagent_name",
])
def test_fanout_missing_fields(field):
    task = _task()
    del task[field]
    result = json.loads(fanout_subagents([task]))
    assert result["status"] == "error"
    assert "missing required fields" in result["message"]
    assert field in result["message"]


def test_fanout_missing_multiple_reported():
    result = json.loads(fanout_subagents([{"task_id": "t1"}]))
    assert result["status"] == "error"
    for field in ("subagent_id", "subagent_name", "task_completion_status",
                  "task_description", "task_name"):
        assert field in result["message"]


def test_fanout_unknown_field_rejected():
    result = json.loads(fanout_subagents([_task(evil_field=1)]))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "evil_field" in result["message"]


def test_fanout_multiple_extra_sorted():
    result = json.loads(fanout_subagents([_task(x_field=1, a_field=2)]))
    assert result["status"] == "error"
    assert "['a_field', 'x_field']" in result["message"]


def test_fanout_extra_checked_before_missing():
    result = json.loads(fanout_subagents([{"task_id": "t1", "evil_field": 1}]))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "missing required" not in result["message"]


@pytest.mark.parametrize("task_id", ["", "   ", 123, None, True])
def test_fanout_task_id_invalid(task_id):
    result = json.loads(fanout_subagents([_task(task_id=task_id)]))
    assert result["status"] == "error"
    assert "task_id must be a non-empty string" in result["message"]


def test_fanout_duplicate_task_id_rejected():
    result = json.loads(fanout_subagents([_task(), _task(subagent_id="reviewer_b")]))
    assert result["status"] == "error"
    assert "duplicate task_id: 't1'" in result["message"]


def test_fanout_duplicate_task_id_after_strip():
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id=" t1 ", subagent_id="reviewer_b")]))
    assert result["status"] == "error"
    assert "duplicate task_id: 't1'" in result["message"]


def test_fanout_task_id_case_sensitive():
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id="T1", subagent_id="reviewer_b")]))
    assert result["status"] == "ok"
    assert len(result["tasks"]) == 2


def test_fanout_strips_text_fields():
    result = json.loads(fanout_subagents([_task(
        task_id="  t1  ", task_name="  任务一  ",
        task_description="  描述一  ", subagent_name="  程序员甲  ")]))
    assert result["status"] == "ok"
    cleaned = result["tasks"][0]
    assert cleaned["task_id"] == "t1"
    assert cleaned["task_name"] == "任务一"
    assert cleaned["task_description"] == "描述一"
    assert cleaned["subagent_name"] == "程序员甲"


@pytest.mark.parametrize("task_name", ["", " ", 123, None])
def test_fanout_task_name_invalid(task_name):
    result = json.loads(fanout_subagents([_task(task_name=task_name)]))
    assert result["status"] == "error"
    assert "task_name must be a non-empty string" in result["message"]


@pytest.mark.parametrize("task_description", ["", " ", 123, None])
def test_fanout_task_description_invalid(task_description):
    result = json.loads(fanout_subagents([_task(task_description=task_description)]))
    assert result["status"] == "error"
    assert "task_description must be a non-empty string" in result["message"]


@pytest.mark.parametrize("status", [True, None, 0, 1, "false", []])
def test_fanout_completion_status_invalid(status):
    result = json.loads(fanout_subagents([_task(task_completion_status=status)]))
    assert result["status"] == "error"
    assert "task_completion_status must be false" in result["message"]


@pytest.mark.parametrize("subagent_id", ["", "   ", 123, None, True])
def test_fanout_subagent_id_invalid(subagent_id):
    result = json.loads(fanout_subagents([_task(subagent_id=subagent_id)]))
    assert result["status"] == "error"
    assert "subagent_id must be a non-empty string" in result["message"]


def test_fanout_subagent_id_stripped_stored():
    result = json.loads(fanout_subagents([_task(subagent_id="  programmer_a  ")]))
    assert result["status"] == "ok"
    assert result["tasks"][0]["subagent_id"] == "programmer_a"


@pytest.mark.parametrize("subagent_id", ["hacker_x", "abc", "_x"])
def test_fanout_subagent_prefix_invalid(subagent_id):
    result = json.loads(fanout_subagents([_task(subagent_id=subagent_id)]))
    assert result["status"] == "error"
    assert "has invalid prefix" in result["message"]
    assert "Available" in result["message"]


@pytest.mark.parametrize("prefix", ["programmer", "reviewer", "researcher"])
def test_fanout_prefix_valid(prefix):
    result = json.loads(fanout_subagents([_task(subagent_id=f"{prefix}_a")]))
    assert result["status"] == "ok"


def test_fanout_subagent_id_prefix_only_allowed():
    result = json.loads(fanout_subagents([_task(subagent_id="programmer")]))
    assert result["status"] == "ok"


@pytest.mark.parametrize("subagent_name", ["", " ", 123, None])
def test_fanout_subagent_name_invalid(subagent_name):
    result = json.loads(fanout_subagents([_task(subagent_name=subagent_name)]))
    assert result["status"] == "error"
    assert "subagent_name must be a non-empty string" in result["message"]


def test_fanout_duplicate_subagent_id_rejected():
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id="t2", subagent_id="programmer_a")]))
    assert result["status"] == "error"
    assert "duplicate subagent_id: 'programmer_a'" in result["message"]


def test_fanout_duplicate_subagent_id_after_strip():
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id="t2", subagent_id=" programmer_a ")])
    )
    assert result["status"] == "error"
    assert "duplicate subagent_id: 'programmer_a'" in result["message"]


@pytest.mark.parametrize("project_dir", [123, None, True, []])
def test_fanout_project_dir_invalid(project_dir):
    result = json.loads(fanout_subagents([_task(project_dir=project_dir)]))
    assert result["status"] == "error"
    assert "project_dir must be a string" in result["message"]


def test_fanout_current_tasks_rejected():
    result = json.loads(fanout_subagents([_task()], current_tasks=[_task()]))
    assert result["status"] == "error"
    assert "already called in this turn" in result["message"]


def test_fanout_current_tasks_none_default():
    result = json.loads(fanout_subagents([_task()]))
    assert result["status"] == "ok"


def test_fanout_current_tasks_empty_list_allowed():
    result = json.loads(fanout_subagents([_task()], current_tasks=[]))
    assert result["status"] == "ok"


def test_fanout_current_tasks_priority():
    result = json.loads(fanout_subagents([], current_tasks=[_task()]))
    assert result["status"] == "error"
    assert "already called in this turn" in result["message"]
    assert "non-empty list" not in result["message"]


def test_fanout_ok_message_reports_count():
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id="t2", subagent_id="reviewer_b")]))
    assert result["status"] == "ok"
    assert "Dispatched 2 task(s) to subagents." in result["message"]


def test_fanout_error_localization_index():
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id="t2", subagent_id="reviewer_b", task_name="")]))
    assert result["status"] == "error"
    assert "task[1]" in result["message"]
    assert "task_name" in result["message"]


def test_fanout_ok_response_contract():
    result = json.loads(fanout_subagents([_task()]))
    assert set(result.keys()) == {"status", "message", "tasks"}


def test_fanout_error_response_has_no_tasks():
    result = json.loads(fanout_subagents([]))
    assert result["status"] == "error"
    assert "tasks" not in result


def test_fanout_chinese_not_escaped():
    raw = fanout_subagents([_task()])
    assert "任务一" in raw
    assert "\\u" not in raw


def test_fanout_lifecycle_turn_semantics():
    first = json.loads(fanout_subagents([_task()]))
    assert first["status"] == "ok"
    second = json.loads(fanout_subagents(
        [_task(task_id="t2", subagent_id="reviewer_b")], current_tasks=first["tasks"]))
    assert second["status"] == "error"
    assert "already called in this turn" in second["message"]
