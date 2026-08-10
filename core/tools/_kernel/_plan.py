"""Agent 执行计划管理工具实现

提供函数：
- make_plan:        从阶段列表中创建新的执行计划
- edit_plan:        修改计划中的一个或多个阶段
- delete_plan:      移除一个阶段或清空整个计划

关键约束：
- 所有工具统一返回 JSON 字符串（status: ok/error），不抛异常
- 纯内存操作：不触碰文件系统、无 IO 无锁，plan 由调用方持有并每次传入，
  工具不保存任何内部状态
- 不修改传入的 plan：edit/delete 均在副本上操作，原始计划不被污染
- phase_id 为身份字段：strip 归一化后判重（make）与匹配（edit/delete），
  edit 不可修改它；plan 元素须为含非空字符串 phase_id 的字典
- 字段白名单：make 要求 4 必填字段且拒绝额外字段；edit 仅允许
  phase_name/phase_status/phase_description，只传 phase_id 拒绝
- 状态机约束：phase_status 仅限 pending/in_progress/done（frozenset 常量）
- 资源上限：PLAN_MAX_PHASES（12 阶段）；阶段 ID 重复拒绝；
  existing_plan 非空时拒绝重建（防并发 last-win）
- 类型防护：delete_all 必须为 bool（字符串 "false" 是 truthy，误传会清空
  整个计划）；非字符串 key 与不可哈希值（list/dict）结构化拒绝
- 幂等语义：delete_all 清空空计划返回 ok；清空后才可重新 make_plan

使用注意：
- phases/updates 参数支持 JSON 字符串输入（兼容只能输出 str 的模型），
  解析失败返回 error；解析结果仍走完整列表校验
- 生命周期：make_plan → edit_plan/delete_plan（多次）→
  delete_plan(delete_all=True) 清空后可重新 make_plan
- edit_plan 为部分更新语义：只校验并应用传入字段，未传字段保持不变；
  字段校验优先于 phase_id 存在性校验（先格式后业务）
- 错误消息携带定位索引：phase[i]（make）、updates[i]（edit）、
  plan[j]（plan 结构校验）
"""

import json

from core.tools._kernel.constants import (
    PLAN_MAX_PHASES,
    PHASE_VALID_STATUSES,
    PHASE_REQUIRED_FIELDS,
    PHASE_ALLOWED_UPDATE_FIELDS,
)


def make_plan(
    phases: list[dict],
    existing_plan: list[dict] | None = None,
) -> str:
    """从阶段列表创建新的执行计划。

    每个阶段必须包含 phase_id、phase_name、phase_status 与
    phase_description 字段；重复 ID 会被拒绝；最多 12 个阶段。

    Args:
        phases: 含必填字段的阶段字典列表。

    Returns:
        带 status 与校验后计划的 JSON 字符串。
    """
    # 防止重复创建计划，如果已存在计划则返回错误，拒绝 并发 last-win
    if existing_plan is not None and not isinstance(existing_plan, list):
        return json.dumps({
            "status": "error",
            "message": "existing_plan must be a list or None.",
        }, ensure_ascii=False)

    if existing_plan:
        return json.dumps({
            "status": "error",
            "message": f"Plan already exists ({len(existing_plan)} phases). "
                    + "Use edit_plan to update, or delete_plan(delete_all=True) to clear and recreate.",
        }, ensure_ascii=False)

    # 把 phases 转换为列表
    if isinstance(phases, str):
        try:
            phases = json.loads(phases)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({
                "status": "error",
                "message": "Invalid phases: not a JSON string.",
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Invalid phases: {e}",
            }, ensure_ascii=False)

    # 检查 phases 是否为 列表，且为非空
    if not isinstance(phases, list) or not phases:
        return json.dumps({
            "status": "error",
            "message": "phases must be a non-empty list."
        }, ensure_ascii=False)

    # 检查 phases 长度是否超过限制
    if len(phases) > PLAN_MAX_PHASES:
        return json.dumps({
            "status": "error",
            "message": f"Too many phases ({len(phases)}). Max {PLAN_MAX_PHASES}."
        }, ensure_ascii=False)

    seen_ids: set[str] = set()            # phase 去重保护
    clean_phases: list[dict] = []         # 清理后的阶段列表

    for i, p in enumerate(phases):
        # 把 每个阶段 从 str 做一个转换
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except (json.JSONDecodeError, TypeError):
                return json.dumps({
                    "status": "error",
                    "message": f"phase[{i}] must be a valid JSON string.",
                }, ensure_ascii=False)
            except Exception as e:
                return json.dumps({
                    "status": "error",
                    "message": f"Invalid phase[{i}]: {e}",
                }, ensure_ascii=False)

        # 检查每个阶段是否为字典
        if not isinstance(p, dict):
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] must be a dict, got {type(p).__name__}."
            }, ensure_ascii=False)

        # 检查 key 是否全为字符串（非字符串 key 会使 sorted(extra) 崩溃）
        if any(not isinstance(k, str) for k in p):
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] keys must be strings.",
            }, ensure_ascii=False)

        # 检查如果有额外的字段，返回错误
        extra = set(p.keys()) - PHASE_REQUIRED_FIELDS
        if extra:
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] unknown fields: {sorted(extra)}. Allowed: {sorted(PHASE_REQUIRED_FIELDS)}."
            }, ensure_ascii=False)

        # 检查缺少的字段，返回错误
        missing =  PHASE_REQUIRED_FIELDS - p.keys()
        if missing:
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] missing required fields: {sorted(missing)}."
            }, ensure_ascii=False)

        pid = p["phase_id"]

        # 检查 phase_id 是否为非空字符串
        if not isinstance(pid, str) or not pid.strip():
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] phase_id must be a non-empty string."
            }, ensure_ascii=False)

        pid = pid.strip()

        # 检查 phase_id 是否已存在, duplicate 检查
        if pid in seen_ids:
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] duplicate phase_id: '{pid}'."
            }, ensure_ascii=False)

        # 添加 phase_id 到 seen_ids 集合
        seen_ids.add(pid)

        # 检查 phase_name 是否为非空字符串
        if not isinstance(p["phase_name"], str) or not p["phase_name"].strip():
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] phase_name must be a non-empty string."
            }, ensure_ascii=False)

        status = p["phase_status"]

        # 检查 phase_status 是否为有效状态（先类型后成员，防不可哈希类型崩溃）
        if not isinstance(status, str) or status not in PHASE_VALID_STATUSES:
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] phase_status must be one of {sorted(PHASE_VALID_STATUSES)}, got '{status}'."
            }, ensure_ascii=False)

        # 检查 phase_description 是否为非空字符串
        if not isinstance(p["phase_description"], str) or not p["phase_description"].strip():
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] phase_description must be a non-empty string."
            }, ensure_ascii=False)

        # 添加清理后的阶段字典到 clean_phases 列表
        clean_phases.append({
            "phase_id": pid,
            "phase_name": p["phase_name"].strip(),
            "phase_status": status,
            "phase_description": p["phase_description"].strip(),
        })

    return json.dumps({
        "status": "ok",
        "message": f"Plan created with {len(clean_phases)} phases.",
        "plan": clean_phases,
    }, ensure_ascii=False)


def edit_plan(
    updates: list[dict],
    plan: list[dict]
) -> str:
    """修改计划中的一个或多个阶段。

    每个 update 必须引用已存在的 phase_id；一次调用可更新多个阶段；
    仅 phase_name、phase_status 与 phase_description 可编辑。

    Args:
        updates: 字典列表，每项含 phase_id 与要修改的字段。
        plan: 待修改的当前计划。

    Returns:
        带 status 与更新后计划的 JSON 字符串。
    """
    # 参数检查：某些大模型例如 xiaomi mimo 2.5 不能写 json，只能写 str, 所以需要先转换一些
    if isinstance(updates, str):
        try:
            updates = json.loads(updates)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({
                "status": "error",
                "message": "Invalid updates: not a JSON string.",
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Invalid updates: {e}",
            }, ensure_ascii=False)

    # 参数检查：确保 updates 是非空列表
    if not isinstance(updates, list) or not updates:
        return json.dumps({
            "status": "error",
            "message": "updates must be a non-empty list."
        }, ensure_ascii=False)

    # 参数检查：确保 plan 存在，即非空列表
    if not isinstance(plan, list) or not plan:
        return json.dumps({
            "status": "error",
            "message": "No plan exists. Use make_plan first."
        }, ensure_ascii=False)

    # 校验 plan 元素结构（plan 由调用方传入，输入不可信）
    for j, p in enumerate(plan):
        if not isinstance(p, dict) or not isinstance(p.get("phase_id"), str) \
                or not p.get("phase_id", "").strip():
            return json.dumps({
                "status": "error",
                "message": f"plan[{j}] must be a dict with a non-empty string phase_id."
            }, ensure_ascii=False)

    for i, u in enumerate(updates):
        # 检查每个 update 是否为字典
        if not isinstance(u, dict):
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] must be a dict."
            }, ensure_ascii=False)

        # 检查每个 update 是否包含 phase_id
        if "phase_id" not in u:
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] missing 'phase_id'."
            }, ensure_ascii=False)

        # 检查 key 是否全为字符串（非字符串 key 会使 sorted(extra) 崩溃）
        if any(not isinstance(k, str) for k in u):
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] keys must be strings."
            }, ensure_ascii=False)

        pid = u["phase_id"]

        # 检查 phase_id 是否为非空字符串
        if not isinstance(pid, str) or not pid.strip():
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] phase_id must be a non-empty string."
            }, ensure_ascii=False)

        # 获取要更新的字段，除 phase_id (因为你要更新里面的内容不是？而不是说相连那个 phase id 一起换了)
        update_fields = {k: v for k, v in u.items() if k != "phase_id"}

        # 检查要更新的字段是否为空，不允许为空
        if not update_fields:
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] has no fields to update. Allowed: {sorted(PHASE_ALLOWED_UPDATE_FIELDS)}."
            }, ensure_ascii=False)

        extra = set(update_fields.keys()) - PHASE_ALLOWED_UPDATE_FIELDS

        # 检查是否有额外的字段，返回错误，这里不做 missing 检测，如果missing 就是不更新就好了
        if extra:
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] unknown fields: {sorted(extra)}. Allowed: {sorted(PHASE_ALLOWED_UPDATE_FIELDS)}."
            }, ensure_ascii=False)

        # 检查 phase_status 是否为有效状态（先类型后成员，防不可哈希类型崩溃）
        if "phase_status" in update_fields:
            if not isinstance(update_fields["phase_status"], str) \
                    or update_fields["phase_status"] not in PHASE_VALID_STATUSES:
                return json.dumps({
                    "status": "error",
                    "message": f"updates[{i}] phase_status must be one of "
                            + f"{sorted(PHASE_VALID_STATUSES)}, got '{update_fields['phase_status']}'."
                }, ensure_ascii=False)

        # 检查 phase_name 是否为非空字符串
        if "phase_name" in update_fields:
            if not isinstance(update_fields["phase_name"], str) or not update_fields["phase_name"].strip():
                return json.dumps({
                    "status": "error",
                    "message": f"updates[{i}] phase_name must be a non-empty string."
                }, ensure_ascii=False)

        # 检查 phase_description 是否为非空字符串
        if "phase_description" in update_fields:
            if not isinstance(update_fields["phase_description"], str) or not update_fields["phase_description"].strip():
                return json.dumps({
                    "status": "error",
                    "message": f"updates[{i}] phase_description must be a non-empty string."
                }, ensure_ascii=False)

    # 获取计划中的所有 phase_id（strip 归一化，防御外部传入带空格 id 的 plan）
    plan_ids = {p["phase_id"].strip() for p in plan}

    # 检查每个 update 的 phase_id 是否在 plan 中，如果不存在则返回错误
    for i, u in enumerate(updates):
        pid = u["phase_id"].strip()
        if pid not in plan_ids:
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] phase_id '{pid}' not found in plan."
            }, ensure_ascii=False)

    # 创建 plan 的副本，避免修改原始计划
    new_plan = [dict(p) for p in plan]
    updated_ids: list[str] = []

    # 遍历每个 update，并更新 new_plan 中对应的阶段
    for u in updates:
        pid = u["phase_id"].strip()
        for p in new_plan:
            if p["phase_id"].strip() == pid:
                if "phase_name" in u:
                    p["phase_name"] = u["phase_name"].strip()
                if "phase_status" in u:
                    p["phase_status"] = u["phase_status"]
                if "phase_description" in u:
                    p["phase_description"] = u["phase_description"].strip()
                if pid not in updated_ids:
                    updated_ids.append(pid)
                break

    # 返回更新后的计划
    return json.dumps({
        "status": "ok",
        "message": f"Updated {len(updated_ids)} phase(s): {', '.join(updated_ids)}.",
        "plan": new_plan,
    }, ensure_ascii=False)


def delete_plan(
    phase_id: str,
    plan: list[dict],
    delete_all: bool = False,
) -> str:
    """移除一个阶段或清空整个计划。

    Args:
        phase_id: 要移除的阶段（delete_all 为 True 时忽略）。
        plan: 当前计划。
        delete_all: 为 True 时清空所有阶段。

    Returns:
        带 status 与更新后计划的 JSON 字符串。
    """

    # 参数检查：delete_all 必须是布尔值（字符串 "false" 是 truthy，会误清空整个计划）
    if not isinstance(delete_all, bool):
        return json.dumps({
            "status": "error",
            "message": "delete_all must be a boolean."
        }, ensure_ascii=False)

    # 参数检查：plan 必须是列表（delete_all 分支也需合法类型，防谎报清空；
    # 空列表在 delete_all 下保持幂等：清空空计划返回 ok）
    if not isinstance(plan, list):
        return json.dumps({
            "status": "error",
            "message": "plan must be a list."
        }, ensure_ascii=False)

    # 如果 delete_all 为 True，则清空整个计划
    if delete_all:
        return json.dumps({
            "status": "ok",
            "message": "All phases deleted.",
            "plan": [],
        }, ensure_ascii=False)

    # 检查 phase_id 是否为非空字符串
    if not isinstance(phase_id, str) or not phase_id.strip():
        return json.dumps({
            "status": "error",
            "message": "phase_id must be a non-empty string."
        }, ensure_ascii=False)

    phase_id = phase_id.strip()

    # 检查计划是否为空
    if not plan:
        return json.dumps({
            "status": "error",
            "message": "No plan exists. Use make_plan first."
        }, ensure_ascii=False)

    # 校验 plan 元素结构（plan 由调用方传入，输入不可信）
    for j, p in enumerate(plan):
        if not isinstance(p, dict) or not isinstance(p.get("phase_id"), str) \
                or not p.get("phase_id", "").strip():
            return json.dumps({
                "status": "error",
                "message": f"plan[{j}] must be a dict with a non-empty string phase_id."
            }, ensure_ascii=False)

    # 创建计划的副本，避免修改原始计划（strip 归一化匹配，与 edit_plan 一致）
    new_plan = [p for p in plan if p.get("phase_id", "").strip() != phase_id]

    # 检查 phase_id 是否存在于计划中
    if len(new_plan) == len(plan):
        return json.dumps({
            "status": "error",
            "message": f"phase_id '{phase_id}' not found in plan."
        }, ensure_ascii=False)

    # 返回更新后的计划
    return json.dumps({
        "status": "ok",
        "message": f"Phase '{phase_id}' deleted.",
        "plan": new_plan,
    }, ensure_ascii=False)
