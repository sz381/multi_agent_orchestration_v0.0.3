"""fanout_subagents 全方面测试：参数校验、字段白名单、判重语义、前缀校验与响应契约。

测试项目：
- test_fanout_single_task_success:                       验证单任务成功与 clean 结构精确断言
- test_fanout_multiple_tasks_order_kept:                 验证多任务顺序与输入一致
- test_fanout_project_dir_kept_stripped:                 验证 project_dir 保留且去除首尾空白
- test_fanout_project_dir_blank_dropped:                 验证空/空白 project_dir 剔除字段
- test_fanout_max_tasks_boundary:                        验证 20 任务（MAX_TASKS 上限边界）成功
- test_fanout_exceed_max_tasks:                          验证 21 任务超限拒绝
- test_fanout_tasks_json_string_success:                 验证 tasks 为 JSON 字符串创建成功
- test_fanout_tasks_type_invalid:                        参数化验证 dict/int/None/bool 拒绝
- test_fanout_tasks_empty_list:                          验证空列表拒绝
- test_fanout_tasks_json_invalid:                        参数化验证非法 JSON 字符串各形态拒绝
- test_fanout_element_type_invalid:                      参数化验证元素为 list/int/None/bool/str 拒绝
- test_fanout_missing_fields:                            参数化验证缺任一必填字段拒绝
- test_fanout_missing_multiple_reported:                 验证缺多字段时全部列出
- test_fanout_unknown_field_rejected:                    验证额外字段拒绝
- test_fanout_multiple_extra_sorted:                     验证多额外字段 sorted 列出
- test_fanout_extra_checked_before_missing:              验证 extra 检查优先于 missing
- test_fanout_task_id_invalid:                           参数化验证空/空白/非字符串/None/bool id 拒绝
- test_fanout_duplicate_task_id_rejected:                验证完全重复 task_id 拒绝
- test_fanout_duplicate_task_id_after_strip:             验证 strip 后重复 task_id 拒绝
- test_fanout_task_id_case_sensitive:                    验证大小写不同不判重
- test_fanout_strips_text_fields:                        验证 task_id/name/desc/subagent_name strip 后存储
- test_fanout_task_name_invalid:                         参数化验证空/空白/非字符串/None name 拒绝
- test_fanout_task_description_invalid:                  参数化验证空/空白/非字符串/None desc 拒绝
- test_fanout_completion_status_invalid:                 参数化验证非 False 各形态拒绝
- test_fanout_subagent_id_invalid:                       参数化验证空/空白/非字符串/None/bool id 拒绝
- test_fanout_subagent_id_stripped_stored:               验证 subagent_id strip 后存储
- test_fanout_subagent_prefix_invalid:                   参数化验证非法前缀/无下划线/空前缀拒绝
- test_fanout_prefix_valid:                              参数化验证三个合法前缀均通过
- test_fanout_subagent_id_prefix_only_allowed:           验证仅前缀无后缀也放行
- test_fanout_subagent_name_invalid:                     参数化验证空/空白/非字符串/None name 拒绝
- test_fanout_duplicate_subagent_id_rejected:            验证同轮重复 subagent_id 拒绝
- test_fanout_duplicate_subagent_id_after_strip:         验证 strip 后重复 subagent_id 拒绝
- test_fanout_project_dir_invalid:                       参数化验证 project_dir 非字符串拒绝
- test_fanout_current_tasks_rejected:                    验证 current_tasks 非空拒绝（防 last-win）
- test_fanout_current_tasks_none_default:                验证默认 None 放行
- test_fanout_current_tasks_empty_list_allowed:          验证空列表放行
- test_fanout_current_tasks_priority:                    验证调用级防护优先于参数级校验
- test_fanout_ok_message_reports_count:                  验证 ok 消息报告任务数量
- test_fanout_error_localization_index:                  验证错误消息定位 task[i] 索引
- test_fanout_ok_response_contract:                      验证 ok 响应仅 status/message/tasks 三字段
- test_fanout_error_response_has_no_tasks:               验证 error 响应不含 tasks 字段
- test_fanout_chinese_not_escaped:                       验证 ensure_ascii=False 中文直出
- test_fanout_lifecycle_turn_semantics:                  验证轮次语义：成功后再次调用拒绝

覆盖场景：
- 参数校验：tasks 非列表（dict/int/None/bool）与空列表拒绝；JSON 字符串兼容（含非法 JSON 各形态）；元素非 dict 拒绝
- 字段白名单：缺失/额外字段校验（Allowed 全列表报告）；task_id/name/desc/subagent_name 空值、空白、非字符串、None 拒绝；task_completion_status 仅精确 False 放行；project_dir 可选且非字符串拒绝
- 判重语义：完全重复与 strip 后重复均拒绝；大小写敏感不判重；subagent_id 同轮唯一（每个子代理一个任务）
- 前缀校验：programmer/reviewer/researcher 合法（strip 后判定）；非法前缀/无下划线/空前缀拒绝；仅前缀无后缀放行
- 归一化：task_id/name/desc/subagent_name/project_dir/subagent_id 去除首尾空白后存储
- 响应契约：ok 仅 status/message/tasks 三字段（tasks 为清理后列表）；error 不含 tasks；消息报告任务数；中文 ensure_ascii=False 直出
- 调用级防护：current_tasks 非空拒绝（优先于参数校验）；None/[] 放行；轮次语义模拟

测试用例数量：89
"""

import json

import pytest

from core.tools._kernel._orch_control import fanout_subagents
from core.tools._kernel.constants import MAX_TASKS
from tests.helpers import _ok_tasks, _task


def test_fanout_single_task_success():
    """验证单任务成功：返回 ok 且 clean 结构精确。

    无 project_dir 输入时输出不得包含该字段。
    """
    result = json.loads(fanout_subagents([_task()]))
    assert result["status"] == "ok"
    assert result["tasks"] == [_task()]


def test_fanout_multiple_tasks_order_kept():
    """验证多任务顺序与输入一致。

    fanout 不做任何排序，返回顺序必须与输入顺序完全一致。
    """
    tasks = [_task(), _task(task_id="t2", subagent_id="reviewer_b")]
    result = json.loads(fanout_subagents(tasks))
    assert result["status"] == "ok"
    assert [t["task_id"] for t in result["tasks"]] == ["t1", "t2"]
    assert result["tasks"] == tasks


def test_fanout_project_dir_kept_stripped():
    """验证 project_dir 保留且去除首尾空白。"""
    result = json.loads(fanout_subagents([_task(project_dir="  /tmp/x  ")]))
    assert result["status"] == "ok"
    assert result["tasks"][0]["project_dir"] == "/tmp/x"


def test_fanout_project_dir_blank_dropped():
    """验证空/空白 project_dir 从输出中剔除。

    可选字段为空时不出现在 clean 结构中，保持输出契约稳定。
    """
    result = json.loads(fanout_subagents([_task(project_dir="   ")]))
    assert result["status"] == "ok"
    assert "project_dir" not in result["tasks"][0]


def test_fanout_max_tasks_boundary():
    """验证 20 任务（MAX_TASKS 上限边界）成功。

    恰好达到上限时应放行，为超限拒绝提供边界对照。
    """
    result = json.loads(fanout_subagents(_ok_tasks(MAX_TASKS)))
    assert result["status"] == "ok"
    assert len(result["tasks"]) == MAX_TASKS


def test_fanout_exceed_max_tasks():
    """验证 21 任务超限拒绝。

    错误消息必须同时报告实际数量（21）与上限（20），便于诊断。
    """
    result = json.loads(fanout_subagents(_ok_tasks(MAX_TASKS + 1)))
    assert result["status"] == "error"
    assert f"Too many tasks ({MAX_TASKS + 1}). Max {MAX_TASKS}." in result["message"]


def test_fanout_tasks_json_string_success():
    """验证 tasks 为 JSON 字符串（模型只输出 str 场景）成功。

    工具必须兼容 str 形态输入，结果与 dict 列表输入一致。
    """
    result = json.loads(fanout_subagents(json.dumps([_task()])))
    assert result["status"] == "ok"
    assert result["tasks"] == [_task()]


@pytest.mark.parametrize("tasks", [{"a": 1}, 123, None, True])
def test_fanout_tasks_type_invalid(tasks):
    """参数化验证 tasks 为 dict/int/None/bool 时拒绝。

    非列表输入统一按类型错误处理，消息提示需要列表。
    """
    result = json.loads(fanout_subagents(tasks))
    assert result["status"] == "error"
    assert "tasks must be a list" in result["message"]


def test_fanout_tasks_empty_list():
    """验证空列表拒绝（任务至少一个）。

    空派遣无意义，必须显式拒绝并提示 non-empty list。
    """
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
    """参数化验证 JSON 字符串各非法形态。

    语法错误解析失败后按非列表处理（must be a list）；
    解析成功但为空数组时走非空校验（non-empty list）。
    """
    result = json.loads(fanout_subagents(tasks))
    assert result["status"] == "error"
    assert expected in result["message"]


@pytest.mark.parametrize("element", [[1], 123, None, True, "json-str"])
def test_fanout_element_type_invalid(element):
    """参数化验证元素为 list/int/None/bool/str 时拒绝。

    元素必须是 dict（fanout 不做元素级 JSON 解析，str 元素直接拒绝）。
    """
    result = json.loads(fanout_subagents([element]))
    assert result["status"] == "error"
    assert "task[0] must be a dict" in result["message"]


@pytest.mark.parametrize("field", [
    "task_id", "task_name", "task_description",
    "task_completion_status", "subagent_id", "subagent_name",
])
def test_fanout_missing_fields(field):
    """参数化验证缺任一必填字段拒绝。

    错误消息必须包含缺失字段名，便于调用方补全。
    """
    task = _task()
    del task[field]
    result = json.loads(fanout_subagents([task]))
    assert result["status"] == "error"
    assert "missing required fields" in result["message"]
    assert field in result["message"]


def test_fanout_missing_multiple_reported():
    """验证缺多字段时全部列出。

    一次调用即可获知全部缺失字段，减少往返修正。
    """
    result = json.loads(fanout_subagents([{"task_id": "t1"}]))
    assert result["status"] == "error"
    for field in ("subagent_id", "subagent_name", "task_completion_status",
                  "task_description", "task_name"):
        assert field in result["message"]


def test_fanout_unknown_field_rejected():
    """验证额外字段拒绝。

    字段白名单契约，未知字段一律拒绝并点名。
    """
    result = json.loads(fanout_subagents([_task(evil_field=1)]))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "evil_field" in result["message"]


def test_fanout_multiple_extra_sorted():
    """验证多额外字段 sorted 列出。

    sorted 排序保证消息确定性，方便断言与回归。
    """
    result = json.loads(fanout_subagents([_task(x_field=1, a_field=2)]))
    assert result["status"] == "error"
    assert "['a_field', 'x_field']" in result["message"]


def test_fanout_extra_checked_before_missing():
    """验证 extra 检查优先于 missing。

    同输入同时违例时只报 extra，检查顺序是稳定契约。
    """
    result = json.loads(fanout_subagents([{"task_id": "t1", "evil_field": 1}]))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "missing required" not in result["message"]


@pytest.mark.parametrize("task_id", ["", "   ", 123, None, True])
def test_fanout_task_id_invalid(task_id):
    """参数化验证 task_id 为空/空白/非字符串/None/bool 拒绝。

    非空字符串是 id 的唯一合法形态（bool 是 int 子类需显式排除）。
    """
    result = json.loads(fanout_subagents([_task(task_id=task_id)]))
    assert result["status"] == "error"
    assert "task_id must be a non-empty string" in result["message"]


def test_fanout_duplicate_task_id_rejected():
    """验证完全重复 task_id 拒绝。

    重复 id 会破坏任务定位语义，必须在创建时拦截。
    """
    result = json.loads(fanout_subagents([_task(), _task(subagent_id="reviewer_b")]))
    assert result["status"] == "error"
    assert "duplicate task_id: 't1'" in result["message"]


def test_fanout_duplicate_task_id_after_strip():
    """验证 strip 后重复 task_id 拒绝。

    "t1" 与 " t1 " 归一化后视为同一 id，判重发生在 strip 之后。
    """
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id=" t1 ", subagent_id="reviewer_b")]))
    assert result["status"] == "error"
    assert "duplicate task_id: 't1'" in result["message"]


def test_fanout_task_id_case_sensitive():
    """验证大小写不同不判重。

    id 比较大小写敏感，"t1" 与 "T1" 是两个合法任务。
    """
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id="T1", subagent_id="reviewer_b")]))
    assert result["status"] == "ok"
    assert len(result["tasks"]) == 2


def test_fanout_strips_text_fields():
    """验证 task_id/name/desc/subagent_name 去除首尾空白后存储。

    文本字段统一归一化，保持与 plan 工具一致的存储契约。
    """
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
    """参数化验证 task_name 为空/空白/非字符串/None 拒绝。

    名称与 id 一样必须是非空字符串。
    """
    result = json.loads(fanout_subagents([_task(task_name=task_name)]))
    assert result["status"] == "error"
    assert "task_name must be a non-empty string" in result["message"]


@pytest.mark.parametrize("task_description", ["", " ", 123, None])
def test_fanout_task_description_invalid(task_description):
    """参数化验证 task_description 为空/空白/非字符串/None 拒绝。"""
    result = json.loads(fanout_subagents([_task(task_description=task_description)]))
    assert result["status"] == "error"
    assert "task_description must be a non-empty string" in result["message"]


@pytest.mark.parametrize("status", [True, None, 0, 1, "false", []])
def test_fanout_completion_status_invalid(status):
    """参数化验证 task_completion_status 非 False 各形态拒绝。

    新派遣的任务必须精确为 False；0/1 等 int 值也拒绝（防误传）。
    """
    result = json.loads(fanout_subagents([_task(task_completion_status=status)]))
    assert result["status"] == "error"
    assert "task_completion_status must be false" in result["message"]


@pytest.mark.parametrize("subagent_id", ["", "   ", 123, None, True])
def test_fanout_subagent_id_invalid(subagent_id):
    """参数化验证 subagent_id 为空/空白/非字符串/None/bool 拒绝。"""
    result = json.loads(fanout_subagents([_task(subagent_id=subagent_id)]))
    assert result["status"] == "error"
    assert "subagent_id must be a non-empty string" in result["message"]


def test_fanout_subagent_id_stripped_stored():
    """验证 subagent_id strip 后存储，前缀判定基于 strip 后值。"""
    result = json.loads(fanout_subagents([_task(subagent_id="  programmer_a  ")]))
    assert result["status"] == "ok"
    assert result["tasks"][0]["subagent_id"] == "programmer_a"


@pytest.mark.parametrize("subagent_id", ["hacker_x", "abc", "_x"])
def test_fanout_subagent_prefix_invalid(subagent_id):
    """参数化验证非法前缀/无下划线/空前缀拒绝。

    前缀必须是可用 subagent 集合成员（下划线前的部分）。
    """
    result = json.loads(fanout_subagents([_task(subagent_id=subagent_id)]))
    assert result["status"] == "error"
    assert "has invalid prefix" in result["message"]
    assert "Available" in result["message"]


@pytest.mark.parametrize("prefix", ["programmer", "reviewer", "researcher"])
def test_fanout_prefix_valid(prefix):
    """参数化验证三个合法前缀均通过。"""
    result = json.loads(fanout_subagents([_task(subagent_id=f"{prefix}_a")]))
    assert result["status"] == "ok"


def test_fanout_subagent_id_prefix_only_allowed():
    """验证仅前缀无后缀（无下划线）也放行。

    前缀校验基于 split 后首段，缺后缀不视为非法。
    """
    result = json.loads(fanout_subagents([_task(subagent_id="programmer")]))
    assert result["status"] == "ok"


@pytest.mark.parametrize("subagent_name", ["", " ", 123, None])
def test_fanout_subagent_name_invalid(subagent_name):
    """参数化验证 subagent_name 为空/空白/非字符串/None 拒绝。"""
    result = json.loads(fanout_subagents([_task(subagent_name=subagent_name)]))
    assert result["status"] == "error"
    assert "subagent_name must be a non-empty string" in result["message"]


def test_fanout_duplicate_subagent_id_rejected():
    """验证同轮重复 subagent_id 拒绝。

    每个子代理一轮只能处理一个任务，防止重复派遣。
    """
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id="t2", subagent_id="programmer_a")]))
    assert result["status"] == "error"
    assert "duplicate subagent_id: 'programmer_a'" in result["message"]


def test_fanout_duplicate_subagent_id_after_strip():
    """验证 strip 后重复 subagent_id 拒绝。"""
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id="t2", subagent_id=" programmer_a ")])
    )
    assert result["status"] == "error"
    assert "duplicate subagent_id: 'programmer_a'" in result["message"]


@pytest.mark.parametrize("project_dir", [123, None, True, []])
def test_fanout_project_dir_invalid(project_dir):
    """参数化验证 project_dir 非字符串拒绝。

    非字符串会使 strip 崩溃，类型防护必须在取值前拦截。
    """
    result = json.loads(fanout_subagents([_task(project_dir=project_dir)]))
    assert result["status"] == "error"
    assert "project_dir must be a string" in result["message"]


def test_fanout_current_tasks_rejected():
    """验证 current_tasks 非空拒绝（防并发 last-win）。

    StateGraph 中 sub_agent_round_tasks 字段已有值时视为本轮已派遣过。
    """
    result = json.loads(fanout_subagents([_task()], current_tasks=[_task()]))
    assert result["status"] == "error"
    assert "already called in this turn" in result["message"]


def test_fanout_current_tasks_none_default():
    """验证默认 None（未传）放行派遣。

    首次派遣不传 current_tasks 是最常见路径。
    """
    result = json.loads(fanout_subagents([_task()]))
    assert result["status"] == "ok"


def test_fanout_current_tasks_empty_list_allowed():
    """验证空列表 current_tasks 放行。

    清空后的 [] 表示未派遣过，可再次派遣。
    """
    result = json.loads(fanout_subagents([_task()], current_tasks=[]))
    assert result["status"] == "ok"


def test_fanout_current_tasks_priority():
    """验证调用级防护优先于参数级校验。

    current_tasks 非空且 tasks 非法时只报 already called。
    """
    result = json.loads(fanout_subagents([], current_tasks=[_task()]))
    assert result["status"] == "error"
    assert "already called in this turn" in result["message"]
    assert "non-empty list" not in result["message"]


def test_fanout_ok_message_reports_count():
    """验证 ok 消息报告任务数量。"""
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id="t2", subagent_id="reviewer_b")]))
    assert result["status"] == "ok"
    assert "Dispatched 2 task(s) to subagents." in result["message"]


def test_fanout_error_localization_index():
    """验证错误消息定位 task[i] 索引。

    索引定位准确不偏移，同时报告违例字段名。
    """
    result = json.loads(fanout_subagents(
        [_task(), _task(task_id="t2", subagent_id="reviewer_b", task_name="")]))
    assert result["status"] == "error"
    assert "task[1]" in result["message"]
    assert "task_name" in result["message"]


def test_fanout_ok_response_contract():
    """验证 ok 响应仅 status/message/tasks 三字段。

    字段集合必须精确等于三字段，防止未来新增字段破坏契约。
    """
    result = json.loads(fanout_subagents([_task()]))
    assert set(result.keys()) == {"status", "message", "tasks"}


def test_fanout_error_response_has_no_tasks():
    """验证 error 响应不含 tasks 字段。

    失败时不返回半成品任务列表，避免调用方误用不完整数据。
    """
    result = json.loads(fanout_subagents([]))
    assert result["status"] == "error"
    assert "tasks" not in result


def test_fanout_chinese_not_escaped():
    """验证 ensure_ascii=False：中文字面直出而非 \\u 转义。

    原始响应字符串直接包含中文，保证可读性。
    """
    raw = fanout_subagents([_task()])
    assert "任务一" in raw
    assert "\\u" not in raw


def test_fanout_lifecycle_turn_semantics():
    """轮次语义：第一次派遣成功 → 模拟 state 更新 → 第二次调用拒绝。

    第一次调用时 sub_agent_round_tasks 为空（current_tasks=None）放行；
    成功后 state 写入任务列表，第二次调用（current_tasks=上次结果）拒绝。
    """
    first = json.loads(fanout_subagents([_task()]))
    assert first["status"] == "ok"
    second = json.loads(fanout_subagents(
        [_task(task_id="t2", subagent_id="reviewer_b")], current_tasks=first["tasks"]))
    assert second["status"] == "error"
    assert "already called in this turn" in second["message"]
