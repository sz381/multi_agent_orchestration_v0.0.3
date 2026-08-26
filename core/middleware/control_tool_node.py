"""ToolNode middleware for single-turn exclusivity of control tools.

Class provided:
- ControlAwareToolNode:             subclass of ToolNode enforcing single-turn exclusivity for control tools

Key constraints:
- Decision is based on the current turn's tool calls list itself, not a state snapshot, so true parallelism is also covered
- Control tools are exclusive per turn: when one appears, only the first control call runs, all other calls, control or normal, are rejected, no mixing allowed
- Rejected calls must get a ToolMessage with the original tool_call_id to keep message pairing
- _afunc/_func are internal langgraph methods, requirements pin langgraph==1.2.10; upgrading the version needs regression tests

Background:
- langgraph ToolNode runs multiple tool calls of one turn concurrently via
  asyncio.gather, each tool sees the same state snapshot taken before
  execution, so kernel-level validation such as current_response against
  last-win cannot distinguish parallel calls in the same turn
- In one orchestrator turn, control tools, end_orchestration,
  fanout_subagents, pause_orchestration, make_plan, edit_plan, delete_plan,
  must be exclusive: one control tool per turn, never mixed with other tools;
  otherwise parallel Command(update=...) merges in order and later writes to
  the same field overwrite earlier ones, losing tasks

Usage notes:
- Usage: node = ControlAwareToolNode(tools, control_tool_names=CONTROL_TOOL_NAMES), then wire it into StateGraph as a
            normal ToolNode, sync invoke goes through _func, async through _afunc
- control_tool_names is injected by the caller, the bundle registration site, avoiding hardcoding
- Rejection messages guide the model to send only one control call next turn, achieving self-healing
"""

import asyncio
from typing import Any, Sequence

from langchain_core.messages import ToolMessage
from langchain_core.runnables.config import (
    RunnableConfig,
    get_config_list,
    get_executor_for_config,
)
from langchain_core.tools import BaseTool
from langgraph.prebuilt.tool_node import ToolNode, ToolRuntime


class ControlAwareToolNode(ToolNode):
    """ToolNode that makes control tools exclusive within a turn.

    When a control tool call appears in the same turn, only the first control
    call runs, all other calls, control or normal, are rejected with an
    explanatory message guiding the model to retry next turn, preventing
    parallel Command updates from overwriting each other.
    """

    def __init__(
        self,
        tools: Sequence[BaseTool],
        *,
        control_tool_names: set[str],
        **kwargs: Any,
    ) -> None:
        """Initialize ControlAwareToolNode.

        Args:
            tools: tool sequence of BaseTool or callables convertible to
                BaseTool, same as the tools argument of ToolNode.
            control_tool_names: set of control tool names; tools in this set
                are exclusive per turn, only the first control call runs when
                one appears, all other calls are rejected.
            **kwargs: other arguments passed through to ToolNode, such as
                name or messages_key.
        """
        super().__init__(tools, **kwargs)
        self._control_tool_names = frozenset(control_tool_names)

    def _filter_control_calls(
        self, tool_calls: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """Exclusivity filter: control tools own the turn.

        Rules:
        - No control tool in this turn: keep all calls, normal tools can keep
            running in parallel, e.g. multiple view_file calls
        - Control tool present: keep only the first control call, reject all
            other calls, including other control tools and all normal tools,
            control calls cannot mix with other tools

        Args:
            tool_calls: all tool calls of this turn, langgraph ToolCall dicts
                with fields such as name, args, and id.

        Returns:
            (kept, rejected) tuple: kept is the calls to run, rejected is the
            calls refused, each needing a rejection ToolMessage to keep
            message pairing.
        """
        # find the first control call; pass all through when there is none
        first_control_idx = next(
            (
                i
                for i, call in enumerate(tool_calls)
                if call["name"] in self._control_tool_names
            ),
            None,
        )
        if first_control_idx is None:
            return tool_calls, []

        # control tool present: own the turn, keep the first control call, reject the rest
        kept = [tool_calls[first_control_idx]]
        rejected = [
            call for i, call in enumerate(tool_calls) if i != first_control_idx
        ]
        return kept, rejected

    def _reject_message(self, call: dict) -> ToolMessage:
        """Build a rejection ToolMessage for a rejected call.

        The message explains the control tool exclusivity rule and guides the
        model to send only one control call next turn; tool_call_id must match
        the original call's id so every tool_call has a response.

        Args:
            call: the rejected tool call, a langgraph ToolCall dict.

        Returns:
            a ToolMessage paired with the tool_call_id, content explains the
            exclusivity rule.
        """
        names = ", ".join(sorted(self._control_tool_names))
        return ToolMessage(
            content=(
                f"Control tools are exclusive: when one of [{names}] is called, "
                f"it must be the only tool call in this turn. "
                f"Skipping call to '{call['name']}'."
            ),
            tool_call_id=call["id"],
            name=call["name"],
        )

    async def _afunc(
        self,
        input: Any,
        config: RunnableConfig,
        runtime: Any,
    ) -> Any:
        """Run the current turn's tool calls asynchronously, overriding ToolNode._afunc.

        Inserts the exclusivity filter before the parent's concurrent
        execution: keep only the first control call of the turn, reject the
        rest with ToolMessages, see _filter_control_calls and _reject_message.
        The main logic is copied from ToolNode._afunc of langgraph 1.2.10,
        because langgraph offers no hook to see all tool calls of the turn
        before execution, so the only option is copying the main entry and
        inserting instrumentation.

        Args:
            input: graph node input, a message list or a state dict with a
                messages key; tool_calls of the last AIMessage are parsed and
                executed.
            config: run configuration, auto-injected by langgraph, includes
                runtime etc.
            runtime: runtime context, auto-injected by langgraph.

        Returns:
            same as the parent: a ToolMessage list or
            {messages_key: [ToolMessage]}, packaged by _combine_tool_outputs
            according to input_type.
        """
        # copied from ToolNode._afunc, langgraph 1.2.10, with the exclusivity filter inserted
        tool_calls, input_type = self._parse_input(input)
        kept_calls, rejected_calls = self._filter_control_calls(tool_calls)

        config_list = get_config_list(config, len(kept_calls))

        # build a ToolRuntime for each kept call, same as the parent
        tool_runtimes = []
        for call, cfg in zip(kept_calls, config_list, strict=False):
            state = self._extract_state(input, cfg)
            tool_runtime = ToolRuntime(
                state=state,
                tool_call_id=call["id"],
                config=cfg,
                context=runtime.context,
                store=runtime.store,
                stream_writer=runtime.stream_writer,
                tools=list(self.tools_by_name.values()),
                execution_info=runtime.execution_info,
                server_info=runtime.server_info,
            )
            tool_runtimes.append(tool_runtime)

        coros = [
            self._arun_one(call, input_type, tool_runtime)
            for call, tool_runtime in zip(kept_calls, tool_runtimes, strict=False)
        ]
        outputs = await asyncio.gather(*coros)

        # append rejection messages for rejected calls so every tool_call has a response
        outputs.extend(self._reject_message(call) for call in rejected_calls)

        return self._combine_tool_outputs(outputs, input_type)

    def _func(
        self,
        input: Any,
        config: RunnableConfig,
        runtime: Any,
    ) -> Any:
        """Run the current turn's tool calls synchronously, overriding ToolNode._func.

        Same exclusivity filter as _afunc, used when the graph runs
        synchronously via invoke; main logic copied from ToolNode._func of
        langgraph 1.2.10.

        Args:
            input: graph node input, a message list or a state dict with a
                messages key; tool_calls of the last AIMessage are parsed and
                executed.
            config: run configuration, auto-injected by langgraph, includes
                runtime etc.
            runtime: runtime context, auto-injected by langgraph.

        Returns:
            same as the parent: a ToolMessage list or
            {messages_key: [ToolMessage]}, packaged by _combine_tool_outputs
            according to input_type.
        """
        # copied from ToolNode._func, langgraph 1.2.10, with the exclusivity filter inserted
        tool_calls, input_type = self._parse_input(input)
        kept_calls, rejected_calls = self._filter_control_calls(tool_calls)

        config_list = get_config_list(config, len(kept_calls))

        # build a ToolRuntime for each kept call, same as the parent
        tool_runtimes = []
        for call, cfg in zip(kept_calls, config_list, strict=False):
            state = self._extract_state(input, cfg)
            tool_runtime = ToolRuntime(
                state=state,
                tool_call_id=call["id"],
                config=cfg,
                context=runtime.context,
                store=runtime.store,
                stream_writer=runtime.stream_writer,
                tools=list(self.tools_by_name.values()),
                execution_info=runtime.execution_info,
                server_info=runtime.server_info,
            )
            tool_runtimes.append(tool_runtime)

        # run the kept calls synchronously, same as the parent
        with get_executor_for_config(config) as executor:
            outputs = list(
                executor.map(
                    self._run_one,
                    kept_calls,
                    [input_type] * len(kept_calls),
                    tool_runtimes,
                )
            )

        # append rejection messages for rejected calls so every tool_call has a response
        outputs.extend(self._reject_message(call) for call in rejected_calls)

        return self._combine_tool_outputs(outputs, input_type)
