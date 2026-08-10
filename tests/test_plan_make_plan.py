"""make_plan 全方面测试：参数校验、字段校验、判重语义、existing_plan 防护与响应契约。

测试项目：
- test_make_plan_single_phase_success:              验证单阶段创建成功与返回 plan 结构
- test_make_plan_multiple_phases_order_kept:        验证多阶段创建且顺序与输入一致
- test_make_plan_max_phases_allowed:                验证 12 阶段（上限边界）创建成功
- test_make_plan_exceed_max_phases_rejected:        验证 13 阶段超限拒绝
- test_make_plan_strips_phase_id:                   验证 phase_id 去除首尾空白后存储
- test_make_plan_strips_name_description:           验证 phase_name/description 去除首尾空白
- test_make_plan_status_requires_exact_value:       验证 phase_status 不做 strip（集合精确匹配）
- test_make_plan_ok_message_reports_count:          验证 ok 消息报告阶段数量
- test_make_plan_ok_response_contract:              验证 ok 响应仅 status/message/plan 三字段
- test_make_plan_error_response_has_no_plan:        验证 error 响应不含 plan 字段
- test_make_plan_chinese_not_escaped:               验证 ensure_ascii=False 中文直出
- test_make_plan_phases_type_invalid:               参数化验证 None/dict/int/bool 拒绝
- test_make_plan_phases_empty_list:                 验证空列表拒绝
- test_make_plan_phases_json_string_success:        验证 JSON 字符串输入创建成功
- test_make_plan_phases_json_string_invalid:        参数化验证非法 JSON 字符串各形态拒绝
- test_make_plan_phase_as_json_string:              验证元素为 JSON 字符串成功
- test_make_plan_phase_as_invalid_json_string:      验证元素字符串非 JSON 拒绝
- test_make_plan_phase_type_invalid:                参数化验证元素为 list/int/None/bool 拒绝
- test_make_plan_phase_non_string_keys_rejected:    验证非字符串 key 拒绝（sorted 崩溃防护）
- test_make_plan_phase_missing_fields:              参数化验证缺任一必填字段拒绝
- test_make_plan_phase_missing_multiple_reported:   验证缺多字段时全部列出
- test_make_plan_phase_extra_field_rejected:        验证额外字段拒绝
- test_make_plan_phase_multiple_extra_sorted:       验证多额外字段 sorted 列出
- test_make_plan_extra_checked_before_missing:      验证 extra 检查优先于 missing
- test_make_plan_phase_id_invalid:                  参数化验证空/空白/非字符串/None/bool id 拒绝
- test_make_plan_phase_name_invalid:                参数化验证空/空白/非字符串/None name 拒绝
- test_make_plan_phase_description_invalid:         参数化验证空/空白/非字符串/None desc 拒绝
- test_make_plan_phase_status_invalid:              参数化验证非法值/list/dict/int/None/bool 拒绝
- test_make_plan_phase_status_all_valid_values:     参数化验证三个有效状态均通过
- test_make_plan_duplicate_phase_id_rejected:       验证完全重复 id 拒绝
- test_make_plan_duplicate_detected_after_strip:    验证 strip 后重复 id 拒绝
- test_make_plan_duplicate_case_sensitive:          验证大小写不同不判重
- test_make_plan_error_reports_phase_index:         验证错误消息定位 phase[i]
- test_make_plan_second_phase_error_localization:   验证第二个阶段错误定位 phase[1]
- test_make_plan_existing_plan_rejected:            验证已有计划拒绝重建（防 last-win）
- test_make_plan_existing_plan_message_counts:      验证拒绝消息含已有阶段数
- test_make_plan_existing_plan_empty_list_allowed:  验证空列表视为无计划放行
- test_make_plan_existing_plan_none_default:        验证默认 None 放行
- test_make_plan_existing_plan_type_invalid:        参数化验证 str/dict/int 拒绝
- test_make_plan_lifecycle_reject_while_plan_exists:验证 make 后未清空再 make 拒绝
- test_make_plan_lifecycle_recreate_after_delete_all:验证清空后重建成功
- test_make_plan_lifecycle_make_edit_make_rejected:  混合：make → edit → 再 make 拒绝（edit 不解除防重建锁）
- test_make_plan_lifecycle_make_delete_partial_then_recreate: 混合：make → delete 部分 → make 拒绝 → 清空 → make 成功
- test_make_plan_lifecycle_full_chain_rebuild:        混合完整链：make → edit → delete → delete_all → 重建
- test_make_plan_lifecycle_failed_edit_then_recreate: 混合：make → edit 失败（原子性）→ 清空 → make 成功
- test_make_plan_lifecycle_mixed_input_formats:       混合：dict 列表 make → JSON 字符串 edit → 常规 delete

覆盖场景：
- 参数校验：phases 非列表（None/dict/int/bool）与空列表拒绝；元素非 dict（list/int/None/bool）拒绝；非字符串 key 拒绝（sorted 崩溃防护）；缺失/额外字段白名单校验；id/name/desc 空值、空白、非字符串、None 拒绝；status 集合精确匹配与不可哈希输入（list/dict）拒绝
- 输入形态：phases 支持 dict 列表与 JSON 字符串（含元素级 JSON 字符串）；非法 JSON 各形态（语法错误/解析为 dict/int/null/空数组）拒绝
- 判重语义：完全重复与 strip 后重复均拒绝；大小写敏感不判重；错误消息定位 phase[i] 索引
- 响应契约：ok 仅 status/message/plan 三字段；error 不含 plan（无半成品）；消息报告阶段数；中文 ensure_ascii=False 直出
- 防重建防护：existing_plan 非空拒绝重建（消息含已有阶段数）；空列表/None 放行；str/dict/int 类型拒绝
- 生命周期混合链：make 后未清空再 make 拒绝；delete_all 清空后重建成功；edit 不解除防重建锁；delete 部分后仍拒绝、清空后才放行；edit 原子失败不污染后续 delete/make；跨输入形态（dict 列表/JSON 字符串）链式衔接

测试用例数量：79
"""

import json

import pytest

from core.tools._kernel._plan import delete_plan, edit_plan, make_plan
from tests.helpers import _ok_phases, _phase


def test_make_plan_single_phase_success():
    """验证单阶段创建成功：返回 ok 且 plan 结构与输入一致。

    返回的 plan 必须可直接用于后续 edit_plan/delete_plan。
    """
    result = json.loads(make_plan([_phase()]))
    assert result["status"] == "ok"
    assert result["plan"] == [_phase()]
    assert result["message"] == "Plan created with 1 phases."


def test_make_plan_multiple_phases_order_kept():
    """验证多阶段创建且顺序与输入一致。

    plan 工具不做任何排序，返回顺序必须与输入顺序完全一致。
    """
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
    """验证 12 阶段（PLAN_MAX_PHASES 上限边界）创建成功。

    恰好达到上限时应放行，为超限拒绝提供边界对照。
    """
    result = json.loads(make_plan(_ok_phases(12)))
    assert result["status"] == "ok"
    assert len(result["plan"]) == 12


def test_make_plan_exceed_max_phases_rejected():
    """验证 13 阶段超限拒绝。

    错误消息必须同时报告实际数量（13）与上限（12），便于诊断。
    """
    result = json.loads(make_plan(_ok_phases(13)))
    assert result["status"] == "error"
    assert "Too many phases (13). Max 12." in result["message"]


def test_make_plan_strips_phase_id():
    """验证 phase_id 去除首尾空白后存储。

    判重与后续 edit/delete 匹配均基于 strip 后的值。
    """
    result = json.loads(make_plan([_phase(phase_id="  p1  ")]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_id"] == "p1"


def test_make_plan_strips_name_description():
    """验证 phase_name/phase_description 去除首尾空白后存储。

    name 与 description 同样归一化，保持与 phase_id 一致的存储契约。
    """
    result = json.loads(make_plan([_phase(phase_name="  阶段一  ", phase_description="  描述  ")]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "阶段一"
    assert result["plan"][0]["phase_description"] == "描述"


def test_make_plan_status_requires_exact_value():
    """验证 phase_status 不做 strip。

    状态值集合精确匹配，" pending " 等带空白形态必须拒绝。
    """
    result = json.loads(make_plan([_phase(phase_status=" pending ")]))
    assert result["status"] == "error"
    assert "phase_status must be one of" in result["message"]


def test_make_plan_ok_message_reports_count():
    """验证 ok 消息报告阶段数量。

    消息必须包含实际创建的阶段数，供编排层感知计划规模。
    """
    result = json.loads(make_plan(_ok_phases(3)))
    assert result["status"] == "ok"
    assert "Plan created with 3 phases." in result["message"]


def test_make_plan_ok_response_contract():
    """验证 ok 响应仅 status/message/plan 三字段。

    字段集合必须精确等于三字段，防止未来新增字段破坏契约。
    """
    result = json.loads(make_plan([_phase()]))
    assert set(result.keys()) == {"status", "message", "plan"}


def test_make_plan_error_response_has_no_plan():
    """验证 error 响应不含 plan 字段。

    失败时不返回半成品 plan，避免调用方误用不完整数据。
    """
    result = json.loads(make_plan([]))
    assert result["status"] == "error"
    assert "plan" not in result


def test_make_plan_chinese_not_escaped():
    """验证 ensure_ascii=False：中文字面直出而非 \\u 转义。

    原始响应字符串直接包含中文，保证可读性。
    """
    raw = make_plan([_phase()])
    assert "阶段一" in raw
    assert "\\u" not in raw


@pytest.mark.parametrize("phases", [None, {"a": 1}, 123, True])
def test_make_plan_phases_type_invalid(phases):
    """参数化验证 phases 为 None/dict/int/bool 时拒绝。

    非列表输入统一按类型错误处理，消息提示需要非空列表。
    """
    result = json.loads(make_plan(phases))
    assert result["status"] == "error"
    assert "non-empty list" in result["message"]


def test_make_plan_phases_empty_list():
    """验证空列表拒绝（计划至少一个阶段）。

    空计划无意义，必须显式拒绝并提示 non-empty list。
    """
    result = json.loads(make_plan([]))
    assert result["status"] == "error"
    assert "non-empty list" in result["message"]


def test_make_plan_phases_json_string_success():
    """验证 phases 为 JSON 字符串（模型只输出 str 场景）创建成功。

    工具必须兼容 str 形态输入，结果与 dict 列表输入一致。
    """
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
    """参数化验证 JSON 字符串各非法形态。

    语法错误（not a JSON string）与解析成功但非列表（non-empty list）两类拒绝。
    """
    result = json.loads(make_plan(phases))
    assert result["status"] == "error"
    assert expected in result["message"]


def test_make_plan_phase_as_json_string():
    """验证元素为 JSON 字符串时解析成功。

    兼容模型输出 str 元素的场景，解析后按 dict 校验。
    """
    result = json.loads(make_plan([json.dumps(_phase(phase_id="e1"))]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_id"] == "e1"


def test_make_plan_phase_as_invalid_json_string():
    """验证元素为非法 JSON 字符串时明确拒绝。

    错误消息明确指向 JSON 解析失败，便于定位问题元素。
    """
    result = json.loads(make_plan(["abc"]))
    assert result["status"] == "error"
    assert "must be a valid JSON string" in result["message"]


@pytest.mark.parametrize("phase", [[1], 123, None, True])
def test_make_plan_phase_type_invalid(phase):
    """参数化验证元素为 list/int/None/bool 时拒绝。

    元素必须是 dict，其余类型统一报 must be a dict。
    """
    result = json.loads(make_plan([phase]))
    assert result["status"] == "error"
    assert "must be a dict" in result["message"]


def test_make_plan_phase_non_string_keys_rejected():
    """验证非字符串 key 拒绝。

    防止 sorted(extra) 对混合类型 key 排序时崩溃，须提前拦截。
    """
    result = json.loads(make_plan([{1: "x", "phase_id": "p1", "phase_name": "n",
                                    "phase_status": "pending", "phase_description": "d"}]))
    assert result["status"] == "error"
    assert "keys must be strings" in result["message"]


@pytest.mark.parametrize("field", ["phase_id", "phase_name", "phase_status", "phase_description"])
def test_make_plan_phase_missing_fields(field):
    """参数化验证缺任一必填字段拒绝。

    错误消息必须包含缺失字段名，便于调用方补全。
    """
    phase = _phase()
    del phase[field]
    result = json.loads(make_plan([phase]))
    assert result["status"] == "error"
    assert "missing required fields" in result["message"]
    assert field in result["message"]


def test_make_plan_phase_missing_multiple_reported():
    """验证缺多字段时全部列出。

    一次调用即可获知全部缺失字段，减少往返修正。
    """
    result = json.loads(make_plan([{"phase_id": "p1"}]))
    assert result["status"] == "error"
    for field in ("phase_name", "phase_status", "phase_description"):
        assert field in result["message"]


def test_make_plan_phase_extra_field_rejected():
    """验证额外字段拒绝。

    字段白名单契约，未知字段一律拒绝并点名。
    """
    result = json.loads(make_plan([_phase(extra_field=1)]))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "extra_field" in result["message"]


def test_make_plan_phase_multiple_extra_sorted():
    """验证多额外字段 sorted 列出。

    sorted 排序保证消息确定性，方便断言与回归。
    """
    result = json.loads(make_plan([_phase(x_field=1, a_field=2)]))
    assert result["status"] == "error"
    assert "['a_field', 'x_field']" in result["message"]


def test_make_plan_extra_checked_before_missing():
    """验证 extra 检查优先于 missing。

    同输入同时违例时只报 extra，检查顺序是稳定契约。
    """
    result = json.loads(make_plan([{"phase_id": "p1", "extra_field": 1}]))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "missing required" not in result["message"]


@pytest.mark.parametrize("phase_id", ["", "   ", 123, None, True])
def test_make_plan_phase_id_invalid(phase_id):
    """参数化验证 phase_id 为空/空白/非字符串/None/bool 拒绝。

    非空字符串是 id 的唯一合法形态（bool 是 int 子类需显式排除）。
    """
    result = json.loads(make_plan([_phase(phase_id=phase_id)]))
    assert result["status"] == "error"
    assert "phase_id must be a non-empty string" in result["message"]


@pytest.mark.parametrize("phase_name", ["", " ", 123, None])
def test_make_plan_phase_name_invalid(phase_name):
    """参数化验证 phase_name 为空/空白/非字符串/None 拒绝。

    名称与 id 一样必须是非空字符串。
    """
    result = json.loads(make_plan([_phase(phase_name=phase_name)]))
    assert result["status"] == "error"
    assert "phase_name must be a non-empty string" in result["message"]


@pytest.mark.parametrize("phase_description", ["", " ", 123, None])
def test_make_plan_phase_description_invalid(phase_description):
    """参数化验证 phase_description 为空/空白/非字符串/None 拒绝。

    描述与 id/name 一样必须是非空字符串。
    """
    result = json.loads(make_plan([_phase(phase_description=phase_description)]))
    assert result["status"] == "error"
    assert "phase_description must be a non-empty string" in result["message"]


@pytest.mark.parametrize("phase_status", [["pending"], {"a": 1}, 123, None, "donex", True])
def test_make_plan_phase_status_invalid(phase_status):
    """参数化验证 phase_status 非法形态拒绝。

    list/dict 等不可哈希输入须在集合成员判断前拦截，避免 TypeError。
    """
    result = json.loads(make_plan([_phase(phase_status=phase_status)]))
    assert result["status"] == "error"
    assert "phase_status must be one of" in result["message"]


@pytest.mark.parametrize("phase_status", ["pending", "in_progress", "done"])
def test_make_plan_phase_status_all_valid_values(phase_status):
    """参数化验证三个有效状态均通过且原值存储。

    pending/in_progress/done 全部放行，不做任何改写。
    """
    result = json.loads(make_plan([_phase(phase_status=phase_status)]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_status"] == phase_status


def test_make_plan_duplicate_phase_id_rejected():
    """验证完全重复 id 拒绝。

    重复 id 会破坏 edit/delete 的定位语义，必须在创建时拦截。
    """
    result = json.loads(make_plan([_phase(), _phase()]))
    assert result["status"] == "error"
    assert "duplicate phase_id: 'p1'" in result["message"]


def test_make_plan_duplicate_detected_after_strip():
    """验证 strip 后重复 id 拒绝。

    "p1" 与 " p1 " 归一化后视为同一 id，判重发生在 strip 之后。
    """
    result = json.loads(make_plan([_phase(), _phase(phase_id=" p1 ")]))
    assert result["status"] == "error"
    assert "duplicate phase_id: 'p1'" in result["message"]


def test_make_plan_duplicate_case_sensitive():
    """验证大小写不同不判重。

    id 比较大小写敏感，"p1" 与 "P1" 是两个合法阶段。
    """
    result = json.loads(make_plan([_phase(), _phase(phase_id="P1")]))
    assert result["status"] == "ok"
    assert len(result["plan"]) == 2


def test_make_plan_error_reports_phase_index():
    """验证错误消息定位 phase[i] 索引。

    错误消息包含问题阶段的位置，便于调用方快速定位。
    """
    result = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_status="bad")]))
    assert result["status"] == "error"
    assert "phase[1]" in result["message"]


def test_make_plan_second_phase_error_localization():
    """验证第二个阶段字段违例时索引为 phase[1]。

    索引定位准确不偏移，同时报告违例字段名。
    """
    result = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="")]))
    assert result["status"] == "error"
    assert "phase[1]" in result["message"]
    assert "phase_name" in result["message"]


def test_make_plan_existing_plan_rejected():
    """验证已有计划拒绝重建。

    existing_plan 非空时拒绝，防止并发场景 last-win 覆盖。
    """
    result = json.loads(make_plan([_phase()], existing_plan=[_phase(phase_id="old")]))
    assert result["status"] == "error"
    assert "already exists" in result["message"]


def test_make_plan_existing_plan_message_counts():
    """验证拒绝消息含已有阶段数。

    消息包含已有计划规模，帮助调用方决定是否先清空。
    """
    result = json.loads(make_plan(
        [_phase()], existing_plan=[_phase(phase_id="a"), _phase(phase_id="b")]))
    assert result["status"] == "error"
    assert "already exists (2 phases)" in result["message"]


def test_make_plan_existing_plan_empty_list_allowed():
    """验证空列表视为无计划。

    delete_all 清空后的 [] 可直接作为 existing_plan 重建。
    """
    result = json.loads(make_plan([_phase()], existing_plan=[]))
    assert result["status"] == "ok"


def test_make_plan_existing_plan_none_default():
    """验证默认 None（未传）放行创建。

    首次创建不传 existing_plan 是最常见路径。
    """
    result = json.loads(make_plan([_phase()]))
    assert result["status"] == "ok"


@pytest.mark.parametrize("existing_plan", ["[{}]", {"a": 1}, 123])
def test_make_plan_existing_plan_type_invalid(existing_plan):
    """参数化验证 existing_plan 为 str/dict/int 拒绝。

    类型防护：必须是 list 或 None，非法类型一律拒绝。
    """
    result = json.loads(make_plan([_phase()], existing_plan=existing_plan))
    assert result["status"] == "error"
    assert "must be a list or None" in result["message"]


def test_make_plan_lifecycle_reject_while_plan_exists():
    """生命周期：make 成功后未清空再 make 拒绝。

    编排层防双计划：existing_plan 非空时重建一律拒绝。
    """
    first = json.loads(make_plan([_phase()]))
    result = json.loads(make_plan([_phase(phase_id="new")], existing_plan=first["plan"]))
    assert result["status"] == "error"
    assert "already exists" in result["message"]


def test_make_plan_lifecycle_recreate_after_delete_all():
    """生命周期：make → delete_all 清空 → 重新 make 成功。

    清空后的空列表满足 existing_plan 放行条件，可无缝重建。
    """
    first = json.loads(make_plan([_phase()]))
    cleared = json.loads(delete_plan("p1", first["plan"], delete_all=True))
    result = json.loads(make_plan([_phase(phase_id="new")], existing_plan=cleared["plan"]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_id"] == "new"


def test_make_plan_lifecycle_make_edit_make_rejected():
    """混合：make → edit → 再 make 拒绝。

    编辑操作不解除防重建锁，只有清空后才允许重建。
    """
    made = json.loads(make_plan([_phase()]))
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    assert edited["status"] == "ok"
    result = json.loads(make_plan([_phase(phase_id="new")], existing_plan=edited["plan"]))
    assert result["status"] == "error"
    assert "already exists" in result["message"]


def test_make_plan_lifecycle_make_delete_partial_then_recreate():
    """混合：make → delete 部分 → make 拒绝 → delete 清空 → make 成功。

    删除部分阶段后计划仍非空，须全部清空才满足重建条件。
    """
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
    """混合完整链：make → edit → delete → delete_all → 重建。

    每一步的返回 plan 直接作为下一步输入，验证链式衔接。
    """
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
    """混合：make → edit 失败（原子失败不污染）→ delete 清空 → make 成功。

    原子失败不污染原 plan，后续操作可基于原快照继续。
    """
    made = json.loads(make_plan([_phase()]))
    failed = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "bad"}], made["plan"]))
    assert failed["status"] == "error"
    deleted = json.loads(delete_plan("p1", made["plan"]))
    assert deleted["plan"] == []
    recreated = json.loads(make_plan([_phase(phase_id="new")], existing_plan=deleted["plan"]))
    assert recreated["status"] == "ok"
    assert recreated["plan"][0]["phase_id"] == "new"


def test_make_plan_lifecycle_mixed_input_formats():
    """混合：dict 列表 make → JSON 字符串 edit → 常规 delete。

    跨输入形态链式衔接，模拟模型输出形态混用的真实场景。
    """
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    edited = json.loads(edit_plan(
        json.dumps([{"phase_id": "p2", "phase_status": "in_progress"}]), made["plan"]))
    assert edited["status"] == "ok"
    assert edited["plan"][1]["phase_status"] == "in_progress"
    deleted = json.loads(delete_plan("p2", edited["plan"]))
    assert deleted["status"] == "ok"
    assert [p["phase_id"] for p in deleted["plan"]] == ["p1"]
