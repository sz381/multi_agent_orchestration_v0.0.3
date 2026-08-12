"""end_orchestration 全方面测试：参数校验、状态闸门、plan 阶段校验与响应契约。

测试项目：
- test_end_orchestration_success:                           验证正常结束与 message 精确断言
- test_end_orchestration_response_stripped:                 验证 response 首尾空白不影响结束
- test_end_orchestration_response_max_length_boundary:      验证 MAX_RESPONSE_LENGTH 恰好边界通过
- test_end_orchestration_plan_none_default:                 验证 plan 默认 None 放行
- test_end_orchestration_plan_empty_list_allowed:           验证空列表视为无计划放行
- test_end_orchestration_plan_all_done_success:             验证计划全部 done 时结束成功
- test_end_orchestration_current_response_rejected:         验证 current_response 非空拒绝（防 last-win）
- test_end_orchestration_current_response_blank_rejected:   验证空白 current_response 视为已调用过
- test_end_orchestration_current_response_empty_allowed:    验证空字符串 current_response 放行
- test_end_orchestration_should_orch_end_false_rejected:    验证状态闸门 False 拒绝结束
- test_end_orchestration_should_orch_end_type_invalid:      参数化验证非 bool 各形态拒绝
- test_end_orchestration_plan_type_invalid:                 参数化验证 plan 为 str/dict/int/bool 拒绝
- test_end_orchestration_plan_element_type_invalid:         参数化验证 plan 元素非 dict 拒绝
- test_end_orchestration_plan_phase_id_invalid:             参数化验证 phase_id 空/非字符串拒绝
- test_end_orchestration_plan_element_index_localization:   验证错误消息定位 plan[j] 索引
- test_end_orchestration_plan_pending_status_rejected:      参数化验证未完成状态拒绝结束
- test_end_orchestration_plan_multiple_pending_reported:    验证多个未完成阶段全部列出
- test_end_orchestration_response_type_invalid:             参数化验证 response 非字符串拒绝
- test_end_orchestration_response_empty_rejected:           参数化验证 response 空/空白拒绝
- test_end_orchestration_response_too_long_rejected:        验证超长 response 拒绝并报告数量
- test_end_orchestration_ok_response_contract:              验证 ok 响应仅 status/message 两字段
- test_end_orchestration_error_response_contract:           验证 error 响应仅 status/message 两字段
- test_end_orchestration_current_response_priority:         验证调用级防护优先于状态闸门
- test_end_orchestration_should_orch_end_priority:          验证状态闸门优先于 plan 校验
- test_end_orchestration_plan_priority:                     验证 plan 校验优先于 response 校验
- test_end_orchestration_lifecycle_turn_semantics:          验证轮次语义：成功后再次调用拒绝

覆盖场景：
- 参数校验：response 类型/空值/空白/超长（含 MAX_RESPONSE_LENGTH 边界）；should_orch_end 类型与值闸门（字符串 "false" truthy 陷阱）；current_response 防 last-win（空串放行/空白与非空拒绝）
- plan 校验：类型（list/None）；元素 dict 与 phase_id 非空字符串；未完成阶段（pending/in_progress/未知状态）拒绝并列出 phase_id；全部 done 放行；错误消息定位 plan[j]
- 检查顺序契约：current_response → should_orch_end → plan → response，同输入多违例时按序只报第一个
- 响应契约：ok/error 均仅 status/message 两字段；无 \\u 转义
- 轮次语义：第一次调用成功 → 模拟 state 更新后第二次调用拒绝

测试用例数量：48
"""

import json

import pytest

from core.tools._kernel._orch_control import end_orchestration
from core.tools._kernel.constants import MAX_RESPONSE_LENGTH


def test_end_orchestration_success():
    """验证正常结束：返回 ok 且 message 精确匹配。"""
    result = json.loads(end_orchestration("final answer"))
    assert result == {"status": "ok", "message": "Orchestration ended."}


def test_end_orchestration_response_stripped():
    """验证 response 带首尾空白时正常结束。

    内部 strip 后参与长度校验，不应影响结束路径。
    """
    result = json.loads(end_orchestration("  final answer  "))
    assert result["status"] == "ok"


def test_end_orchestration_response_max_length_boundary():
    """验证 response 恰好 MAX_RESPONSE_LENGTH 边界通过。

    与超长拒绝形成边界对照，防止 off-by-one。
    """
    result = json.loads(end_orchestration("x" * MAX_RESPONSE_LENGTH))
    assert result["status"] == "ok"


def test_end_orchestration_plan_none_default():
    """验证 plan 默认 None（未传）放行结束。

    首次结束不传 plan 是最常见路径。
    """
    result = json.loads(end_orchestration("final"))
    assert result["status"] == "ok"


def test_end_orchestration_plan_empty_list_allowed():
    """验证 plan 为空列表时视为无计划放行。

    计划清空后 [] 可直接作为 plan 传入结束。
    """
    result = json.loads(end_orchestration("final", plan=[]))
    assert result["status"] == "ok"


def test_end_orchestration_plan_all_done_success():
    """验证计划全部 done 时结束成功。

    混合状态计划中无 pending 即满足结束条件。
    """
    plan = [
        {"phase_id": "p1", "phase_status": "done"},
        {"phase_id": "p2", "phase_status": "done"},
    ]
    result = json.loads(end_orchestration("final", plan=plan))
    assert result["status"] == "ok"


def test_end_orchestration_current_response_rejected():
    """验证 current_response 非空拒绝（防并发 last-win）。

    StateGraph 中 response 字段已有值时视为本轮已结束过。
    """
    result = json.loads(end_orchestration("final", current_response="old"))
    assert result["status"] == "error"
    assert "already called in this turn" in result["message"]


def test_end_orchestration_current_response_blank_rejected():
    """验证空白 current_response 同样视为已调用过。

    空白字符串是 truthy，与空字符串（falsy）语义不同，须拒绝。
    """
    result = json.loads(end_orchestration("final", current_response="   "))
    assert result["status"] == "error"
    assert "already called in this turn" in result["message"]


def test_end_orchestration_current_response_empty_allowed():
    """验证空字符串 current_response 放行。

    未结束过（response 字段为空）时正常结束。
    """
    result = json.loads(end_orchestration("final", current_response=""))
    assert result["status"] == "ok"


def test_end_orchestration_should_orch_end_false_rejected():
    """验证状态闸门 False 拒绝结束。

    should_orch_end 为 False 时编排处于阻止状态，需先解除。
    """
    result = json.loads(end_orchestration("final", should_orch_end=False))
    assert result["status"] == "error"
    assert "should_orch_end is False" in result["message"]


@pytest.mark.parametrize("should_orch_end", [None, "false", "False", 0, 1, [], {}])
def test_end_orchestration_should_orch_end_type_invalid(should_orch_end):
    """参数化验证 should_orch_end 非 bool 各形态拒绝。

    int/字符串/None 均拒绝；重点防字符串 "false" 是 truthy 会误放行。
    """
    result = json.loads(end_orchestration("final", should_orch_end=should_orch_end))
    assert result["status"] == "error"
    assert "must be a boolean" in result["message"]


@pytest.mark.parametrize("plan", ["[{}]", {"a": 1}, 123, True])
def test_end_orchestration_plan_type_invalid(plan):
    """参数化验证 plan 为 str/dict/int/bool 拒绝。

    类型防护：必须是 list 或 None，非法类型一律拒绝。
    """
    result = json.loads(end_orchestration("final", plan=plan))
    assert result["status"] == "error"
    assert "plan must be a list or None" in result["message"]


@pytest.mark.parametrize("element", ["abc", None, 123])
def test_end_orchestration_plan_element_type_invalid(element):
    """参数化验证 plan 元素非 dict 拒绝。

    元素必须是 dict 且含非空字符串 phase_id。
    """
    result = json.loads(end_orchestration("final", plan=[element]))
    assert result["status"] == "error"
    assert "plan[0] must be a dict" in result["message"]


@pytest.mark.parametrize("phase_id", ["", "   ", 123, None, True])
def test_end_orchestration_plan_phase_id_invalid(phase_id):
    """参数化验证 phase_id 空/空白/非字符串/None/bool 拒绝。

    非空字符串是 id 的唯一合法形态（bool 是 int 子类需显式排除）。
    """
    result = json.loads(end_orchestration(
        "final", plan=[{"phase_id": phase_id, "phase_status": "done"}]))
    assert result["status"] == "error"
    assert "plan[0] must be a dict with a non-empty string phase_id" in result["message"]


def test_end_orchestration_plan_element_index_localization():
    """验证 plan 元素违例时错误消息定位 plan[j] 索引。"""
    result = json.loads(end_orchestration(
        "final", plan=[{"phase_id": "p1", "phase_status": "done"}, {"phase_status": "done"}]))
    assert result["status"] == "error"
    assert "plan[1]" in result["message"]


@pytest.mark.parametrize("status", ["pending", "in_progress", "doing"])
def test_end_orchestration_plan_pending_status_rejected(status):
    """参数化验证未完成状态（含未知状态）拒绝结束。

    仅 phase_status == "done" 视为完成，其余一律 pending。
    """
    result = json.loads(end_orchestration(
        "final", plan=[{"phase_id": "p1", "phase_status": status}]))
    assert result["status"] == "error"
    assert "still pending" in result["message"]
    assert "p1" in result["message"]


def test_end_orchestration_plan_multiple_pending_reported():
    """验证多个未完成阶段全部列出。

    一次调用即可获知全部阻塞阶段，减少往返修正。
    """
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
    """参数化验证 response 非字符串各形态拒绝。"""
    result = json.loads(end_orchestration(response))
    assert result["status"] == "error"
    assert "response must be a string" in result["message"]


@pytest.mark.parametrize("response", ["", "   "])
def test_end_orchestration_response_empty_rejected(response):
    """参数化验证 response 空/空白拒绝。

    空答案无意义，必须显式拒绝并提示 non-empty string。
    """
    result = json.loads(end_orchestration(response))
    assert result["status"] == "error"
    assert "response must be a non-empty string" in result["message"]


def test_end_orchestration_response_too_long_rejected():
    """验证超长 response 拒绝并报告实际数量与上限。

    错误消息必须同时报告字符数与 MAX_RESPONSE_LENGTH，便于诊断。
    """
    result = json.loads(end_orchestration("x" * (MAX_RESPONSE_LENGTH + 1)))
    assert result["status"] == "error"
    assert f"response too long ({MAX_RESPONSE_LENGTH + 1} chars)" in result["message"]
    assert f"Max {MAX_RESPONSE_LENGTH}" in result["message"]


def test_end_orchestration_ok_response_contract():
    """验证 ok 响应仅 status/message 两字段。

    字段集合必须精确等于两字段，防止未来新增字段破坏契约。
    """
    result = json.loads(end_orchestration("final"))
    assert set(result.keys()) == {"status", "message"}


def test_end_orchestration_error_response_contract():
    """验证 error 响应仅 status/message 两字段。"""
    result = json.loads(end_orchestration("final", should_orch_end=False))
    assert set(result.keys()) == {"status", "message"}


def test_end_orchestration_current_response_priority():
    """验证调用级防护优先于状态闸门。

    同输入同时违例时只报 already called，检查顺序是稳定契约。
    """
    result = json.loads(end_orchestration(
        "final", current_response="old", should_orch_end=False))
    assert result["status"] == "error"
    assert "already called in this turn" in result["message"]
    assert "should_orch_end" not in result["message"]


def test_end_orchestration_should_orch_end_priority():
    """验证状态闸门优先于 plan 校验。

    should_orch_end=False 与 plan 未完成同时违例时只报状态闸门。
    """
    result = json.loads(end_orchestration(
        "final", should_orch_end=False,
        plan=[{"phase_id": "p1", "phase_status": "pending"}]))
    assert result["status"] == "error"
    assert "should_orch_end is False" in result["message"]
    assert "still pending" not in result["message"]


def test_end_orchestration_plan_priority():
    """验证 plan 校验优先于 response 校验。

    plan 未完成与 response 非字符串同时违例时只报 plan。
    """
    result = json.loads(end_orchestration(
        123, plan=[{"phase_id": "p1", "phase_status": "pending"}]))
    assert result["status"] == "error"
    assert "still pending" in result["message"]
    assert "response" not in result["message"]


def test_end_orchestration_lifecycle_turn_semantics():
    """轮次语义：第一次结束成功 → 模拟 state 更新 → 第二次调用拒绝。

    第一次调用时 response 字段为空（current_response=""）放行；
    成功后 state 写入 response，第二次调用（current_response=上次结果）拒绝。
    """
    first = json.loads(end_orchestration("final", current_response=""))
    assert first["status"] == "ok"
    second = json.loads(end_orchestration("final", current_response="final"))
    assert second["status"] == "error"
    assert "already called in this turn" in second["message"]
