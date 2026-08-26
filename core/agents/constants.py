""" Tool constants

Constants provided:
- MAX_RETRIES:                        max retries for model invoke         default 3
- BASE_DELAY:                         default retry interval for model     default 1s
- RETRYABLE_EXC:                      retryable exceptions for model invoke
- ORCHESTRATOR_MAX_ITERATIONS:        max iterations for orchestrator      default 45
- ORCHESTRATOR_ITERATION_BUDGET:      iteration budget for orchestrator    default 41
"""

import ssl

import openai
import httpx


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
