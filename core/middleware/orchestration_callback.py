"""Callback handler carrying agent identity through the whole run

Class provided:
- OrchestrationCallBack:         AsyncCallbackHandler tracking identity across LLM runs and tool runs

Key constraints:
- Identity comes only from metadata injected by bind_identity, the callback never guesses
- Three contexts hold one identity chain: _llm_ctx keyed by LLM run_id, _tool_call_ctx keyed by tool_call_id, _tool_run_ctx keyed by tool run_id
- Lifecycle closes at both ends: on_chat_model_start registers and on_llm_end or on_llm_error unregisters, on_tool_start registers and on_tool_end or on_tool_error unregisters
- raise_error is True, a broken chain raises ValueError at the source instead of dropping events silently
- Rejected tool calls never execute, so ControlAwareToolNode calls discard_rejected_tool_calls to clean their entries

Callback Handler Provided:
- on_chat_model_start:      Run when a chat model starts running.
- on_llm_end:               Run when the model ends running.
- on_llm_error:             Run when LLM errors.
- on_tool_start:            Run when the tool starts running.
- on_tool_end:              Run when the tool ends running.
- on_tool_error:            Run when tool errors.
- on_llm_new_token:         Run on new output token. Only available when streaming is enabled.
"""

from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.outputs import LLMResult, GenerationChunk, ChatGenerationChunk

from core.middleware.constants import AGENT_ID, AGENT_NAME, AGENT_ROLE, TASK_ID, TASK_NAME
from core.middleware.identity_injection import identity_from_metadata
from utils.logging import get_logger

logger = get_logger(__name__)


class OrchestrationCallBack(AsyncCallbackHandler):
    """Identity-tracking callback for the whole orchestration run

    Holds three contexts passing identity from the LLM run to its tool
    runs, and pops every entry in the hook that registered it or in the
    error hook when the run fails.
    """

    raise_error = True

    def __init__(self):
        self._llm_ctx: dict[UUID, dict] = {}
        self._tool_call_ctx: dict[str, dict] = {}
        self._tool_run_ctx: dict[UUID, tuple[str, dict]] = {}

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

        Registers the identity in _llm_ctx keyed by run_id; raises when the
        metadata carries no identity, before the API request is sent.
        """
        # Extract identity from metadata and check for its existence
        # identity will be and should be binded before this callback is triggered by orchestrator node or subagent node
        identity = identity_from_metadata(metadata)
        if identity is None:
            raise ValueError(
                f"LLM run {run_id} carries no identity in metadata; "
                "the calling node must call bind_identity before invoking the model"
            )

        # bind identity to llm_ctx using run_id as key for the future identity lookup
        self._llm_ctx[run_id] = identity

        if identity[AGENT_NAME] == "orchestrator":
            logger.debug(
                "on_llm_start",
                agent_name=identity[AGENT_NAME],
                agent_id=identity[AGENT_ID],
                agent_role=identity[AGENT_ROLE],
                run_id=str(run_id),
            )
        else:
            logger.debug(
                "on_llm_start",
                agent_name=identity[AGENT_NAME],
                agent_id=identity[AGENT_ID],
                agent_role=identity[AGENT_ROLE],
                task_id=identity[TASK_ID],
                task_name=identity[TASK_NAME],
                run_id=str(run_id),
            )

        # log the size of ctx for debugging purposes
        # the healthy status should be 
        # " llm_ctx_cnt=1 tool_call_ctx_cnt=0 tool_run_ctx_cnt=0 "
        logger.debug(
            "ctx_size",
            llm_ctx_cnt=len(self._llm_ctx),
            tool_call_ctx_cnt=len(self._tool_call_ctx),
            tool_run_ctx_cnt=len(self._tool_run_ctx),
        )

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

        Pops the identity from _llm_ctx and registers it in _tool_call_ctx
        for every tool call of the response, so each child tool run can
        claim its owner later by tool_call_id.
        """
        # clean the llm_ctx to avoid infinite growth after the usage
        # Extract identity from llm_ctx using run_id, and check for its existence
        identity = self._llm_ctx.pop(run_id, None)
        if identity is None:
            raise ValueError(f"LLM run {run_id} carries no identity in metadata")

        # Extract tool calls from response
        msg = response.generations[0][0].message
        if isinstance(msg, AIMessage):
            tool_calls = msg.tool_calls
        else:
            tool_calls = []

        # Extract tool call IDs from tool calls and check for their existence
        # then bind tool call IDs and identity to tool call context using tool call ID as key for future lookup purposes
        for tool_call in tool_calls:
            tool_call_id = tool_call.get("id")
            if not tool_call_id:
                raise ValueError(
                    f"Tool call from {identity[AGENT_ID]} carries no id, name={tool_call.get('name')}"
                )
            self._tool_call_ctx[tool_call_id] = identity

        logger.debug(
            "on_llm_end",
            agent_name=identity[AGENT_NAME],
            agent_id=identity[AGENT_ID],
            tool_call_cnt=len(tool_calls),
            tool_calls=[call['name'] for call in tool_calls],
            run_id=str(run_id),
        )

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

        Pops the identity from _llm_ctx the same way on_llm_end does, so a
        failed run never leaks its entry; logs only, the call has already
        failed.
        """
        # clean the llm_ctx when error occurs
        self._llm_ctx.pop(run_id, None)
        logger.error(
            "on_llm_error", 
            error=str(error)[:300], 
            run_id=str(run_id)
        )

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

        Claims the identity from _tool_call_ctx by tool_call_id and stores
        a tuple of tool_call_id and identity in _tool_run_ctx keyed by this
        tool run_id, because on_tool_end receives no tool_call_id.
        """
        # Extract tool_call_id from kwargs，and check for its existence
        tool_call_id = kwargs.get("tool_call_id", "")
        if not tool_call_id:
            raise ValueError(f"tool run {run_id} carries no tool_call_id in kwargs")

        # Extract identity from _tool_call_ctx using tool_call_id, and check for its existence
        identity = self._tool_call_ctx.pop(tool_call_id, None)
        if identity is None:
            raise ValueError(
                f"tool_call_id {tool_call_id} has no identity in _tool_call_ctx; "
                "the LLM run that produced it must register it in on_llm_end"
            )

        # bind tool_call_id and identity to tool_run_ctx, because at the end of tool run,
        # we need to use the run_id to find the exact tool_call_id and push event to the bridge
        self._tool_run_ctx[run_id] = (tool_call_id, identity)

        logger.debug(
            "on_tool_start",
            agent_name=identity[AGENT_NAME],
            agent_id=identity[AGENT_ID],
            tool_name=serialized.get("name", ""),
            tool_input=str(inputs)[:86],
            tool_call_id=tool_call_id,
            run_id=str(run_id),
        )

        # push_event 
        # push_event to the client here, future logic

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

        Pops the tuple from _tool_run_ctx by run_id and recovers the owner
        identity; raises when on_tool_start has not completed.
        """
        # Extract tool_call_id and identity from tool_run_ctx using run_id, and check for their existence
        tc_record = self._tool_run_ctx.pop(run_id, None)
        if tc_record is None:
            raise ValueError(
                f"tool run {run_id} carries no record in _tool_run_ctx; "
                "on_tool_start must have completed to register it"
            )
        tool_call_id, identity = tc_record

        logger.debug(
            "on_tool_end",
            agent_id=identity[AGENT_ID],
            tool_name=kwargs.get("name", ""),
            tool_call_id=tool_call_id,
            output_type=type(output).__name__,
            output_size=len(str(output)),
            run_id=str(run_id),
        )

        # push_event 
        # push_event to the client here, future logic

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

        Pops the tuple from _tool_run_ctx the same way on_tool_end does, so
        a failed tool run never leaks its entry; raises when the record is
        missing, which means the chain broke beyond the original error.
        """
        # clear the _tool_run_ctx when error occurs
        # this is not the tool calling error, it is about some serious things that the system internal
        # or the system itself has underlying problems, we need to raise an error and stop the execution
        # no tc_record and identity error. CHAIN_BREAKING ERROR
        tc_record = self._tool_run_ctx.pop(run_id, None)
        if tc_record is None:
            raise ValueError(
                f"tool run {run_id} carries no record in _tool_run_ctx, "
                f"original error: {str(error)[:200]}; "
                "on_tool_start must have completed to register it"
            )

        # Extract tool_call_id and identity from tool_run_ctx using run_id
        tool_call_id, identity = tc_record

        logger.error(
            "on_tool_error",
            agent_id=identity[AGENT_ID],
            tool_call_id=tool_call_id,
            error=str(error)[:300],
            run_id=str(run_id),
        )

        # push_event 
        # push_event to the client here, future logic

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

        Reads the identity from _llm_ctx without popping, because on_llm_end
        still needs it later; empty chunks are skipped before the lookup.
        """
        # this is important, since llm invokes involves lots of empty chunks, we need to skip them
        if not token:
            return

        # get identity from llm_ctx using run_id, and check for its existence
        identity = self._llm_ctx.get(run_id, None)
        if not identity:
            raise ValueError(f"LLM run {run_id} carries no identity in metadata")

        # logger.debug(
        #     "on_llm_new_token",
        #     agent_id=identity[AGENT_ID],
        #     token=token,
        # )

        # push_stream
        # push_stream to the client here, future logic

    def discard_rejected_tool_calls(self, rejected_calls: list[dict]) -> None:
        """Drop the ctx entries of rejected tool calls

        Called by ControlAwareToolNode after exclusivity filtering.
        Rejected calls never execute, on_tool_start never fires for them,
        nobody else pops their entries.

        Args:
            rejected_calls: the rejected tool call dicts, each carrying id
                and name.
        """
        for call in rejected_calls:
            identity = self._tool_call_ctx.pop(call["id"], None)
            if identity is None:
                raise ValueError(
                    f"rejected tool_call_id {call['id']} carries no identity in _tool_call_ctx; "
                    "ControlAwareToolNode must be wired with the same handler instance "
                    "that is injected into config callbacks"
                )
            logger.debug(
                "tool_call_ctx_discarded_due_to_tool_call_rejection",
                agent_id=identity[AGENT_ID],
                tool_name=call["name"],
                tool_call_id=call["id"],
            )
