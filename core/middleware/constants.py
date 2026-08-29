"""Identity metadata keys and role sets

Constants provided:
- identity keys:               AGENT_NAME, AGENT_ID, AGENT_ROLE, TASK_ID, TASK_NAME, the key string is the value written into metadata
- roles:                       one orchestrator role and three sub-agent roles, gathered in ALL_ROLES and SUB_AGENT_ROLES
- IDENTITY_KEYS:               all five identity keys in one tuple
"""

# identity_injection.py
AGENT_NAME = "agent_name"
AGENT_ID = "agent_id"
AGENT_ROLE = "agent_role"
TASK_ID = "task_id"
TASK_NAME = "task_name"

AGENT_ROLE_ORCHESTRATOR = "orchestrator"
AGENT_ROLE_PROGRAMMER = "programmer"
AGENT_ROLE_RESEARCHER = "researcher"
AGENT_ROLE_REVIEWER = "reviewer"

ALL_ROLES = (
    AGENT_ROLE_ORCHESTRATOR,
    AGENT_ROLE_PROGRAMMER,
    AGENT_ROLE_RESEARCHER,
    AGENT_ROLE_REVIEWER,
)
SUB_AGENT_ROLES = (
    AGENT_ROLE_PROGRAMMER,
    AGENT_ROLE_RESEARCHER,
    AGENT_ROLE_REVIEWER,
)

IDENTITY_KEYS = (AGENT_NAME, AGENT_ID, AGENT_ROLE, TASK_ID, TASK_NAME)
