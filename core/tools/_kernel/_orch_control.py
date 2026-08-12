"""Orchestrator 编排控制工具实现

提供函数：
- end_orchestration:        结束编排
- pause_orchestration:      暂停编排
- fanout_subagents:         派遣子代理

关键约束：
- 所有工具统一返回 JSON 字符串（status: ok/error），不抛异常（except 兜底）
- 纯函数：不直接修改 StateGraph，通过返回 JSON 让 bundle 层用
  Command(update=...) 写入编排状态（分层规范：Kernel 纯函数 + Bundle 异步 Command）
- 调用级防护优先：current_response/current_tasks 非空即视为本轮已调用过，
  拒绝重复调用（防并发的 last-win，优先于参数级校验）
- 布尔状态闸门：should_orch_end/should_orch_pause 必须为 bool
  （字符串 "false" 是 truthy，误传会放行）且为 False 时拒绝操作
- 检查顺序契约：end_orchestration 按 current_response → should_orch_end →
  plan → response 依次校验，同输入多违例时只报第一个
- plan 校验：必须是 list 或 None；元素为含非空字符串 phase_id 的字典；
  存在未完成阶段（phase_status != "done"）时拒绝结束并列出 phase_id
- response 校验：非空字符串（strip 后参与长度校验），上限 MAX_RESPONSE_LENGTH
- fanout 校验链：tasks 须为非空列表（上限 MAX_TASKS）；元素为字典且字段白名单
  （6 必填 + project_dir 可选）；task_id 同轮唯一；subagent_id 前缀必须在
  AVAILABLE_SUBAGENT_PREFIXES 内且同轮唯一（每个子代理一轮一个任务）；
  task_completion_status 必须精确为 False
- 清理输出：所有文本字段 strip 后存储；project_dir 空值时剔除

使用注意：
- 状态快照由 bundle 层从 StateGraph 读取并作为参数传入
  （current_response/current_tasks/should_orch_end/should_orch_pause）
- 控制类工具须配合 ControlAwareToolNode 使用：本轮独占，一次只能调用一个
  控制工具且不能与其他任何工具混用
- 轮次语义：调用成功后的返回（tasks/plan）应写入 StateGraph，作为下一次
  调用的 current_* 参数，形成防重闭环
- fanout 的 tasks 参数支持 JSON 字符串输入（兼容只能输出 str 的模型），
  解析失败返回 error；解析结果仍走完整列表校验
- 错误消息携带定位索引：task[i]（fanout）、plan[j]（plan 结构校验）
"""

import json

from core.tools._kernel.constants import (
    MAX_RESPONSE_LENGTH,
    MAX_TASKS,
    REQUIRED_TASK_FIELDS,
    ALLOWED_OPTIONAL_FIELDS,
    AVAILABLE_SUBAGENT_PREFIXES,
)


def end_orchestration(
    response: any, 
    current_response: str = "",
    plan: list | None = None,
    should_orch_end: bool = True,
) -> str:
    """返回最终响应并结束编排。

    每轮仅允许调用一次。如果计划中仍有未完成的阶段，则拒绝结束。
    可以让 bundle 层 采用 runtime['xxx'] 
    //runtime: ToolRuntime // from langgraph.prebuilt import ToolRuntime//传递 StateGraph 中的数据
    原理是通过 Command //"from langgraph.types import Command"// 更改 StateGraph 中的字段以更新编排状态。

    参数：
        response：最终答案字符串 （StateGraph 中的 "response" 字段）。
        current_response：StateGraph 中 "response" 字段的当前值。
                        （防止并发的 last-win：非空即视为本轮已调用过 end_orchestration。）
        plan：当前计划阶段（可选）。若提供，所有阶段必须为 “done” 才能结束。
        should_orch_end：当前编排是否允许结束 （StateGraph 中的 "should_orch_end" 字段）。
                        （状态闸门：为 False 时拒绝结束，需先解除阻止状态。）

    返回值：
        包含状态和消息的 JSON 数据。
    """

    try:
        # 如果已经调用过 end_orchestration，则拒绝再次调用（调用级防护优先于参数级校验）
        if current_response:
            return json.dumps({
                "status": "error",
                "message": "end_orchestration already called in this turn. Ignoring duplicate call."
            }, ensure_ascii=False)

        # 参数检查：should_orch_end 必须是布尔值（字符串 "false" 是 truthy，会误放行）
        if not isinstance(should_orch_end, bool):
            return json.dumps({
                "status": "error",
                "message": "should_orch_end must be a boolean."
            }, ensure_ascii=False)

        # 状态闸门：编排不允许结束时拒绝（should_orch_end 为 False）
        if not should_orch_end:
            return json.dumps({
                "status": "error",
                "message": "Cannot end orchestration: should_orch_end is False."
            }, ensure_ascii=False)

        # 参数检查：plan 必须为列表或 None
        if plan is not None and not isinstance(plan, list):
            return json.dumps({
                "status": "error",
                "message": "plan must be a list or None.",
            }, ensure_ascii=False)

        # 校验 plan 元素结构（plan 由调用方传入，输入不可信），防异常被兜底捕获吞掉
        if plan:
            for j, p in enumerate(plan):
                if not isinstance(p, dict) or not isinstance(p.get("phase_id"), str) \
                        or not p.get("phase_id", "").strip():
                    return json.dumps({
                        "status": "error",
                        "message": f"plan[{j}] must be a dict with a non-empty string phase_id."
                    }, ensure_ascii=False)

            # 如果有 未完成的 plan，则拒绝结束当前 orchestration
            pending = [p for p in plan if p.get("phase_status") != "done"]

            if pending:
                pending_ids = [p["phase_id"] for p in pending]

                return json.dumps({
                    "status": "error",
                    "message": (
                        f"Cannot end orchestration: {len(pending)} phase(s) "
                        f"still pending: {pending_ids}. Complete them or "
                        f"delete them before calling end_orchestration."
                    ),
                }, ensure_ascii=False)

        # 如果 response 不是字符串，则拒绝
        if not isinstance(response, str):
            return json.dumps({
                "status": "error",
                "message": "response must be a string."
            }, ensure_ascii=False)

        # 如果 response 是空字符串，则拒绝
        if not response.strip():
            return json.dumps({
                "status": "error",
                "message": "response must be a non-empty string."
            }, ensure_ascii=False)

        # 去除 response 两端的空白字符
        response = response.strip()

        # 如果 response 过长，则拒绝
        if len(response) > MAX_RESPONSE_LENGTH:
            return json.dumps({
                "status": "error",
                "message": f"response too long ({len(response)} chars). Max {MAX_RESPONSE_LENGTH}."
            }, ensure_ascii=False)

        # 如果以上检查都通过，则返回最终响应并结束编排  
        return json.dumps({
            "status": "ok",
            "message": "Orchestration ended.",
        }, ensure_ascii=False)

    # 捕获并处理任何异常
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Unexpected error in end_orchestration: {exc}"
        }, ensure_ascii=False)


def pause_orchestration(
    should_orch_pause: bool,
) -> str:
    """返回响应并暂停编排。

    每轮仅允许调用一次
    原理是通过 Command //"from langgraph.types import Command"// 更改 StateGraph 中的字段以更新编排状态。

    参数：
        should_orch_pause：当前编排是否允许暂停 （StateGraph 中的 "should_orch_pause" 字段）。
                        （状态闸门：为 False 时拒绝暂停。）

    返回值：
        包含状态和消息的 JSON 数据。
    """
    # 参数检查：should_orch_pause 必须是布尔值（字符串 "false" 是 truthy，会误放行）
    if not isinstance(should_orch_pause, bool):
        return json.dumps({
            "status": "error",
            "message": "should_orch_pause must be a boolean."
        }, ensure_ascii=False)

    # 状态闸门：编排不允许暂停时拒绝（should_orch_pause 为 False）
    if not should_orch_pause:
        return json.dumps({
            "status": "error",
            "message": "Cannot pause orchestration: should_orch_pause is False."
        }, ensure_ascii=False)

    return json.dumps({
        "status": "ok",
        "message": "Orchestration paused."
    }, ensure_ascii=False)


def fanout_subagents(
    tasks: any, 
    current_tasks: list = None
) -> str:
    """将任务分发给子代理以实现并行执行。

    每轮仅允许调用一次分支操作。
    原理是通过 Command //"from langgraph.types import Command"// 更改 StateGraph 中的字段以更新编排状态。

    参数：
        tasks：包含必要字段的任务字典列表。 （StateGraph 中的 "sub_agent_round_tasks" 字段）。
        current_tasks：本轮是否已调用过分支操作。（防止并发的 last_win）（StateGraph 中的 "sub_agent_round_tasks" 字段）。

    返回值：
        包含状态信息和验证后的任务列表的JSON。
    """
    try:
        # 如果已经调用过 fanout_subagents，则拒绝再次调用（调用级防护优先于参数级校验）
        if current_tasks:
            return json.dumps({
                "status": "error",
                "message": "fanout_subagents already called in this turn. Ignoring duplicate call."
            }, ensure_ascii=False)

        # 如果 tasks 是字符串，则尝试解析为 JSON，有一些 model 可能会返回字符串，例如 xiaomi mimo v2.5...
        if isinstance(tasks, str):
            try:
                tasks = json.loads(tasks)
            except (json.JSONDecodeError, TypeError):
                pass

        # 参数检查：tasks 必须是列表
        if not isinstance(tasks, list):
            return json.dumps({
                "status": "error",
                "message": "tasks must be a list."
            }, ensure_ascii=False)

        # 参数检查：tasks 必须是非空列表
        if not tasks:
            return json.dumps({
                "status": "error",
                "message": "tasks must be a non-empty list."
            }, ensure_ascii=False)

        # 参数检查：tasks 必须不超过最大任务数
        if len(tasks) > MAX_TASKS:
            return json.dumps({
                "status": "error",
                "message": f"Too many tasks ({len(tasks)}). Max {MAX_TASKS}."
            }, ensure_ascii=False)

        seen_ids: set[str] = set()                          # 存储已见的 task_id
        seen_subagent_ids: set[str] = set()                 # 存储已见的 subagent_id
        clean_tasks: list[dict] = []                        # 构建清理后的任务列表

        for i, t in enumerate(tasks):
            # 参数检查：tasks 必须是字典
            if not isinstance(t, dict):
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] must be a dict, got {type(t).__name__}."
                }, ensure_ascii=False)

            # 参数检查：tasks 必须包含必需字段
            extra = set(t.keys()) - REQUIRED_TASK_FIELDS - ALLOWED_OPTIONAL_FIELDS
            if extra:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] unknown fields: {sorted(extra)}. Allowed: {sorted(REQUIRED_TASK_FIELDS | ALLOWED_OPTIONAL_FIELDS)}."
                }, ensure_ascii=False)

            # 参数检查：tasks 必须包含所有必需字段
            missing = REQUIRED_TASK_FIELDS - t.keys()
            if missing:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] missing required fields: {sorted(missing)}."
                }, ensure_ascii=False)

            tid = t["task_id"]
            
            # 参数检查：tasks 必须包含非空字符串 task_id
            if not isinstance(tid, str) or not tid.strip():
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] task_id must be a non-empty string."
                }, ensure_ascii=False)
                
            tid = tid.strip()

            # 参数检查：tasks 必须包含唯一 task_id
            if tid in seen_ids:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] duplicate task_id: '{tid}'."
                }, ensure_ascii=False)
                
            seen_ids.add(tid)

            # 参数检查：tasks 必须包含非空字符串 task_name
            if not isinstance(t["task_name"], str) or not t["task_name"].strip():
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] task_name must be a non-empty string."
                }, ensure_ascii=False)

            # 参数检查：tasks 必须包含非空字符串 task_description
            if not isinstance(t["task_description"], str) or not t["task_description"].strip():
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] task_description must be a non-empty string."
                }, ensure_ascii=False)

            # 参数检查：tasks 必须包含布尔值 task_completion_status
            if t["task_completion_status"] is not False:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] task_completion_status must be false."
                }, ensure_ascii=False)

            sid = t["subagent_id"]
            
            # 参数检查：tasks 必须包含非空字符串 subagent_id
            if not isinstance(sid, str) or not sid.strip():
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] subagent_id must be a non-empty string."
                }, ensure_ascii=False)
                
            sid = sid.strip()
            prefix = sid.split("_", 1)[0]
            
            # 参数检查：tasks 必须包含有效前缀的 subagent_id
            if prefix not in AVAILABLE_SUBAGENT_PREFIXES:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] subagent_id '{sid}' has invalid prefix '{prefix}'. Available: {AVAILABLE_SUBAGENT_PREFIXES}."
                }, ensure_ascii=False)

            # 参数检查：tasks 必须包含非空字符串 subagent_name
            if not isinstance(t["subagent_name"], str) or not t["subagent_name"].strip():
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] subagent_name must be a non-empty string."
                }, ensure_ascii=False)

            # 参数检查：tasks 必须包含唯一 subagent_id
            sid_stripped = sid.strip()
            if sid_stripped in seen_subagent_ids:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] duplicate subagent_id: '{sid_stripped}'. Each sub-agent can only handle one task per fanout."
                }, ensure_ascii=False)
            seen_subagent_ids.add(sid_stripped)

            # 参数检查：可选字段 project_dir 必须是字符串（非字符串会使 strip 崩溃，被兜底捕获吞掉）
            if "project_dir" in t and not isinstance(t["project_dir"], str):
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] project_dir must be a string."
                }, ensure_ascii=False)

            # 构建清理后的任务列表
            clean_tasks.append({
                "task_id": tid,
                "task_name": t["task_name"].strip(),
                "task_description": t["task_description"].strip(),
                "task_completion_status": False,
                "subagent_id": sid,
                "subagent_name": t["subagent_name"].strip(),
                **({"project_dir": t["project_dir"].strip()} if t.get("project_dir", "").strip() else {}),
            })

        # 返回结果
        return json.dumps({
            "status": "ok",
            "message": f"Dispatched {len(clean_tasks)} task(s) to subagents.",
            "tasks": clean_tasks,
        }, ensure_ascii=False)

    # 异常处理
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Unexpected error in fanout_subagents: {exc}"
        }, ensure_ascii=False)
