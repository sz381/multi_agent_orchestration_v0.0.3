"""FILE HEADER HERE

DESCRIPTIONS HERE

Callback Handler Provided:
- on_chat_model_start:      Run when a chat model starts running.
- on_llm_end:               Run when the model ends running.
- on_llm_error:             Run when LLM errors.
- on_tool_start:            Run when the tool starts running.
- on_tool_end:              Run when the tool ends running.
- on_tool_error:            Run when tool errors.
- on_llm_new_token:         Run on new output token. Only available when streaming is enabled.
"""

class OrchestrationCallBack(AsyncCallbackHandler):
    """HEADER HERE

    DESCRIPTIONS HERE
    """

    def __init__(self):
        pass

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs
    ) -> None:
        """Run when a chat model starts running.

        """
        pass

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs
    ) -> None:
        """Run when the model ends running.

        """
        pass

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs
    ) -> None:
        """Run when LLM errors.

        """
        pass

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs
    ) -> None:
        """Run when the tool starts running.

        """
        pass

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs
    ) -> None:
        """Run when the tool ends running.

        """
        pass

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs
    ) -> None:
        """Run when tool errors.

        """
        pass

    async def on_llm_new_token(
        self,
        token: str | list[str | dict[str, Any]],
        *,
        chunk: GenerationChunk | ChatGenerationChunk | None = None,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs,
    ) -> None:
        """Run on new output token. Only available when streaming is enabled.

        """
        pass
