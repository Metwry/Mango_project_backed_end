from __future__ import annotations

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
    route_after_agent,
    trading_agent_node,
)


class TradingGraphState(TypedDict):
    user_id: int
    session_id: int

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
                    "messages": messages or [HumanMessage(content=query)],
                    "tool_iteration_count": 0,
                }
            )
        finally:
            reset_agent_context(token)
