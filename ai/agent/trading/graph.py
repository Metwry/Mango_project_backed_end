from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from ai.agent.runtime_context import reset_agent_context, set_agent_context
from ai.tools.trading.tools import TRADING_TOOLS

from .nodes import (
    cancel_trade_node,
    execute_trade_node,
    load_trade_draft_node,
    preview_trade_node,
    trading_agent_node,
)
from .schema import render_response


class TradingGraphState(TypedDict):
    user_id: int
    session_id: int
    user_message: str

    messages: NotRequired[Annotated[list[BaseMessage], add_messages]]

    draft: NotRequired[dict[str, Any]]
    draft_status: NotRequired[
        Literal["EMPTY", "DRAFT_EDITING", "READY_CONFIRM", "COMPLETED", "CANCELLED"]
    ]

    tool_iteration_count: NotRequired[int]
    next_action: NotRequired[
        Literal["TOOL", "ASK_CLARIFY", "PREVIEW", "EXECUTE", "CANCEL", "INVALID"]
    ]

    event: NotRequired[str]
    payload: NotRequired[dict[str, Any]]


def route_after_agent(state: dict) -> str:
    mapping = {
        "TOOL": "tool_node",
        "ASK_CLARIFY": "end",
        "PREVIEW": "preview_trade",
        "EXECUTE": "execute_trade",
        "CANCEL": "cancel_trade",
        "INVALID": "end",
    }
    return mapping.get(state.get("next_action", "INVALID"), "end")


class TradingWorkflow:
    def __init__(self):
        graph = StateGraph(TradingGraphState)
        graph.add_node("load_draft", load_trade_draft_node)
        graph.add_node("trade_agent", trading_agent_node)
        graph.add_node("run_tools", ToolNode(TRADING_TOOLS))
        graph.add_node("preview", preview_trade_node)
        graph.add_node("submit", execute_trade_node)
        graph.add_node("cancel", cancel_trade_node)

        graph.add_edge(START, "load_draft")
        graph.add_edge("load_draft", "trade_agent")
        graph.add_conditional_edges(
            "trade_agent",
            route_after_agent,
            {
                "tool_node": "run_tools",
                "preview_trade": "preview",
                "execute_trade": "submit",
                "cancel_trade": "cancel",
                "end": END,
            },
        )
        graph.add_edge("run_tools", "trade_agent")
        graph.add_edge("preview", END)
        graph.add_edge("submit", END)
        graph.add_edge("cancel", END)

        self.graph = graph.compile()

    def run(
        self,
        *,
        user_id: int,
        session_id: int,
        query: str,
        messages: list[BaseMessage] | None = None,
    ) -> dict:
        token = set_agent_context({"user_id": user_id, "session_id": session_id})
        try:
            return self.graph.invoke(
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "user_message": query,
                    "messages": messages or [HumanMessage(content=query)],
                    "tool_iteration_count": 0,
                }
            )
        finally:
            reset_agent_context(token)

    def stream_run(
        self,
        *,
        user_id: int,
        session_id: int,
        query: str,
        messages: list[BaseMessage] | None = None,
    ) -> Iterator[dict[str, Any]]:
        token = set_agent_context({"user_id": user_id, "session_id": session_id})
        try:
            final_result: dict[str, Any] | None = None
            stream_input = {
                "user_id": user_id,
                "session_id": session_id,
                "user_message": query,
                "messages": messages or [HumanMessage(content=query)],
                "tool_iteration_count": 0,
            }
            for update in self.graph.stream(stream_input, stream_mode="updates"):
                if not isinstance(update, dict):
                    continue
                for node_name, payload in update.items():
                    if not isinstance(payload, dict):
                        continue
                    final_result = payload
                    status_event = _build_status_event(node_name=node_name, payload=payload)
                    if status_event is not None:
                        yield status_event
            if final_result is None:
                final_result = self.run(
                    user_id=user_id,
                    session_id=session_id,
                    query=query,
                    messages=messages,
                )
            response_message = render_response(
                event=str(final_result.get("event") or ""),
                payload=final_result.get("payload") if isinstance(final_result.get("payload"), dict) else {},
            )
            yield {
                "event": "done",
                "data": {
                    **final_result,
                    "response_message": response_message,
                },
            }
        finally:
            reset_agent_context(token)

    def execute(
        self,
        *,
        user_id: int,
        session_id: int,
        query: str,
        messages: list[BaseMessage] | None = None,
    ) -> str:
        result = self.run(
            user_id=user_id,
            session_id=session_id,
            query=query,
            messages=messages,
        )
        return render_response(
            event=str(result.get("event") or ""),
            payload=result.get("payload") if isinstance(result.get("payload"), dict) else {},
        )


def _build_status_event(*, node_name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if node_name == "load_draft":
        return {
            "event": "status",
            "data": {
                "stage": "drafting",
                "message": "正在读取交易草稿",
            },
        }
    if node_name == "trade_agent":
        return {
            "event": "status",
            "data": {
                "stage": "drafting",
                "message": "正在解析交易意图",
            },
        }
    if node_name == "run_tools":
        return {
            "event": "status",
            "data": {
                "stage": "tool",
                "message": "正在查询账户、标的和行情",
            },
        }
    if node_name == "preview":
        return {
            "event": "status",
            "data": {
                "stage": "preview",
                "message": "正在生成交易预览",
            },
        }
    if node_name == "submit":
        return {
            "event": "status",
            "data": {
                "stage": "execute",
                "message": "正在提交交易",
            },
        }
    if node_name == "cancel":
        return {
            "event": "status",
            "data": {
                "stage": "cancel",
                "message": "正在取消交易",
            },
        }
    return None
