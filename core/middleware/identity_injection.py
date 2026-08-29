"""Agent identity contract bridging LLM-calling nodes and the callback

Single source of truth for identity binding:

- bind_identity:                called by every LLM-calling node (orchestrator now, sub-agents later) to declare WHO invokes the model; the identity is merged into RunnableConfig.metadata
- identity_from_metadata:       called by the callback to read the identity back

Design rule: the callback never guesses. Identity comes only from metadata;
runs without one are system-level calls and are skipped by the callback.
"""

from langchain_core.runnables import RunnableConfig

from core.middleware.constants import (
    AGENT_ID,
    AGENT_NAME,
    AGENT_ROLE,
    ALL_ROLES,
    IDENTITY_KEYS,
    TASK_ID,
    TASK_NAME,
)


def bind_identity(
    config: RunnableConfig,
    agent_name: str,
    agent_id: str,
    agent_role: str,
    task_id: str = "",
    task_name: str = "",
) -> RunnableConfig:
    """Return a new config with the agent identity merged into metadata

    The config is copied first, so the shared graph config is never
    modified in place. Unrelated metadata injected by LangGraph
    (langgraph_step, langgraph_node, ...) is preserved.

    Args:
        config:      the incoming RunnableConfig of a graph node.
        agent_name:  display name, e.g. "orchestrator" or "programmer".
        agent_id:    unique instance id; the orchestrator uses "orchestrator", sub-agents use generated ids such as "programmer_001".
        agent_role:  one of ALL_ROLES.
        task_id:     parent task id, empty for the orchestrator.
        task_name:   parent task label, empty for the orchestrator.

    Returns:
        a new RunnableConfig carrying the identity in metadata.

    Raises:
        ValueError: when agent_role is not a legal role.
    """
    if agent_role not in ALL_ROLES:
        raise ValueError(f"Unknown agent_role: {agent_role}")

    # copy the config so the caller's config stays untouched
    new_config = dict(config)

    # copy the existing metadata, then fill in the identity keys one by one
    metadata = dict(new_config.get("metadata") or {})
    metadata[AGENT_NAME] = agent_name
    metadata[AGENT_ID] = agent_id
    metadata[AGENT_ROLE] = agent_role
    metadata[TASK_ID] = task_id
    metadata[TASK_NAME] = task_name

    new_config["metadata"] = metadata
    return new_config


def identity_from_metadata(metadata: dict | None) -> dict | None:
    """Extract the identity dict from a run's metadata

    Args:
        metadata: the metadata dict delivered to callback hooks such as
            on_chat_model_start.

    Returns:
        the identity dict keyed by IDENTITY_KEYS, or None when the run
        carries no identity (system-level call; the callback skips it).
    """
    if not metadata:
        return None

    identity = {}
    for key in IDENTITY_KEYS:
        identity[key] = str(metadata.get(key, ""))

    # no agent_id means this LLM call declared no identity at all
    if not identity.get(AGENT_ID):
        return None

    return identity