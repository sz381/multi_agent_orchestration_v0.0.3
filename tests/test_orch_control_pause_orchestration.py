"""pause_orchestration 全方面测试：布尔类型校验、状态闸门与响应契约。

测试项目：
- test_pause_orchestration_success:                      验证 True 时暂停成功与 message 精确断言
- test_pause_orchestration_false_rejected:               验证状态闸门 False 拒绝暂停
- test_pause_orchestration_type_invalid:                 参数化验证非 bool 各形态拒绝
- test_pause_orchestration_bool_not_int_subclass:        验证 bool 精确匹配：1 拒绝而 True 通过
- test_pause_orchestration_ok_response_contract:         验证 ok 响应仅 status/message 两字段
- test_pause_orchestration_error_response_contract:      验证 error 响应仅 status/message 两字段
- test_pause_orchestration_chinese_not_escaped:          验证 ensure_ascii=False 无 \\u 转义

覆盖场景：
- 参数校验：should_orch_pause 必须是 bool（字符串 "false" 是 truthy 会误放行；0/1 等 int 拒绝）
- 状态闸门：False 时拒绝暂停，需先解除阻止状态
- bool 精确匹配：bool 是 int 子类，1 与 True 必须区分对待
- 响应契约：ok/error 均仅 status/message 两字段；无 \\u 转义

测试用例数量：13
"""

import json

import pytest

from core.tools._kernel._orch_control import pause_orchestration


def test_pause_orchestration_success():
    """验证 True 时暂停成功：返回 ok 且 message 精确匹配。"""
    result = json.loads(pause_orchestration(True))
    assert result == {"status": "ok", "message": "Orchestration paused."}


def test_pause_orchestration_false_rejected():
    """验证状态闸门 False 拒绝暂停。

    should_orch_pause 为 False 时编排不允许暂停。
    """
    result = json.loads(pause_orchestration(False))
    assert result["status"] == "error"
    assert "should_orch_pause is False" in result["message"]


@pytest.mark.parametrize("should_orch_pause", [None, "false", "False", 0, 1, [], {}])
def test_pause_orchestration_type_invalid(should_orch_pause):
    """参数化验证 should_orch_pause 非 bool 各形态拒绝。

    int/字符串/None 均拒绝；重点防字符串 "false" 是 truthy 会误放行。
    """
    result = json.loads(pause_orchestration(should_orch_pause))
    assert result["status"] == "error"
    assert "must be a boolean" in result["message"]


def test_pause_orchestration_bool_not_int_subclass():
    """验证 bool 精确匹配：1 拒绝而 True 通过。

    bool 是 int 的子类，若用数值判定会放行 1；必须 isinstance 精确到 bool。
    """
    assert json.loads(pause_orchestration(1))["status"] == "error"
    assert json.loads(pause_orchestration(True))["status"] == "ok"


def test_pause_orchestration_ok_response_contract():
    """验证 ok 响应仅 status/message 两字段。

    字段集合必须精确等于两字段，防止未来新增字段破坏契约。
    """
    result = json.loads(pause_orchestration(True))
    assert set(result.keys()) == {"status", "message"}


def test_pause_orchestration_error_response_contract():
    """验证 error 响应仅 status/message 两字段。"""
    result = json.loads(pause_orchestration(False))
    assert set(result.keys()) == {"status", "message"}


def test_pause_orchestration_chinese_not_escaped():
    """验证 ensure_ascii=False：原始响应字符串无 \\u 转义。"""
    raw = pause_orchestration(True)
    assert "\\u" not in raw
