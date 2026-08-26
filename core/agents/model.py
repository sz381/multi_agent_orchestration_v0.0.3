"""Model initialization and invocation retry

Functions provided:
- init_model:                   Create a cached ChatOpenAI instance routed by model prefix
- ainvoke_with_retry:           Invoke with exponential backoff retry on transient errors
- ainvoke_with_content_guard:   Retry with empty-response guard, resend once when empty
"""

import asyncio
from functools import lru_cache
from typing import Any

import openai
from langchain_openai import ChatOpenAI

from utils.settings import settings
from utils.logging import get_logger
from core.agents.constants import (
    MAX_RETRIES,
    BASE_DELAY,
    RETRYABLE_EXC,
)

logger = get_logger(__name__)


@lru_cache(maxsize=16)
def init_model(
    model_name: str = settings.deepseek_model_name,
    temperature: float = 0.3,
    max_tokens: int = 16384,
    streaming: bool = True,
) -> ChatOpenAI:
    """Initialize a ChatOpenAI model instance

    Args:
        model_name:         Model name
        temperature:        Sampling temperature.
        max_tokens:         Maximum number of tokens to generate.
        streaming:          Whether to stream output.

    Returns:
        A configured ChatOpenAI instance
    """
    if model_name.startswith("deepseek"):
        api_key = settings.deepseek_api_key
        base_url = settings.deepseek_base_url
    elif model_name.startswith("mimo"):
        api_key = settings.xiaomi_mimo_api_key
        base_url = settings.xiaomi_mimo_base_url
    else:
        raise ValueError(f"Unknown model name: {model_name}")
        
    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
    )


async def ainvoke_with_retry(
    runnable: Any,
    *args: Any,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY,
    **kwargs: Any,
) -> Any:
    """Invoke with retry

    Asynchronously invoke any object with an ainvoke method; on transient network or 
    rate-limit errors, automatically retry with exponential backoff, and raise the 
    original exception once retries are exhausted

    Args:
        runnable:       Any object with an ainvoke method such as ChatOpenAI or Runnable.
        *args:          Positional arguments passed through to ainvoke.
        max_retries:    Max retry count, default 3.
        base_delay:     Initial backoff seconds, default 1.0, doubling each time.
        **kwargs:       Keyword arguments passed through to ainvoke.

    Returns:
        The result of runnable.ainvoke(*args, **kwargs).

    Raises:
        Raises the last retryable exception after retries are exhausted; 
        non-retryable exceptions are raised immediately as-is.
    """
    last_exc: Exception | None = None

    # Retry up to max_retries + 1 times (first attempt + retries)
    for attempt in range(max_retries + 1):
        # invoke or retry successfully
        try:
            return await runnable.ainvoke(*args, **kwargs)

        # invoke or retry unsuccessfully, retry only on retryable exceptions
        except RETRYABLE_EXC as exc:
            last_exc = exc

            # if still have retry chances left
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)

                # Flow control explanation: The server is continuously overloaded. 
                # A 5-second backoff period is applied to avoid short backoff cycles that repeatedly trigger the flow control limit.
                if isinstance(exc, openai.RateLimitError):
                    delay = max(delay, 5.0)

                logger.warning("ainvoke_retry", attempt=attempt + 1, max_retries=max_retries, delay=round(delay, 1), error=str(exc)[:200])
                
                await asyncio.sleep(delay)
            else:
                # Retry exhausted: raise the original exception (not wrapped or swallowed), let the caller handle the real error
                raise

    # theoretically unreachable (last failure must raise): fallback to prevent exception path misjudgment
    raise last_exc


async def ainvoke_with_content_guard(
    runnable: Any,
    *args: Any,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY,
    allow_empty: bool = False,
    role: str = "agent",
    **kwargs: Any,
) -> Any:
    """Invoke with network retry and empty-response guard

    Layer 1 retries transient network errors such as SSL, connection, timeout, or rate limit. 
    Layer 2 resends the same request once without backoff when the response has no tool calls or content, and raises if still empty.

    Args:
        runnable:       Any object with an ainvoke method such as ChatOpenAI.
        *args:          Positional arguments passed through to ainvoke.
        max_retries:    Network retry count, default 3.
        base_delay:     Initial backoff seconds, default 1.0.
        allow_empty:    If True, return empty responses directly without retry.
        role:           Caller role label for logging, such as orchestrator or sub_agent.
        **kwargs:       Keyword arguments passed through to ainvoke.

    Returns:
        First non-empty result; possibly empty when allow_empty is True.

    Raises:
        RuntimeError when two consecutive responses are empty, with role in the message.
    """
    def is_empty_response(msg: Any) -> bool:
        """Check for empty responses with no tool calls or valid content

        Empty when content is None, blank, or only whitespace text blocks;
        conservatively non-empty with tool calls, non-dict text blocks, or non-str content.
        """
        if getattr(msg, "tool_calls", None):
            return False
        content = getattr(msg, "content", None)
        if content is None:
            return True
        if isinstance(content, str):
            return not content.strip()
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    return False
                text = block.get("text") or ""
                if str(text).strip():
                    return False
            return True
        return not str(content).strip()

    # first invoke, ainvoke with retry and get response
    response = await ainvoke_with_retry(
        runnable, *args, max_retries=max_retries, base_delay=base_delay, **kwargs
    )
    # check for empty response and allow_empty flag, if allow_empty or response if not empty, return response directly
    if not is_empty_response(response) or allow_empty:
        return response

    logger.warning("llm_empty_response_retry", role=role, attempt=1)

    # if the previous response is empty, resend once without backoff: 
    # input unchanged, backoff meaningless; only resend once, no infinite loop
    response = await ainvoke_with_retry(
        runnable, *args, max_retries=max_retries, base_delay=base_delay, **kwargs
    )
    # if the resent is still empty, raise RuntimeError
    if is_empty_response(response):
        logger.warning(
            "llm_empty_response",
            role=role,
            attempt=2,
        )
        raise RuntimeError(f"LLM returned empty response twice (role={role})")

    return response
