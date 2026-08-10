"""edit_plan 全方面测试：参数校验、部分更新语义、副本语义、原子性、存在性校验与生命周期。

测试项目：
- test_edit_plan_update_name_success:               验证更新 phase_name 成功
- test_edit_plan_update_status_success:             验证更新 phase_status 成功
- test_edit_plan_update_description_success:        验证更新 phase_description 成功
- test_edit_plan_update_all_fields_success:         验证三字段同时更新
- test_edit_plan_multiple_phases_updated:           验证一次调用更新多个阶段
- test_edit_plan_same_phase_multiple_updates:       验证同阶段多次 update 顺序应用且计数去重
- test_edit_plan_unupdated_fields_kept:             验证未传字段保持不变（部分更新）
- test_edit_plan_original_plan_untouched:           验证副本语义：原 plan 不被修改
- test_edit_plan_update_id_with_spaces:             验证 update 的 phase_id strip 后匹配
- test_edit_plan_plan_id_with_spaces:               验证 plan 内 id 带空格也能匹配
- test_edit_plan_values_stripped_on_store:          验证 name/description strip 后存储
- test_edit_plan_status_requires_exact_value:       验证 status 集合精确匹配
- test_edit_plan_ok_message_lists_updated_ids:      验证 ok 消息列出更新 id
- test_edit_plan_ok_message_dedup_same_phase:       验证同阶段多 update 消息去重
- test_edit_plan_ok_message_order_matches_updates:  验证消息 id 顺序与 updates 一致
- test_edit_plan_ok_response_contract:              验证 ok 响应仅 status/message/plan 三字段
- test_edit_plan_error_response_has_no_plan:        验证 error 响应不含 plan 字段
- test_edit_plan_updates_empty_list:                验证空 updates 拒绝
- test_edit_plan_updates_type_invalid:              参数化验证 None/dict/int 拒绝
- test_edit_plan_updates_json_string_success:       验证 JSON 字符串输入成功
- test_edit_plan_updates_json_string_invalid:       参数化验证非法 JSON 字符串各形态拒绝
- test_edit_plan_update_element_type_invalid:       参数化验证元素非 dict 拒绝
- test_edit_plan_update_missing_phase_id:           验证 update 缺 phase_id 拒绝
- test_edit_plan_update_phase_id_invalid:           参数化验证 id 空/空白/非字符串/None 拒绝
- test_edit_plan_update_phase_id_only_rejected:     验证只传 phase_id 无更新字段拒绝
- test_edit_plan_update_extra_field_rejected:       验证额外字段拒绝
- test_edit_plan_update_multiple_extra_sorted:      验证多额外字段 sorted 列出
- test_edit_plan_update_rename_id_rejected:         验证试图改 phase_id 本身被拒（phase_id_new 是额外字段）
- test_edit_plan_update_non_string_key_rejected:    验证非字符串 key 拒绝
- test_edit_plan_update_status_invalid:             参数化验证 status 非法值/list/dict/int/None 拒绝
- test_edit_plan_update_status_message_format:      验证状态错误消息格式 "one of [...]"
- test_edit_plan_update_name_invalid:               参数化验证 name 空/空白/非字符串/None 拒绝
- test_edit_plan_update_description_invalid:        参数化验证 desc 空/空白/非字符串/None 拒绝
- test_edit_plan_plan_none_rejected:                验证 plan 为 None 拒绝
- test_edit_plan_plan_empty_rejected:               验证空 plan 拒绝
- test_edit_plan_plan_non_list_rejected:            参数化验证 plan 为 str/dict/int 拒绝
- test_edit_plan_plan_element_invalid:              参数化验证 plan 元素非 dict/缺 id/空 id/非字符串 id 拒绝
- test_edit_plan_phase_id_not_found:                验证不存在的 phase_id 拒绝
- test_edit_plan_one_invalid_update_aborts_all:     验证原子性：任一 update 非法整体失败
- test_edit_plan_failed_update_plan_untouched:      验证失败后原 plan 不被修改
- test_edit_plan_error_index_localization:          验证错误消息定位 updates[i]
- test_edit_plan_lifecycle_make_then_edit:          生命周期：make 后 edit 成功
- test_edit_plan_lifecycle_edit_after_edit:         生命周期：连续两次 edit 基于上次结果
- test_edit_plan_lifecycle_edit_deleted_phase:      生命周期：delete 后 edit 已删 id 拒绝
- test_edit_plan_lifecycle_edit_empty_after_delete_all: 生命周期：清空后 edit 拒绝
- test_edit_plan_lifecycle_make_edit_full_flow:     生命周期：make 3 阶段 → 一次 edit 2 个 update
- test_edit_plan_lifecycle_make_edit_delete_edit_remaining: 混合：make → edit → delete → 编辑剩余成功/已删拒绝
- test_edit_plan_lifecycle_atomic_failure_then_retry: 混合：edit 原子失败 → 修正后重试成功
- test_edit_plan_lifecycle_progress_all_phases:      混合：多轮 edit 将全部阶段状态推进到 done
- test_edit_plan_lifecycle_make_delete_edit_remaining: 混合：make → delete → 编辑剩余阶段成功
- test_edit_plan_lifecycle_rebuild_chain:            混合：make → edit → delete → 清空 → 重建 → edit 新阶段
- test_edit_plan_lifecycle_stale_snapshot_editable:  约定：旧快照仍可编辑（工具无状态，调用方传最新 plan）

覆盖场景：
- 参数校验：updates 非列表（None/dict/int）与空列表拒绝；元素非 dict（str/int/None/list）拒绝；缺/非法 phase_id 拒绝；只传 phase_id 无更新字段拒绝；额外字段与 phase_id_new 白名单拒绝；非字符串 key 拒绝（sorted 崩溃防护）；name/desc 空值、空白、非字符串、None 拒绝；status 集合精确匹配与不可哈希输入（list/dict/bool）拒绝（消息格式 one of [...]）
- 输入形态：updates 支持 dict 列表与 JSON 字符串；非法 JSON 各形态（语法错误/解析为 dict/null/空数组）拒绝
- 部分更新语义：单字段/多字段/三字段更新；同阶段多 update 顺序应用与计数去重；未传字段保持不变；消息 id 顺序与 updates 一致；name/description strip 后存储
- 存在性校验：plan None/空/非列表/坏元素拒绝（No plan exists 语义）；phase_id 不存在拒绝；错误消息定位 updates[i] 索引
- 副本与原子性：原 plan 永不被修改（成功/失败均不动）；任一 update 非法整体失败、合法部分不生效
- 生命周期混合链：make 后 edit；连续 edit 推进状态；delete 后 edit 已删 id 拒绝而剩余阶段可编辑；清空后 edit 拒绝；原子失败后可重试；重建后 edit 新阶段；旧快照仍可编辑（无状态快照约定）

测试用例数量：80
"""

import json

import pytest

from core.tools._kernel._plan import delete_plan, edit_plan, make_plan


def _phase(**overrides):
    """构造标准阶段字典，overrides 覆盖默认字段。"""
    phase = {
        "phase_id": "p1",
        "phase_name": "阶段一",
        "phase_status": "pending",
        "phase_description": "描述一",
    }
    phase.update(overrides)
    return phase


def _plan2():
    """标准两阶段计划。"""
    return [_phase(), _phase(phase_id="p2", phase_name="阶段二")]


def test_edit_plan_update_name_success():
    """验证更新 phase_name 成功且其余字段不变。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "新阶段一"}], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "新阶段一"
    assert result["plan"][0]["phase_status"] == "pending"
    assert result["plan"][1] == _phase(phase_id="p2", phase_name="阶段二")


def test_edit_plan_update_status_success():
    """验证更新 phase_status 成功。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "in_progress"}], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_status"] == "in_progress"


def test_edit_plan_update_description_success():
    """验证更新 phase_description 成功。"""
    result = json.loads(edit_plan([{"phase_id": "p2", "phase_description": "新描述"}], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][1]["phase_description"] == "新描述"


def test_edit_plan_update_all_fields_success():
    """验证三字段同时更新成功。"""
    update = {"phase_id": "p1", "phase_name": "新名", "phase_status": "done",
              "phase_description": "新描述"}
    result = json.loads(edit_plan([update], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "新名"
    assert result["plan"][0]["phase_status"] == "done"
    assert result["plan"][0]["phase_description"] == "新描述"


def test_edit_plan_multiple_phases_updated():
    """验证一次调用更新多个阶段（不同 phase_id）。"""
    result = json.loads(edit_plan([
        {"phase_id": "p1", "phase_status": "done"},
        {"phase_id": "p2", "phase_name": "阶段二改"},
    ], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_status"] == "done"
    assert result["plan"][1]["phase_name"] == "阶段二改"


def test_edit_plan_same_phase_multiple_updates():
    """验证同阶段多次 update 顺序应用且计数去重。"""
    result = json.loads(edit_plan([
        {"phase_id": "p1", "phase_name": "改名"},
        {"phase_id": "p1", "phase_status": "done"},
    ], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "改名"
    assert result["plan"][0]["phase_status"] == "done"
    assert result["message"] == "Updated 1 phase(s): p1."


def test_edit_plan_unupdated_fields_kept():
    """验证未传字段保持不变（部分更新语义）。"""
    result = json.loads(edit_plan([{"phase_id": "p2", "phase_status": "in_progress"}], _plan2()))
    assert result["plan"][1]["phase_name"] == "阶段二"
    assert result["plan"][1]["phase_description"] == "描述一"


def test_edit_plan_original_plan_untouched():
    """验证副本语义：更新后传入的原始 plan 不被修改。"""
    original = _plan2()
    edit_plan([{"phase_id": "p1", "phase_name": "改名"}], original)
    assert original[0]["phase_name"] == "阶段一"
    assert original == _plan2()


def test_edit_plan_update_id_with_spaces():
    """验证 update 的 phase_id strip 后匹配（" p1 " 命中 p1）。"""
    result = json.loads(edit_plan([{"phase_id": " p1 ", "phase_name": "改名"}], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "改名"


def test_edit_plan_plan_id_with_spaces():
    """验证 plan 内 id 带空格也能被 strip 后的 update id 命中。"""
    plan = [_phase(phase_id=" p1 "), _phase(phase_id="p2", phase_name="阶段二")]
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "改名"}], plan))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "改名"


def test_edit_plan_values_stripped_on_store():
    """验证 name/description 更新值 strip 后存储。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "  改名  ",
                                    "phase_description": "  新描述  "}], _plan2()))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_name"] == "改名"
    assert result["plan"][0]["phase_description"] == "新描述"


def test_edit_plan_status_requires_exact_value():
    """验证 status 集合精确匹配：带空白状态拒绝。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_status": " done "}], _plan2()))
    assert result["status"] == "error"
    assert "phase_status must be one of" in result["message"]


def test_edit_plan_ok_message_lists_updated_ids():
    """验证 ok 消息列出更新 id。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "a"}], _plan2()))
    assert result["message"] == "Updated 1 phase(s): p1."


def test_edit_plan_ok_message_dedup_same_phase():
    """验证同阶段多 update 消息去重计数（不重复列出 id）。"""
    result = json.loads(edit_plan([
        {"phase_id": "p1", "phase_name": "a"},
        {"phase_id": "p1", "phase_status": "done"},
    ], _plan2()))
    assert result["message"] == "Updated 1 phase(s): p1."


def test_edit_plan_ok_message_order_matches_updates():
    """验证消息 id 顺序与 updates 顺序一致。"""
    result = json.loads(edit_plan([
        {"phase_id": "p2", "phase_name": "a"},
        {"phase_id": "p1", "phase_status": "done"},
    ], _plan2()))
    assert result["message"] == "Updated 2 phase(s): p2, p1."


def test_edit_plan_ok_response_contract():
    """验证 ok 响应仅 status/message/plan 三字段（契约稳定性）。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "a"}], _plan2()))
    assert set(result.keys()) == {"status", "message", "plan"}


def test_edit_plan_error_response_has_no_plan():
    """验证 error 响应不含 plan 字段。"""
    result = json.loads(edit_plan([{"phase_id": "nope", "phase_name": "a"}], _plan2()))
    assert result["status"] == "error"
    assert "plan" not in result


def test_edit_plan_updates_empty_list():
    """验证空 updates 拒绝。"""
    result = json.loads(edit_plan([], _plan2()))
    assert result["status"] == "error"
    assert "non-empty list" in result["message"]


@pytest.mark.parametrize("updates", [None, {"a": 1}, 123])
def test_edit_plan_updates_type_invalid(updates):
    """参数化验证 updates 为 None/dict/int 拒绝。"""
    result = json.loads(edit_plan(updates, _plan2()))
    assert result["status"] == "error"
    assert "non-empty list" in result["message"]


def test_edit_plan_updates_json_string_success():
    """验证 updates 为 JSON 字符串（模型只输出 str 场景）更新成功。"""
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
    """参数化验证 JSON 字符串各非法形态：语法错误拒绝、解析成功但非列表拒绝。"""
    result = json.loads(edit_plan(updates, _plan2()))
    assert result["status"] == "error"
    assert expected in result["message"]


@pytest.mark.parametrize("update", ["x", 123, None, [1]])
def test_edit_plan_update_element_type_invalid(update):
    """参数化验证 update 元素为 str/int/None/list 拒绝。"""
    result = json.loads(edit_plan([update], _plan2()))
    assert result["status"] == "error"
    assert "must be a dict" in result["message"]


def test_edit_plan_update_missing_phase_id():
    """验证 update 缺 phase_id 拒绝。"""
    result = json.loads(edit_plan([{"phase_name": "x"}], _plan2()))
    assert result["status"] == "error"
    assert "missing 'phase_id'" in result["message"]


@pytest.mark.parametrize("phase_id", ["", "   ", 123, None])
def test_edit_plan_update_phase_id_invalid(phase_id):
    """参数化验证 update 的 phase_id 为空/空白/非字符串/None 拒绝。"""
    result = json.loads(edit_plan([{"phase_id": phase_id, "phase_name": "x"}], _plan2()))
    assert result["status"] == "error"
    assert "phase_id must be a non-empty string" in result["message"]


def test_edit_plan_update_phase_id_only_rejected():
    """验证只传 phase_id（无更新字段）拒绝。"""
    result = json.loads(edit_plan([{"phase_id": "p1"}], _plan2()))
    assert result["status"] == "error"
    assert "no fields to update" in result["message"]


def test_edit_plan_update_extra_field_rejected():
    """验证额外字段拒绝（白名单契约）。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_extra": 1}], _plan2()))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "phase_extra" in result["message"]


def test_edit_plan_update_multiple_extra_sorted():
    """验证多额外字段 sorted 列出（消息确定性）。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "z_field": 1, "a_field": 2}], _plan2()))
    assert result["status"] == "error"
    assert "['a_field', 'z_field']" in result["message"]


def test_edit_plan_update_rename_id_rejected():
    """验证试图改 phase_id 本身被拒：phase_id 是定位键，新 id 字段属额外字段。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_id_new": "p9"}], _plan2()))
    assert result["status"] == "error"
    assert "unknown fields" in result["message"]
    assert "phase_id_new" in result["message"]


def test_edit_plan_update_non_string_key_rejected():
    """验证非字符串 key 拒绝（sorted(extra) 崩溃防护）。"""
    result = json.loads(edit_plan([{"phase_id": "p1", 1: "x"}], _plan2()))
    assert result["status"] == "error"
    assert "keys must be strings" in result["message"]


@pytest.mark.parametrize("phase_status", [["done"], {"a": 1}, 123, None, "donex", True])
def test_edit_plan_update_status_invalid(phase_status):
    """参数化验证 status 为 list/dict/int/None/非法值/bool 拒绝（不可哈希防护）。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_status": phase_status}], _plan2()))
    assert result["status"] == "error"
    assert "phase_status must be one of" in result["message"]


def test_edit_plan_update_status_message_format():
    """验证状态错误消息格式："one of [...], got 'x'."（空格分隔）。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "xxx"}], _plan2()))
    assert result["status"] == "error"
    assert "one of ['done', 'in_progress', 'pending'], got 'xxx'" in result["message"]


@pytest.mark.parametrize("phase_name", ["", " ", 123, None])
def test_edit_plan_update_name_invalid(phase_name):
    """参数化验证 name 为空/空白/非字符串/None 拒绝。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": phase_name}], _plan2()))
    assert result["status"] == "error"
    assert "phase_name must be a non-empty string" in result["message"]


@pytest.mark.parametrize("phase_description", ["", " ", 123, None])
def test_edit_plan_update_description_invalid(phase_description):
    """参数化验证 desc 为空/空白/非字符串/None 拒绝。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_description": phase_description}], _plan2()))
    assert result["status"] == "error"
    assert "phase_description must be a non-empty string" in result["message"]


def test_edit_plan_plan_none_rejected():
    """验证 plan 为 None 拒绝。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], None))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


def test_edit_plan_plan_empty_rejected():
    """验证空 plan 拒绝（须先 make_plan）。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], []))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


@pytest.mark.parametrize("plan", ["[{}]", {"a": 1}, 123])
def test_edit_plan_plan_non_list_rejected(plan):
    """参数化验证 plan 为 str/dict/int 拒绝（类型防护）。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], plan))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


@pytest.mark.parametrize("plan", [["abc"], [{"phase_name": "x"}], [{"phase_id": "  "}], [{"phase_id": 1}]])
def test_edit_plan_plan_element_invalid(plan):
    """参数化验证 plan 元素非 dict/缺 id/空 id/非字符串 id 拒绝。"""
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], plan))
    assert result["status"] == "error"
    assert "plan[0] must be a dict with a non-empty string phase_id" in result["message"]


def test_edit_plan_phase_id_not_found():
    """验证不存在的 phase_id 拒绝（带合法更新字段才能触达存在性检查）。"""
    result = json.loads(edit_plan([{"phase_id": "nope", "phase_name": "x"}], _plan2()))
    assert result["status"] == "error"
    assert "phase_id 'nope' not found in plan" in result["message"]


def test_edit_plan_one_invalid_update_aborts_all():
    """验证原子性：任一 update 非法整体失败，合法部分不生效且原 plan 不变。"""
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
    """验证校验失败后原 plan 不被修改（副本在检查通过后才创建）。"""
    original = _plan2()
    edit_plan([{"phase_id": "p1", "phase_status": "bad"}], original)
    assert original == _plan2()


def test_edit_plan_error_index_localization():
    """验证错误消息定位 updates[i] 索引。"""
    result = json.loads(edit_plan([
        {"phase_id": "p1", "phase_name": "a"},
        {"phase_id": "p2", "phase_status": "bad"},
    ], _plan2()))
    assert result["status"] == "error"
    assert "updates[1]" in result["message"]


def test_edit_plan_lifecycle_make_then_edit():
    """生命周期：make 创建的 plan 可直接 edit。"""
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    result = json.loads(edit_plan([{"phase_id": "p2", "phase_status": "in_progress"}], made["plan"]))
    assert result["status"] == "ok"
    assert result["plan"][1]["phase_status"] == "in_progress"


def test_edit_plan_lifecycle_edit_after_edit():
    """生命周期：连续两次 edit 基于上次结果推进状态。"""
    made = json.loads(make_plan([_phase()]))
    once = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "in_progress"}], made["plan"]))
    twice = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], once["plan"]))
    assert twice["status"] == "ok"
    assert twice["plan"][0]["phase_status"] == "done"


def test_edit_plan_lifecycle_edit_deleted_phase():
    """生命周期：delete 后 edit 已删 id 拒绝。"""
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    deleted = json.loads(delete_plan("p2", made["plan"]))
    result = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "x"}], deleted["plan"]))
    assert result["status"] == "error"
    assert "not found" in result["message"]


def test_edit_plan_lifecycle_edit_empty_after_delete_all():
    """生命周期：delete_all 清空后 edit 拒绝（无计划可编辑）。"""
    made = json.loads(make_plan([_phase()]))
    cleared = json.loads(delete_plan("p1", made["plan"], delete_all=True))
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], cleared["plan"]))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


def test_edit_plan_lifecycle_make_edit_full_flow():
    """生命周期：make 3 阶段 → 一次 edit 2 个 update（不同阶段）全部生效。"""
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
    """混合：make → edit → delete → 编辑剩余阶段成功、编辑已删 id 拒绝（同一快照内对照）。"""
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
    """混合：edit 原子失败后 plan 状态未被污染，修正后基于原快照重试成功。"""
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
    """混合：多轮 edit 将全部阶段状态逐步推进到 done（状态机轮转）。"""
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
    """混合：make → delete → 编辑剩余阶段成功（无 edit 中间步的对照链）。"""
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    deleted = json.loads(delete_plan("p2", made["plan"]))
    assert deleted["status"] == "ok"
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], deleted["plan"]))
    assert result["status"] == "ok"
    assert result["plan"][0]["phase_status"] == "done"
    assert result["message"] == "Updated 1 phase(s): p1."


def test_edit_plan_lifecycle_rebuild_chain():
    """混合：make → edit → delete → 清空 → 重建 → edit 新阶段（edit 视角完整闭环）。"""
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
    """约定：plan 工具无内部状态，旧快照仍可编辑；调用方必须传递最新 plan。"""
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    deleted = json.loads(delete_plan("p2", made["plan"]))
    assert [p["phase_id"] for p in deleted["plan"]] == ["p1"]
    # 旧快照（make 的结果）中 p2 仍存在，基于旧快照编辑 p2 会成功
    stale = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "旧快照改名"}], made["plan"]))
    assert stale["status"] == "ok"
    assert stale["plan"][1]["phase_name"] == "旧快照改名"
    # 最新快照中 p2 已删，编辑 p2 拒绝
    fresh = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "x"}], deleted["plan"]))
    assert fresh["status"] == "error"
    assert "not found" in fresh["message"]
