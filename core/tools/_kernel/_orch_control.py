"""Orchestrator control tools implementation.

Provides:
- end_orchestration:    end the orchestration with a final response
- pause_orchestration:  pause the orchestration, human-in-the-loop
- fanout_subagents:     dispatch tasks to sub-agents

Key constraints:
- all tools return JSON strings with status ok or error, exceptions are
  caught and converted to error JSON instead of raising
- pure functions: the StateGraph is never mutated directly, the bundle
  layer writes orchestration state via Command with update=...,
  following the kernel-plus-bundle layering
- call-level guard first: a non-empty current_response or current_tasks
  means this turn already called the tool, duplicates are rejected,
  this check runs before any argument-level validation
- boolean state gates: should_orch_end and should_orch_pause must be
  bool, a string "false" is truthy and would slip through; a False
  gate rejects the operation
- end_orchestration check order: current_response, then should_orch_end,
  then plan, then response, only the first violation is reported
- plan validation: must be a list or None; elements are dicts with a
  non-empty string phase_id; pending phases, phase_status not "done",
  reject ending and list their phase_ids
- response validation: non-empty string, stripped before the length
  check, capped at MAX_RESPONSE_LENGTH
- fanout validation chain: tasks must be a non-empty list capped at
  MAX_TASKS; elements are dicts with a field whitelist, 6 required
  fields plus the optional project_dir; task_id unique per round;
  subagent_id prefix must be in AVAILABLE_SUBAGENT_PREFIXES and unique
  per round, one task per sub-agent per round; task_completion_status
  must be exactly False
- cleaned output: all text fields are stripped before storage, an empty
  project_dir is dropped

Usage notes:
- state snapshots are read from the StateGraph by the bundle layer and
  passed in as arguments, current_response, current_tasks,
  should_orch_end and should_orch_pause
- control tools must run with ControlAwareToolNode: exclusive per turn,
  only one control tool per round and never mixed with other tools
- round semantics: the returned tasks or plan should be written back to
  the StateGraph and become the current_* arguments of the next call,
  closing the duplicate-guard loop
- the tasks argument accepts a JSON string since some models can only
  output str; a parse failure falls through to the list check and
  returns error, parsed results still go through the full list validation
- error messages carry locating indexes: task[i] in fanout, plan[j] in
  plan structure checks
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
    """Return the final response and end the orchestration.

    Only one call is allowed per round. Ending is refused while the
    plan still has pending phases.

    The bundle layer reads StateGraph data from runtime.state[...]
    with ToolRuntime, from langgraph.prebuilt import ToolRuntime, and
    writes orchestration state back via Command with update=...,
    from langgraph.types import Command.

    Args:
        response: final answer string, the "response" field in StateGraph.
        current_response: current value of the "response" field in
            StateGraph; non-empty means already called this round,
            guarding against concurrent last-win.
        plan: current plan phases, optional; when provided, every phase
            must be done before ending.
        should_orch_end: whether ending is allowed, the "should_orch_end"
            field in StateGraph; False rejects ending, unblock first.

    Returns:
        JSON data with status and message.
    """

    try:
        # refuse a second end_orchestration call this round, call-level guard
        # runs before argument checks
        if current_response:
            return json.dumps({
                "status": "error",
                "message": "end_orchestration already called in this turn. Ignoring duplicate call."
            }, ensure_ascii=False)

        # should_orch_end must be a bool, string "false" is truthy and would slip through
        if not isinstance(should_orch_end, bool):
            return json.dumps({
                "status": "error",
                "message": "should_orch_end must be a boolean."
            }, ensure_ascii=False)

        # state gate: reject when ending is not allowed
        if not should_orch_end:
            return json.dumps({
                "status": "error",
                "message": "Cannot end orchestration: should_orch_end is False."
            }, ensure_ascii=False)

        # plan must be a list or None
        if plan is not None and not isinstance(plan, list):
            return json.dumps({
                "status": "error",
                "message": "plan must be a list or None.",
            }, ensure_ascii=False)

        # validate plan element structure, the caller-supplied plan is
        # untrusted, keeps errors from being swallowed by the fallback
        if plan:
            for j, p in enumerate(plan):
                if not isinstance(p, dict) or not isinstance(p.get("phase_id"), str) \
                        or not p.get("phase_id", "").strip():
                    return json.dumps({
                        "status": "error",
                        "message": f"plan[{j}] must be a dict with a non-empty string phase_id."
                    }, ensure_ascii=False)

            # refuse to end while the plan has pending phases
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

        # response must be a string
        if not isinstance(response, str):
            return json.dumps({
                "status": "error",
                "message": "response must be a string."
            }, ensure_ascii=False)

        # response must be non-empty
        if not response.strip():
            return json.dumps({
                "status": "error",
                "message": "response must be a non-empty string."
            }, ensure_ascii=False)

        # strip whitespace around response
        response = response.strip()

        # reject responses over the length cap
        if len(response) > MAX_RESPONSE_LENGTH:
            return json.dumps({
                "status": "error",
                "message": f"response too long ({len(response)} chars). Max {MAX_RESPONSE_LENGTH}."
            }, ensure_ascii=False)

        # all checks passed, return the final response and end
        return json.dumps({
            "status": "ok",
            "message": "Orchestration ended.",
        }, ensure_ascii=False)

    # catch and convert any exception to error JSON
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Unexpected error in end_orchestration: {exc}"
        }, ensure_ascii=False)


def pause_orchestration(
    should_orch_pause: bool,
) -> str:
    """Return a response and pause the orchestration.

    Only one call is allowed per round. The bundle layer writes
    orchestration state back via Command with update=..., setting
    should_orchestration_pause to trigger the human-in-the-loop branch
    in graph.py. Command comes from langgraph.types import Command.

    Args:
        should_orch_pause: whether pausing is allowed, the
            "should_orch_pause" field in StateGraph; False rejects
            pausing.

    Returns:
        JSON data with status and message.
    """
    # should_orch_pause must be a bool, string "false" is truthy and would slip through
    if not isinstance(should_orch_pause, bool):
        return json.dumps({
            "status": "error",
            "message": "should_orch_pause must be a boolean."
        }, ensure_ascii=False)

    # state gate: reject when pausing is not allowed
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
    """Dispatch tasks to sub-agents for parallel execution.

    Only one dispatch call is allowed per round. The bundle layer reads
    StateGraph data from runtime.state[...] and writes the validated
    tasks back via Command with update=..., from langgraph.types
    import Command.

    Args:
        tasks: list of task dicts with the required fields, the
            "sub_agent_round_tasks" field in StateGraph; a JSON string
            is also accepted.
        current_tasks: whether dispatch was already called this round,
            non-empty guards against concurrent last-win, the
            "sub_agent_round_tasks" field in StateGraph.

    Returns:
        JSON data with status and the validated task list.
    """
    try:
        # refuse a second fanout_subagents call this round, call-level guard
        # runs before argument checks
        if current_tasks:
            return json.dumps({
                "status": "error",
                "message": "fanout_subagents already called in this turn. Ignoring duplicate call."
            }, ensure_ascii=False)

        # some models, e.g. xiaomi mimo v2.5, can only output str,
        # try to parse tasks as JSON first
        if isinstance(tasks, str):
            try:
                tasks = json.loads(tasks)
            except (json.JSONDecodeError, TypeError):
                pass

        # tasks must be a list
        if not isinstance(tasks, list):
            return json.dumps({
                "status": "error",
                "message": "tasks must be a list."
            }, ensure_ascii=False)

        # tasks must be a non-empty list
        if not tasks:
            return json.dumps({
                "status": "error",
                "message": "tasks must be a non-empty list."
            }, ensure_ascii=False)

        # reject more tasks than MAX_TASKS
        if len(tasks) > MAX_TASKS:
            return json.dumps({
                "status": "error",
                "message": f"Too many tasks ({len(tasks)}). Max {MAX_TASKS}."
            }, ensure_ascii=False)

        seen_ids: set[str] = set()                          # seen task_ids
        seen_subagent_ids: set[str] = set()                 # seen subagent_ids
        clean_tasks: list[dict] = []                        # cleaned task list

        for i, t in enumerate(tasks):
            # each task must be a dict
            if not isinstance(t, dict):
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] must be a dict, got {type(t).__name__}."
                }, ensure_ascii=False)

            # reject unknown extra fields
            extra = set(t.keys()) - REQUIRED_TASK_FIELDS - ALLOWED_OPTIONAL_FIELDS
            if extra:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] unknown fields: {sorted(extra)}. Allowed: {sorted(REQUIRED_TASK_FIELDS | ALLOWED_OPTIONAL_FIELDS)}."
                }, ensure_ascii=False)

            # reject missing required fields
            missing = REQUIRED_TASK_FIELDS - t.keys()
            if missing:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] missing required fields: {sorted(missing)}."
                }, ensure_ascii=False)

            tid = t["task_id"]

            # task_id must be a non-empty string
            if not isinstance(tid, str) or not tid.strip():
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] task_id must be a non-empty string."
                }, ensure_ascii=False)

            tid = tid.strip()

            # reject duplicate task_id
            if tid in seen_ids:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] duplicate task_id: '{tid}'."
                }, ensure_ascii=False)

            seen_ids.add(tid)

            # task_name must be a non-empty string
            if not isinstance(t["task_name"], str) or not t["task_name"].strip():
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] task_name must be a non-empty string."
                }, ensure_ascii=False)

            # task_description must be a non-empty string
            if not isinstance(t["task_description"], str) or not t["task_description"].strip():
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] task_description must be a non-empty string."
                }, ensure_ascii=False)

            # task_completion_status must be exactly False
            if t["task_completion_status"] is not False:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] task_completion_status must be false."
                }, ensure_ascii=False)

            sid = t["subagent_id"]

            # subagent_id must be a non-empty string
            if not isinstance(sid, str) or not sid.strip():
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] subagent_id must be a non-empty string."
                }, ensure_ascii=False)

            sid = sid.strip()
            prefix = sid.split("_", 1)[0]

            # subagent_id prefix must be one of the available prefixes
            if prefix not in AVAILABLE_SUBAGENT_PREFIXES:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] subagent_id '{sid}' has invalid prefix '{prefix}'. Available: {AVAILABLE_SUBAGENT_PREFIXES}."
                }, ensure_ascii=False)

            # subagent_name must be a non-empty string
            if not isinstance(t["subagent_name"], str) or not t["subagent_name"].strip():
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] subagent_name must be a non-empty string."
                }, ensure_ascii=False)

            # reject duplicate subagent_id, one task per sub-agent per fanout
            sid_stripped = sid.strip()
            if sid_stripped in seen_subagent_ids:
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] duplicate subagent_id: '{sid_stripped}'. Each sub-agent can only handle one task per fanout."
                }, ensure_ascii=False)
            seen_subagent_ids.add(sid_stripped)

            # optional project_dir must be a string, a non-str would
            # crash strip and get swallowed by the fallback
            if "project_dir" in t and not isinstance(t["project_dir"], str):
                return json.dumps({
                    "status": "error",
                    "message": f"task[{i}] project_dir must be a string."
                }, ensure_ascii=False)

            # build the cleaned task list
            clean_tasks.append({
                "task_id": tid,
                "task_name": t["task_name"].strip(),
                "task_description": t["task_description"].strip(),
                "task_completion_status": False,
                "subagent_id": sid,
                "subagent_name": t["subagent_name"].strip(),
                **({"project_dir": t["project_dir"].strip()} if t.get("project_dir", "").strip() else {}),
            })

        # return the result
        return json.dumps({
            "status": "ok",
            "message": f"Dispatched {len(clean_tasks)} task(s) to subagents.",
            "tasks": clean_tasks,
        }, ensure_ascii=False)

    # exception handling
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Unexpected error in fanout_subagents: {exc}"
        }, ensure_ascii=False)
