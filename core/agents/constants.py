""" Tool constants

Constants provided:
- MAX_RETRIES:                        max retries for model invoke         default 3
- BASE_DELAY:                         default retry interval for model     default 1s
- RETRYABLE_EXC:                      retryable exceptions for model invoke
- ORCHESTRATOR_MAX_ITERATIONS:        max iterations for orchestrator      default 45
- ORCHESTRATOR_ITERATION_BUDGET:      iteration budget for orchestrator    default 41
- SUB_AGENT_MAX_ITERATIONS:           max iterations for sub-agents        default 42
- SUB_AGENT_ITERATION_BUDGET:         iteration budget for sub-agents      default 37
- SUB_AGENT_PLAN_CAPABLE_ROLES:       plan-capable sub-agent roles         default programmer, researcher
- PLAN_VISIBLE_ROLES:                 roles rendering the plan block       default orchestrator, programmer, researcher
- BASE_IDENTITY_FIELDS:               base identity fields of sub-agents
- PREPARE_IDENTITY_FIELDS:            identity fields for prepare node
- LLM_IDENTITY_FIELDS:                identity fields for llm node
- SUMMARIZE_IDENTITY_FIELDS:          identity fields for summarize node
- FILE_PRODUCING_TOOLS:               file-producing tool to arg-name mapping
- MAX_FILES_SHOWN:                    max artifacts shown in console block   default 20
"""

import ssl

import openai
import httpx

from core.middleware.constants import (
    AGENT_ROLE_ORCHESTRATOR,
    AGENT_ROLE_PROGRAMMER,
    AGENT_ROLE_RESEARCHER,
)


# model.py
MAX_RETRIES = 3
BASE_DELAY = 1
RETRYABLE_EXC = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
    ssl.SSLError,
    httpx.TransportError,
    httpx.ReadError,
    httpx.ConnectError,
    ConnectionError,
    OSError,
)

# orchestrator.py
ORCHESTRATOR_MAX_ITERATIONS = 45
ORCHESTRATOR_ITERATION_BUDGET = 41

# workers/nodes/llm.py
SUB_AGENT_MAX_ITERATIONS = 42
SUB_AGENT_ITERATION_BUDGET = 37
SUB_AGENT_PLAN_CAPABLE_ROLES = (AGENT_ROLE_PROGRAMMER, AGENT_ROLE_RESEARCHER)

# core/agents/utils.py
PLAN_VISIBLE_ROLES = (
    AGENT_ROLE_ORCHESTRATOR,
    AGENT_ROLE_PROGRAMMER,
    AGENT_ROLE_RESEARCHER,
)

BASE_IDENTITY_FIELDS = (
    "sub_agent_id",
    "sub_agent_name",
    "task_id",
    "task_name",
)

PREPARE_IDENTITY_FIELDS = (
    "sub_agent_id",
    "sub_agent_name",
    "task_id",
    "task_name",
    "task_description",
)

LLM_IDENTITY_FIELDS = (
    "sub_agent_id",
    "sub_agent_name",
    "task_id",
    "task_name",
    "sub_agent_messages",
)

SUMMARIZE_IDENTITY_FIELDS = (
    "sub_agent_id",
    "sub_agent_name",
    "task_id",
    "task_name",
    "sub_agent_messages",
)

# workers/nodes/summarize.py
FILE_PRODUCING_TOOLS = {
    "write_file": "file_path",
    "str_replace": "file_path",
}

MAX_FILES_SHOWN = 100
