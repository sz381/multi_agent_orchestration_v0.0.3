"""控制类工具单轮互斥的 ToolNode 中间件。

提供类：
- ControlAwareToolNode:    子类化 ToolNode，对控制类工具做单轮互斥

关键约束：
- 判定基于本轮 tool calls 列表本身，不依赖 state 快照，真并行也拦得住
- 控制类工具独占本轮：出现控制类工具时只执行第一个控制调用，其余所有调用
  （其他控制类 + 普通工具）一律拒绝，不可混用
- 被拒绝的调用必须补 ToolMessage（tool_call_id 匹配原 call），保证消息配对
- _afunc/_func 是 langgraph 内部方法（requirements 已锁 langgraph==1.2.10），
  升级版本需回归测试

背景：
- langgraph 的 ToolNode 对同一轮的多个 tool calls 是并发执行的（asyncio.gather），
  每个工具拿到的是执行前同一份 state 快照——因此 kernel 层的参数校验
  （如 current_response 防 last-win）无法区分同轮并行调用
- orchestrator 单轮决策中，控制类工具（end_orchestration、fanout_subagents、
  pause_orchestration、make_plan、edit_plan、delete_plan）必须独占本轮：
  一次只能调用一个控制工具，且不能与其他任何工具混用；否则并行的
  Command(update=...) 按序合并时同字段后写覆盖前写，导致任务丢失

使用注意：
- 用法：node = ControlAwareToolNode(tools, control_tool_names=CONTROL_TOOL_NAMES)
  然后作为普通 ToolNode 节点接入 StateGraph（同步 invoke 走 _func，异步走 _afunc）
- control_tool_names 由调用方（bundle 注册处）注入，避免硬编码
- 拒绝消息引导模型下轮只发一个控制调用，实现自愈
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
    """控制类工具本轮独占的 ToolNode。

    同一轮出现控制类工具调用时，只执行第一个控制调用，其余所有调用
    （其他控制类 + 普通工具）被拒绝并返回说明消息（引导模型下轮重试），
    防止并行 Command 更新互相覆盖。
    """

    def __init__(
        self,
        tools: Sequence[BaseTool],
        *,
        control_tool_names: set[str],
        **kwargs: Any,
    ) -> None:
        """初始化 ControlAwareToolNode。

        Args:
            tools: 工具序列（BaseTool 或可转换为 BaseTool 的可调用对象），
                与 ToolNode 的 tools 参数一致。
            control_tool_names: 控制类工具名集合；命中该集合的工具本轮独占，
                出现时只执行第一个控制调用，其余调用一律拒绝。
            **kwargs: 透传给 ToolNode 的其他参数（name/messages_key 等）。
        """
        super().__init__(tools, **kwargs)
        self._control_tool_names = frozenset(control_tool_names)

    def _filter_control_calls(
        self, tool_calls: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """互斥过滤：控制类工具本轮独占。

        规则：
        - 本轮无控制类工具：全部保留，普通工具可继续并行（view_file 等可多个）
        - 本轮有控制类工具：只保留第一个控制类调用，其余所有调用
          （其他控制类 + 所有普通工具）一律拒绝，控制调用不可与其他工具混用

        Args:
            tool_calls: 本轮全部工具调用列表（langgraph ToolCall 字典，
                含 name/args/id 等字段）。

        Returns:
            (kept, rejected) 二元组：kept 为保留执行的调用列表；
            rejected 为被拒绝的调用列表（需补拒绝 ToolMessage 保证消息配对）。
        """
        # 找第一个控制类调用；无控制类则全部放行
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

        # 有控制类：独占本轮——保留第一个控制调用，其余全部拒绝
        kept = [tool_calls[first_control_idx]]
        rejected = [
            call for i, call in enumerate(tool_calls) if i != first_control_idx
        ]
        return kept, rejected

    def _reject_message(self, call: dict) -> ToolMessage:
        """为被拒绝的调用构造拒绝 ToolMessage。

        消息内容说明控制类工具独占规则，引导模型下轮只发一个控制调用；
        tool_call_id 必须匹配原 call 的 id，保证每个 tool_call 都有对应响应。

        Args:
            call: 被拒绝的工具调用（langgraph ToolCall 字典）。

        Returns:
            配对 tool_call_id 的 ToolMessage，content 为互斥规则说明。
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
        """异步执行本轮工具调用（覆写 ToolNode._afunc）。

        在父类并发执行之前插入互斥过滤：控制类工具同轮只保留第一个，
        其余被拒绝并补 ToolMessage（见 _filter_control_calls/_reject_message）。
        主体逻辑复制自 langgraph 1.2.10 的 ToolNode._afunc——langgraph 没有
        提供"执行前可见本轮全部 tool calls"的钩子，只能在主入口复制后插桩。

        Args:
            input: 图节点输入：消息列表或含 messages 键的 state 字典，
                最后一条 AIMessage 的 tool_calls 将被解析执行。
            config: 运行配置（langgraph 自动注入，含 runtime 等）。
            runtime: 运行时上下文（langgraph 自动注入）。

        Returns:
            与父类一致：ToolMessage 列表或 {messages_key: [ToolMessage]}，
            由 _combine_tool_outputs 按 input_type 打包。
        """
        # 复制自 ToolNode._afunc（langgraph 1.2.10），插入互斥过滤
        tool_calls, input_type = self._parse_input(input)
        kept_calls, rejected_calls = self._filter_control_calls(tool_calls)

        config_list = get_config_list(config, len(kept_calls))

        # 为保留的调用构造 ToolRuntime（与父类一致）
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

        # 被拒绝的调用补拒绝消息，保证每个 tool_call 都有对应响应
        outputs.extend(self._reject_message(call) for call in rejected_calls)

        return self._combine_tool_outputs(outputs, input_type)

    def _func(
        self,
        input: Any,
        config: RunnableConfig,
        runtime: Any,
    ) -> Any:
        """同步执行本轮工具调用（覆写 ToolNode._func）。

        与 _afunc 相同的互斥过滤逻辑，供图以同步方式（invoke）运行时使用；
        主体逻辑复制自 langgraph 1.2.10 的 ToolNode._func。

        Args:
            input: 图节点输入：消息列表或含 messages 键的 state 字典，
                最后一条 AIMessage 的 tool_calls 将被解析执行。
            config: 运行配置（langgraph 自动注入，含 runtime 等）。
            runtime: 运行时上下文（langgraph 自动注入）。

        Returns:
            与父类一致：ToolMessage 列表或 {messages_key: [ToolMessage]}，
            由 _combine_tool_outputs 按 input_type 打包。
        """
        # 复制自 ToolNode._func（langgraph 1.2.10），插入互斥过滤
        tool_calls, input_type = self._parse_input(input)
        kept_calls, rejected_calls = self._filter_control_calls(tool_calls)

        config_list = get_config_list(config, len(kept_calls))

        # 为保留的调用构造 ToolRuntime（与父类一致）
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

        # 同步执行保留的调用（与父类一致）
        with get_executor_for_config(config) as executor:
            outputs = list(
                executor.map(
                    self._run_one,
                    kept_calls,
                    [input_type] * len(kept_calls),
                    tool_runtimes,
                )
            )

        # 被拒绝的调用补拒绝消息，保证每个 tool_call 都有对应响应
        outputs.extend(self._reject_message(call) for call in rejected_calls)

        return self._combine_tool_outputs(outputs, input_type)
