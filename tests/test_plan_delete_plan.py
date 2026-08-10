"""delete_plan 全方面测试：删除语义、delete_all 类型防护、副本语义、存在性校验与完整生命周期。

测试项目：
- test_delete_plan_single_phase:                    验证删除单阶段成功
- test_delete_plan_middle_phase_order_kept:         验证删除中间阶段后顺序保持
- test_delete_plan_last_remaining_phase:            验证删除最后一个阶段 plan 为空
- test_delete_plan_id_with_spaces:                  验证 phase_id strip 后匹配删除
- test_delete_plan_plan_id_with_spaces:             验证 plan 内 id 带空格也能删除
- test_delete_plan_message_reports_id:              验证 ok 消息报告删除的 id
- test_delete_plan_original_plan_untouched:         验证副本语义：原 plan 不被修改
- test_delete_plan_remaining_phases_intact:         验证剩余阶段字段完整
- test_delete_plan_duplicate_ids_all_removed:       验证手工 plan 含重复 id 时全部删除
- test_delete_plan_delete_all_clears:               验证 delete_all 清空全部阶段
- test_delete_plan_delete_all_empty_plan_idempotent:验证 delete_all 清空空计划幂等
- test_delete_plan_delete_all_ignores_phase_id:     验证 delete_all 时 phase_id 被忽略
- test_delete_plan_delete_all_message:              验证清空消息 "All phases deleted."
- test_delete_plan_delete_all_response_contract:    验证清空响应 plan 为空列表
- test_delete_plan_delete_all_string_false_rejected:验证 delete_all="false" 拒绝（防误清空）
- test_delete_plan_delete_all_string_true_rejected: 验证 delete_all="True" 拒绝
- test_delete_plan_delete_all_int_rejected:         参数化验证 delete_all=1/0 拒绝
- test_delete_plan_delete_all_none_rejected:        验证 delete_all=None 拒绝
- test_delete_plan_delete_all_list_rejected:        验证 delete_all=[] 拒绝
- test_delete_plan_delete_all_non_bool_error_first: 验证非 bool 时优先报错且不执行删除
- test_delete_plan_phase_id_invalid:                参数化验证空/空白/非字符串/None/bool id 拒绝
- test_delete_plan_plan_none_rejected:              验证 plan 为 None 拒绝
- test_delete_plan_plan_non_list_rejected:          参数化验证 plan 为 str/dict/int 拒绝
- test_delete_plan_plan_empty_rejected:             验证空 plan 拒绝（须先 make_plan）
- test_delete_plan_plan_element_invalid:            参数化验证 plan 元素非 dict/缺 id/空 id/非字符串 id 拒绝
- test_delete_plan_delete_all_plan_non_list_rejected: 验证 delete_all 下 plan 非列表也拒绝（防谎报清空）
- test_delete_plan_delete_all_plan_bad_element_clears: 验证 delete_all 下坏元素 plan 仍可清空（元素校验跳过）
- test_delete_plan_not_found:                       验证不存在的 phase_id 拒绝
- test_delete_plan_not_found_plan_untouched:        验证 not found 时原 plan 不被修改
- test_delete_plan_error_response_has_no_plan:      验证 error 响应不含 plan 字段
- test_delete_plan_ok_response_contract:            验证 ok 响应仅 status/message/plan 三字段
- test_delete_plan_lifecycle_make_delete_recreate:  生命周期：make → delete 单阶段 → 重新 make
- test_delete_plan_lifecycle_delete_twice_not_found:生命周期：连续 delete 同一 id 第二次拒绝
- test_delete_plan_lifecycle_make_edit_delete_edit: 生命周期：make → edit → delete → edit 已删 id 拒绝
- test_delete_plan_lifecycle_delete_all_then_make:  生命周期：delete_all 后重新 make 成功
- test_delete_plan_lifecycle_full_flow:             生命周期：make → edit → delete → 清空 → 重建 → edit
- test_delete_plan_lifecycle_delete_all_then_edit:  生命周期：清空后 edit 拒绝
- test_delete_plan_lifecycle_delete_all_then_delete:生命周期：清空后 delete 拒绝
- test_delete_plan_lifecycle_make_edit_delete_delete_again: 混合：make → edit → delete → 再 delete 同 id 拒绝
- test_delete_plan_lifecycle_edit_failed_then_delete: 混合：edit 失败（原子性）→ delete 仍可执行
- test_delete_plan_lifecycle_delete_then_edit_remaining: 混合：delete → 编辑剩余成功、编辑已删拒绝（对照）
- test_delete_plan_lifecycle_delete_until_empty_then_error: 混合：逐个删除至清空 → 继续 delete 报 No plan exists
- test_delete_plan_lifecycle_stale_snapshot_deletable: 约定：旧快照仍可删除；必须传最新快照给 make
- test_delete_plan_lifecycle_delete_view_full_chain:  混合完整链：make → edit → delete → edit 拒绝 → 清空 → 重建 → delete

覆盖场景：
- 参数校验：phase_id 空/空白/非字符串/None/bool 拒绝；plan None/非列表/空/坏元素拒绝（No plan exists 语义）；错误消息报告未找到 id
- delete_all 防护：True 清空（忽略 phase_id、坏元素 plan 仍可清空、消息 All phases deleted.）；"false"/"True"/1/0/None/[] 等非严格布尔一律拒绝（防误清空）；非 bool 优先报错且不执行任何删除；plan 非列表时拒绝谎报清空
- 删除语义：单阶段/中间阶段/末阶段删除；剩余顺序保持；重复 id 全部删除；id 与 plan 内 id 均 strip 后匹配；剩余阶段字段完整；消息报告删除 id
- 副本语义：删除后原 plan 不被修改；not found 时原 plan 不被修改
- 响应契约：ok 仅 status/message/plan 三字段；error 不含 plan
- 生命周期混合链：make → delete 清空 → 重建；连续 delete 第二次 not found；delete 后编辑剩余成功/已删拒绝；edit 失败不阻塞 delete；逐个删除至清空后再删报错；清空后 edit/delete 拒绝；旧快照仍可删除（无状态约定）；make → edit → delete → 清空 → 重建 → edit/delete 完整闭环

测试用例数量：54
"""

import json

import pytest

from core.tools._kernel._plan import delete_plan, edit_plan, make_plan
from tests.helpers import _phase, _plan3


def test_delete_plan_single_phase():
    """验证删除单阶段成功。

    plan 减少且不含已删 id，响应状态为 ok。
    """
    result = json.loads(delete_plan("p2", _plan3()))
    assert result["status"] == "ok"
    assert [p["phase_id"] for p in result["plan"]] == ["p1", "p3"]


def test_delete_plan_middle_phase_order_kept():
    """验证删除中间阶段后剩余顺序保持。

    删除不做任何重排，剩余阶段保持原有相对顺序。
    """
    result = json.loads(delete_plan("p2", _plan3()))
    assert result["plan"][0]["phase_id"] == "p1"
    assert result["plan"][1]["phase_id"] == "p3"


def test_delete_plan_last_remaining_phase():
    """验证删除最后一个阶段后 plan 为空列表。

    清空后的 [] 可作为 make 重建的 existing_plan。
    """
    result = json.loads(delete_plan("p1", [_phase()]))
    assert result["status"] == "ok"
    assert result["plan"] == []


def test_delete_plan_id_with_spaces():
    """验证 phase_id 带首尾空白 strip 后匹配删除。

    " p2 " 等带空白 id 归一化后命中 p2。
    """
    result = json.loads(delete_plan(" p2 ", _plan3()))
    assert result["status"] == "ok"
    assert [p["phase_id"] for p in result["plan"]] == ["p1", "p3"]


def test_delete_plan_plan_id_with_spaces():
    """验证 plan 内 id 带空格也能被删除。

    匹配双方均做 strip 归一化，兼容任意一侧带空白。
    """
    plan = [_phase(phase_id=" p1 "), _phase(phase_id="p2", phase_name="阶段二")]
    result = json.loads(delete_plan("p1", plan))
    assert result["status"] == "ok"
    assert [p["phase_id"] for p in result["plan"]] == ["p2"]


def test_delete_plan_message_reports_id():
    """验证 ok 消息报告删除的 id。

    消息格式 "Phase 'id' deleted." 是响应契约的一部分。
    """
    result = json.loads(delete_plan("p2", _plan3()))
    assert result["message"] == "Phase 'p2' deleted."


def test_delete_plan_original_plan_untouched():
    """验证副本语义：删除后传入的原始 plan 不被修改。

    工具在副本上操作，调用方持有的 plan 必须保持原样。
    """
    original = _plan3()
    delete_plan("p2", original)
    assert original == _plan3()


def test_delete_plan_remaining_phases_intact():
    """验证剩余阶段字段完整。

    删除只移除目标阶段，剩余阶段的 name/status/description 无损失。
    """
    result = json.loads(delete_plan("p2", _plan3()))
    assert result["plan"][0] == _phase()
    assert result["plan"][1] == _phase(phase_id="p3", phase_name="阶段三")


def test_delete_plan_duplicate_ids_all_removed():
    """验证手工 plan 含重复 id 时全部删除。

    过滤语义：所有匹配该 id 的阶段一并移除。
    """
    plan = [_phase(), _phase(), _phase(phase_id="p2", phase_name="阶段二")]
    result = json.loads(delete_plan("p1", plan))
    assert result["status"] == "ok"
    assert [p["phase_id"] for p in result["plan"]] == ["p2"]


def test_delete_plan_delete_all_clears():
    """验证 delete_all 清空全部阶段。

    delete_all=True 时忽略 phase_id，结果恒为空列表。
    """
    result = json.loads(delete_plan("p1", _plan3(), delete_all=True))
    assert result["status"] == "ok"
    assert result["plan"] == []


def test_delete_plan_delete_all_empty_plan_idempotent():
    """验证 delete_all 清空空计划幂等。

    对空计划清空仍返回 ok，而非报错。
    """
    result = json.loads(delete_plan("p1", [], delete_all=True))
    assert result["status"] == "ok"
    assert result["plan"] == []


def test_delete_plan_delete_all_ignores_phase_id():
    """验证 delete_all 时 phase_id 被忽略。

    即使 phase_id 非法（如 123）也不影响清空执行。
    """
    result = json.loads(delete_plan(123, _plan3(), delete_all=True))
    assert result["status"] == "ok"
    assert result["plan"] == []


def test_delete_plan_delete_all_message():
    """验证清空消息为 "All phases deleted."。

    清空路径使用独立消息文案，与单阶段删除区分。
    """
    result = json.loads(delete_plan("p1", _plan3(), delete_all=True))
    assert result["message"] == "All phases deleted."


def test_delete_plan_delete_all_response_contract():
    """验证清空响应 plan 字段为空列表。

    响应仍为 status/message/plan 三字段，[] 可直接作为 existing_plan 重建。
    """
    result = json.loads(delete_plan("p1", _plan3(), delete_all=True))
    assert set(result.keys()) == {"status", "message", "plan"}
    assert result["plan"] == []


def test_delete_plan_delete_all_string_false_rejected():
    """验证 delete_all="false" 拒绝。

    字符串 truthy 陷阱："false" 语义为假但必须按类型拒绝，防误清空整个计划。
    """
    result = json.loads(delete_plan("p1", _plan3(), delete_all="false"))
    assert result["status"] == "error"
    assert "delete_all must be a boolean" in result["message"]


def test_delete_plan_delete_all_string_true_rejected():
    """验证 delete_all="True" 拒绝。

    字符串不因语义等价而放行，严格布尔类型检查。
    """
    result = json.loads(delete_plan("p1", _plan3(), delete_all="True"))
    assert result["status"] == "error"
    assert "delete_all must be a boolean" in result["message"]


@pytest.mark.parametrize("delete_all", [1, 0])
def test_delete_plan_delete_all_int_rejected(delete_all):
    """参数化验证 delete_all=1/0 拒绝。

    bool 是 int 子类，必须严格布尔类型检查排除 1/0。
    """
    result = json.loads(delete_plan("p1", _plan3(), delete_all=delete_all))
    assert result["status"] == "error"
    assert "delete_all must be a boolean" in result["message"]


def test_delete_plan_delete_all_none_rejected():
    """验证 delete_all=None 拒绝。

    None 不是合法布尔，必须显式拒绝而非默认 False。
    """
    result = json.loads(delete_plan("p1", _plan3(), delete_all=None))
    assert result["status"] == "error"
    assert "delete_all must be a boolean" in result["message"]


def test_delete_plan_delete_all_list_rejected():
    """验证 delete_all=[] 拒绝。

    空列表 truthy 为 False，属歧义输入，必须按类型拒绝。
    """
    result = json.loads(delete_plan("p1", _plan3(), delete_all=[]))
    assert result["status"] == "error"
    assert "delete_all must be a boolean" in result["message"]


def test_delete_plan_delete_all_non_bool_error_first():
    """验证 delete_all 非 bool 时优先报错且不执行任何删除。

    类型校验先于删除逻辑，plan 保持原样。
    """
    plan = _plan3()
    result = json.loads(delete_plan("p2", plan, delete_all="false"))
    assert result["status"] == "error"
    assert [p["phase_id"] for p in plan] == ["p1", "p2", "p3"]


@pytest.mark.parametrize("phase_id", ["", "   ", 123, None, True])
def test_delete_plan_phase_id_invalid(phase_id):
    """参数化验证 phase_id 为空/空白/非字符串/None/bool 拒绝。

    非空字符串是 id 的唯一合法形态（bool 是 int 子类需显式排除）。
    """
    result = json.loads(delete_plan(phase_id, _plan3()))
    assert result["status"] == "error"
    assert "phase_id must be a non-empty string" in result["message"]


def test_delete_plan_plan_none_rejected():
    """验证 plan 为 None 拒绝。

    类型防护：报 plan must be a list，而非 No plan exists。
    """
    result = json.loads(delete_plan("p1", None))
    assert result["status"] == "error"
    assert "plan must be a list" in result["message"]


@pytest.mark.parametrize("plan", ["[{}]", {"a": 1}, 123])
def test_delete_plan_plan_non_list_rejected(plan):
    """参数化验证 plan 为 str/dict/int 拒绝。

    类型防护：非列表输入一律拒绝。
    """
    result = json.loads(delete_plan("p1", plan))
    assert result["status"] == "error"
    assert "plan must be a list" in result["message"]


def test_delete_plan_plan_empty_rejected():
    """验证空 plan 拒绝（须先 make_plan）。

    空计划无可删除对象，报 No plan exists。
    """
    result = json.loads(delete_plan("p1", []))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


@pytest.mark.parametrize("plan", [["abc"], [{"phase_name": "x"}], [{"phase_id": "  "}], [{"phase_id": 1}]])
def test_delete_plan_plan_element_invalid(plan):
    """参数化验证 plan 元素非 dict/缺 id/空 id/非字符串 id 拒绝。

    元素校验消息定位 plan[i]，保证可诊断性。
    """
    result = json.loads(delete_plan("p1", plan))
    assert result["status"] == "error"
    assert "plan[0] must be a dict with a non-empty string phase_id" in result["message"]


def test_delete_plan_delete_all_plan_non_list_rejected():
    """验证 delete_all=True 下 plan 非列表也拒绝。

    防止谎报清空成功：类型校验在 delete_all 分支同样生效。
    """
    result = json.loads(delete_plan("p1", "garbage", delete_all=True))
    assert result["status"] == "error"
    assert "plan must be a list" in result["message"]


def test_delete_plan_delete_all_plan_bad_element_clears():
    """验证 delete_all 下坏元素 plan 仍可清空。

    元素校验在 delete_all 之后，语义上全删无所谓元素合法性。
    """
    result = json.loads(delete_plan("p1", [123, "abc"], delete_all=True))
    assert result["status"] == "ok"
    assert result["plan"] == []


def test_delete_plan_not_found():
    """验证不存在的 phase_id 拒绝。

    错误消息报告未找到的 id，便于调用方诊断。
    """
    result = json.loads(delete_plan("nope", _plan3()))
    assert result["status"] == "error"
    assert "phase_id 'nope' not found in plan" in result["message"]


def test_delete_plan_not_found_plan_untouched():
    """验证 not found 时原 plan 不被修改。

    失败路径完全不触碰调用方数据。
    """
    original = _plan3()
    delete_plan("nope", original)
    assert original == _plan3()


def test_delete_plan_error_response_has_no_plan():
    """验证 error 响应不含 plan 字段。

    失败时不返回 plan，避免调用方误把失败结果当有效数据。
    """
    result = json.loads(delete_plan("nope", _plan3()))
    assert result["status"] == "error"
    assert "plan" not in result


def test_delete_plan_ok_response_contract():
    """验证 ok 响应仅 status/message/plan 三字段。

    字段集合必须精确等于三字段，防止未来新增字段破坏契约。
    """
    result = json.loads(delete_plan("p2", _plan3()))
    assert set(result.keys()) == {"status", "message", "plan"}


def test_delete_plan_lifecycle_make_delete_recreate():
    """生命周期：make → delete 全部阶段（plan 清空）→ 重新 make 新计划成功。

    逐个删除至清空后满足重建条件，新计划使用全新 id。
    """
    made = json.loads(make_plan([_phase()]))
    deleted = json.loads(delete_plan("p1", made["plan"]))
    assert deleted["plan"] == []
    recreated = json.loads(make_plan([_phase(phase_id="new")], existing_plan=deleted["plan"]))
    assert recreated["status"] == "ok"
    assert recreated["plan"][0]["phase_id"] == "new"


def test_delete_plan_lifecycle_delete_twice_not_found():
    """生命周期：连续 delete 同一 id，第二次拒绝。

    plan 仍非空时触达 not found 检查（区别于空计划检查）。
    """
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    first = json.loads(delete_plan("p1", made["plan"]))
    assert first["status"] == "ok"
    second = json.loads(delete_plan("p1", first["plan"]))
    assert second["status"] == "error"
    assert "not found" in second["message"]


def test_delete_plan_lifecycle_make_edit_delete_edit():
    """生命周期：make → edit → delete → 再 edit 已删 id 拒绝。

    编辑的 done 状态在删除后仍保留于剩余阶段，链式操作状态无丢失。
    """
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    deleted = json.loads(delete_plan("p2", edited["plan"]))
    result = json.loads(edit_plan([{"phase_id": "p2", "phase_name": "x"}], deleted["plan"]))
    assert result["status"] == "error"
    assert "not found" in result["message"]
    assert deleted["plan"][0]["phase_status"] == "done"


def test_delete_plan_lifecycle_delete_all_then_make():
    """生命周期：delete_all 清空后重新 make 成功。

    清空后的空列表满足 existing_plan 放行条件。
    """
    made = json.loads(make_plan([_phase()]))
    cleared = json.loads(delete_plan("p1", made["plan"], delete_all=True))
    recreated = json.loads(make_plan([_phase(phase_id="new")], existing_plan=cleared["plan"]))
    assert recreated["status"] == "ok"
    assert recreated["plan"][0]["phase_id"] == "new"


def test_delete_plan_lifecycle_full_flow():
    """完整生命周期：make 3 → edit p1 done → delete p2 → delete_all → 重建 → edit 新阶段。

    验证三工具链式衔接：每一步的返回 plan 直接作为下一步输入。
    """
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
    """生命周期：清空后 edit 拒绝。

    无计划可编辑时统一报 No plan exists。
    """
    made = json.loads(make_plan([_phase()]))
    cleared = json.loads(delete_plan("p1", made["plan"], delete_all=True))
    result = json.loads(edit_plan([{"phase_id": "p1", "phase_name": "x"}], cleared["plan"]))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


def test_delete_plan_lifecycle_delete_all_then_delete():
    """生命周期：清空后 delete 拒绝。

    无计划可删除时统一报 No plan exists。
    """
    made = json.loads(make_plan([_phase()]))
    cleared = json.loads(delete_plan("p1", made["plan"], delete_all=True))
    result = json.loads(delete_plan("p1", cleared["plan"]))
    assert result["status"] == "error"
    assert "No plan exists" in result["message"]


def test_delete_plan_lifecycle_make_edit_delete_delete_again():
    """混合：make → edit → delete → 再 delete 同一 id 拒绝。

    plan 仍非空时第二次删除报 not found。
    """
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    edited = json.loads(edit_plan([{"phase_id": "p1", "phase_status": "done"}], made["plan"]))
    first = json.loads(delete_plan("p1", edited["plan"]))
    assert first["status"] == "ok"
    assert first["message"] == "Phase 'p1' deleted."
    second = json.loads(delete_plan("p1", first["plan"]))
    assert second["status"] == "error"
    assert "not found" in second["message"]


def test_delete_plan_lifecycle_edit_failed_then_delete():
    """混合：edit 原子失败后 delete 仍可正常执行。

    错误不阻塞后续操作，原快照保持完整可用。
    """
    made = json.loads(make_plan([_phase(), _phase(phase_id="p2", phase_name="阶段二")]))
    failed = json.loads(edit_plan([{"phase_id": "p2", "phase_status": "bad"}], made["plan"]))
    assert failed["status"] == "error"
    deleted = json.loads(delete_plan("p2", made["plan"]))
    assert deleted["status"] == "ok"
    assert [p["phase_id"] for p in deleted["plan"]] == ["p1"]


def test_delete_plan_lifecycle_delete_then_edit_remaining():
    """混合：delete → 编辑剩余阶段成功、编辑已删 id 拒绝。

    同一快照内对照验证：删除后剩余阶段可编辑，已删 id 报 not found。
    """
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
    """混合：逐个 delete 直至清空，清空后继续 delete 报 No plan exists。

    清空后 plan 为空，删除操作从 not found 语义切换为无计划语义。
    """
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
    """约定：plan 工具无内部状态，旧快照仍可删除。

    make 必须收到最新快照：非空快照（即使最新）拒绝重建，清空后才放行。
    """
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
    """混合完整链（delete 视角）：make → edit → delete → edit 拒绝 → 清空 → 重建 → delete 新阶段。

    delete 视角完整闭环，最终删除新计划后 plan 为空。
    """
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
