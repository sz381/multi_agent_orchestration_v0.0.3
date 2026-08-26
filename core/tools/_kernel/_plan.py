"""Execution plan management tools.

Provides:
- make_plan:        create a new plan from a phase list
- edit_plan:        modify one or more phases of the existing plan
- delete_plan:      remove a phase or clear the whole plan

Key constraints:
- all tools return JSON strings with status ok or error, validation
  failures come back as error JSON instead of raising
- pure in-memory operations: no filesystem, no IO, no locks; the caller
  passes the plan in on every call and no internal state is kept
- the caller's plan is never mutated, edit and delete work on copies
- phase_id is the identity field: stripped before dedup in make and matching
  in edit and delete, and edit can never change it
- field whitelists: make requires exactly the 4 required fields and rejects
  extras; edit allows only phase_name, phase_status, phase_description and
  rejects updates without at least one of them
- status machine: phase_status must be one of pending, in_progress, done
- hard limits: at most PLAN_MAX_PHASES phases; duplicate phase_id rejected;
  a non-empty existing_plan blocks rebuilding, guarding against last-win
- type guards: delete_all must be a bool, a string "false" is truthy and
  would clear the whole plan; non-string keys are rejected
- idempotent clear: delete_all on an empty plan still returns ok, so the
  plan can always be rebuilt

Usage notes:
- phases and updates accept a JSON string since some models can only output
  str; make_plan also accepts each phase element as a JSON string
- lifecycle: make_plan then edit_plan or delete_plan repeatedly, clear with
  delete_all True, then make_plan again
- edit_plan is a partial update: only passed fields are validated and
  applied, omitted fields stay unchanged; field format is checked before
  phase_id existence, format first, business later
- edit_plan and single-phase delete_plan require a non-empty plan and return
  an error suggesting make_plan first
- error messages carry locating indexes: phase[i] in make, updates[i] in
  edit, plan[j] in plan structure checks
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
    """Create a new execution plan from a phase list.

    Each phase must provide phase_id, phase_name, phase_status and
    phase_description. Duplicate phase_ids are rejected and the phase
    count is capped at PLAN_MAX_PHASES. Passing a non-empty
    existing_plan refuses rebuilding, guarding against concurrent
    last-writer-wins. Phases may also be given as JSON strings.

    Args:
        phases: list of phase dicts, each with the required fields.
        existing_plan: current plan; creation is refused when non-empty.

    Returns:
        JSON string with status and the validated plan.
    """
    # refuse to rebuild when a plan already exists, guards against concurrent last-win
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

    # convert phases from a JSON string to a list
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

    # phases must be a non-empty list
    if not isinstance(phases, list) or not phases:
        return json.dumps({
            "status": "error",
            "message": "phases must be a non-empty list."
        }, ensure_ascii=False)

    # reject plans over the phase limit
    if len(phases) > PLAN_MAX_PHASES:
        return json.dumps({
            "status": "error",
            "message": f"Too many phases ({len(phases)}). Max {PLAN_MAX_PHASES}."
        }, ensure_ascii=False)

    seen_ids: set[str] = set()            # dedup protection for phase ids
    clean_phases: list[dict] = []         # cleaned phase list

    for i, p in enumerate(phases):
        # convert each phase element from a JSON string
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

        # each phase must be a dict
        if not isinstance(p, dict):
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] must be a dict, got {type(p).__name__}."
            }, ensure_ascii=False)

        # keys must be strings, non-string keys crash sorted(extra)
        if any(not isinstance(k, str) for k in p):
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] keys must be strings.",
            }, ensure_ascii=False)

        # reject unknown extra fields
        extra = set(p.keys()) - PHASE_REQUIRED_FIELDS
        if extra:
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] unknown fields: {sorted(extra)}. Allowed: {sorted(PHASE_REQUIRED_FIELDS)}."
            }, ensure_ascii=False)

        # reject missing required fields
        missing =  PHASE_REQUIRED_FIELDS - p.keys()
        if missing:
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] missing required fields: {sorted(missing)}."
            }, ensure_ascii=False)

        pid = p["phase_id"]

        # phase_id must be a non-empty string
        if not isinstance(pid, str) or not pid.strip():
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] phase_id must be a non-empty string."
            }, ensure_ascii=False)

        pid = pid.strip()

        # reject duplicate phase_id
        if pid in seen_ids:
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] duplicate phase_id: '{pid}'."
            }, ensure_ascii=False)

        # track the phase_id in seen_ids
        seen_ids.add(pid)

        # phase_name must be a non-empty string
        if not isinstance(p["phase_name"], str) or not p["phase_name"].strip():
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] phase_name must be a non-empty string."
            }, ensure_ascii=False)

        status = p["phase_status"]

        # check type before membership, unhashable status would crash
        if not isinstance(status, str) or status not in PHASE_VALID_STATUSES:
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] phase_status must be one of {sorted(PHASE_VALID_STATUSES)}, got '{status}'."
            }, ensure_ascii=False)

        # phase_description must be a non-empty string
        if not isinstance(p["phase_description"], str) or not p["phase_description"].strip():
            return json.dumps({
                "status": "error",
                "message": f"phase[{i}] phase_description must be a non-empty string."
            }, ensure_ascii=False)

        # append the cleaned phase dict to clean_phases
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
    """Modify one or more phases of the existing plan.

    Each update must reference an existing phase_id; multiple phases
    can be updated in one call. Only phase_name, phase_status and
    phase_description are editable, and updates are partial: fields
    not passed stay unchanged. The caller's plan is never mutated.

    Args:
        updates: list of dicts, each with phase_id and fields to change.
        plan: current plan to modify.

    Returns:
        JSON string with status and the updated plan.
    """
    # some models, e.g. xiaomi mimo 2.5, can only output str, convert first
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

    # updates must be a non-empty list
    if not isinstance(updates, list) or not updates:
        return json.dumps({
            "status": "error",
            "message": "updates must be a non-empty list."
        }, ensure_ascii=False)

    # plan must be a non-empty list
    if not isinstance(plan, list) or not plan:
        return json.dumps({
            "status": "error",
            "message": "No plan exists. Use make_plan first."
        }, ensure_ascii=False)

    # validate plan element structure, the caller-supplied plan is untrusted
    for j, p in enumerate(plan):
        if not isinstance(p, dict) or not isinstance(p.get("phase_id"), str) \
                or not p.get("phase_id", "").strip():
            return json.dumps({
                "status": "error",
                "message": f"plan[{j}] must be a dict with a non-empty string phase_id."
            }, ensure_ascii=False)

    for i, u in enumerate(updates):
        # each update must be a dict
        if not isinstance(u, dict):
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] must be a dict."
            }, ensure_ascii=False)

        # each update must carry phase_id
        if "phase_id" not in u:
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] missing 'phase_id'."
            }, ensure_ascii=False)

        # keys must be strings, non-string keys crash sorted(extra)
        if any(not isinstance(k, str) for k in u):
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] keys must be strings."
            }, ensure_ascii=False)

        pid = u["phase_id"]

        # phase_id must be a non-empty string
        if not isinstance(pid, str) or not pid.strip():
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] phase_id must be a non-empty string."
            }, ensure_ascii=False)

        # fields to update, phase_id is the locator and never updated
        update_fields = {k: v for k, v in u.items() if k != "phase_id"}

        # an update without fields is rejected
        if not update_fields:
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] has no fields to update. Allowed: {sorted(PHASE_ALLOWED_UPDATE_FIELDS)}."
            }, ensure_ascii=False)

        extra = set(update_fields.keys()) - PHASE_ALLOWED_UPDATE_FIELDS

        # reject unknown fields, missing fields simply stay unchanged
        if extra:
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] unknown fields: {sorted(extra)}. Allowed: {sorted(PHASE_ALLOWED_UPDATE_FIELDS)}."
            }, ensure_ascii=False)

        # check type before membership, unhashable status would crash
        if "phase_status" in update_fields:
            if not isinstance(update_fields["phase_status"], str) \
                    or update_fields["phase_status"] not in PHASE_VALID_STATUSES:
                return json.dumps({
                    "status": "error",
                    "message": f"updates[{i}] phase_status must be one of "
                            + f"{sorted(PHASE_VALID_STATUSES)}, got '{update_fields['phase_status']}'."
                }, ensure_ascii=False)

        # phase_name must be a non-empty string
        if "phase_name" in update_fields:
            if not isinstance(update_fields["phase_name"], str) or not update_fields["phase_name"].strip():
                return json.dumps({
                    "status": "error",
                    "message": f"updates[{i}] phase_name must be a non-empty string."
                }, ensure_ascii=False)

        # phase_description must be a non-empty string
        if "phase_description" in update_fields:
            if not isinstance(update_fields["phase_description"], str) or not update_fields["phase_description"].strip():
                return json.dumps({
                    "status": "error",
                    "message": f"updates[{i}] phase_description must be a non-empty string."
                }, ensure_ascii=False)

    # collect stripped phase_ids, defends against plans with padded ids
    plan_ids = {p["phase_id"].strip() for p in plan}

    # each update must reference an existing phase_id
    for i, u in enumerate(updates):
        pid = u["phase_id"].strip()
        if pid not in plan_ids:
            return json.dumps({
                "status": "error",
                "message": f"updates[{i}] phase_id '{pid}' not found in plan."
            }, ensure_ascii=False)

    # copy the plan, never mutate the caller's plan
    new_plan = [dict(p) for p in plan]
    updated_ids: list[str] = []

    # apply each update to the matching phase in new_plan
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

    # return the updated plan
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
    """Remove a phase or clear the whole plan.

    With delete_all True the plan is emptied and phase_id is ignored;
    clearing an already empty plan still returns ok. Otherwise
    phase_id must match an existing phase in the plan.

    Args:
        phase_id: phase to remove, ignored when delete_all is True.
        plan: current plan.
        delete_all: when True, clear all phases.

    Returns:
        JSON string with status and the updated plan.
    """
    # delete_all must be a bool, string "false" is truthy and would wipe the plan
    if not isinstance(delete_all, bool):
        return json.dumps({
            "status": "error",
            "message": "delete_all must be a boolean."
        }, ensure_ascii=False)

    # plan must be a list even for delete_all, keeps clearing honest;
    # an empty plan stays idempotent under delete_all, clearing returns ok
    if not isinstance(plan, list):
        return json.dumps({
            "status": "error",
            "message": "plan must be a list."
        }, ensure_ascii=False)

    # delete_all True clears the whole plan
    if delete_all:
        return json.dumps({
            "status": "ok",
            "message": "All phases deleted.",
            "plan": [],
        }, ensure_ascii=False)

    # phase_id must be a non-empty string
    if not isinstance(phase_id, str) or not phase_id.strip():
        return json.dumps({
            "status": "error",
            "message": "phase_id must be a non-empty string."
        }, ensure_ascii=False)

    phase_id = phase_id.strip()

    # refuse to delete from an empty plan
    if not plan:
        return json.dumps({
            "status": "error",
            "message": "No plan exists. Use make_plan first."
        }, ensure_ascii=False)

    # validate plan element structure, the caller-supplied plan is untrusted
    for j, p in enumerate(plan):
        if not isinstance(p, dict) or not isinstance(p.get("phase_id"), str) \
                or not p.get("phase_id", "").strip():
            return json.dumps({
                "status": "error",
                "message": f"plan[{j}] must be a dict with a non-empty string phase_id."
            }, ensure_ascii=False)

    # copy the plan, strip-normalized matching as in edit_plan
    new_plan = [p for p in plan if p.get("phase_id", "").strip() != phase_id]

    # reject a phase_id not in the plan
    if len(new_plan) == len(plan):
        return json.dumps({
            "status": "error",
            "message": f"phase_id '{phase_id}' not found in plan."
        }, ensure_ascii=False)

    # return the updated plan
    return json.dumps({
        "status": "ok",
        "message": f"Phase '{phase_id}' deleted.",
        "plan": new_plan,
    }, ensure_ascii=False)
