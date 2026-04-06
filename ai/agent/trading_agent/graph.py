from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ai.agent.runtime_context import reset_agent_context, set_agent_context

from .nodes import (
    cancel_trade_node,
    execute_trade_node,
    load_trade_draft_node,
    preview_trade_node,
    trading_agent_node,
)
from .routes import route_after_agent
from .state import TradingGraphState
from .tools import TRADING_TOOLS


class TradingWorkflow:
    def __init__(self):
        graph = StateGraph(TradingGraphState)
        graph.add_node("load_trade_draft", load_trade_draft_node)
        graph.add_node("trading_agent", trading_agent_node)
        graph.add_node("tool_node", ToolNode(TRADING_TOOLS))
        graph.add_node("preview_trade", preview_trade_node)
        graph.add_node("execute_trade", execute_trade_node)
        graph.add_node("cancel_trade", cancel_trade_node)

        graph.add_edge(START, "load_trade_draft")
        graph.add_edge("load_trade_draft", "trading_agent")
        graph.add_conditional_edges(
            "trading_agent",
            route_after_agent,
            {
                "tool_node": "tool_node",
                "preview_trade": "preview_trade",
                "execute_trade": "execute_trade",
                "cancel_trade": "cancel_trade",
                "end": END,
            },
        )
        graph.add_edge("tool_node", "trading_agent")
        graph.add_edge("preview_trade", END)
        graph.add_edge("execute_trade", END)
        graph.add_edge("cancel_trade", END)

        self.graph = graph.compile()

    def execute(
        self,
        *,
        user_id: int,
        session_id: int,
        query: str,
        messages: list[BaseMessage] | None = None,
    ) -> str:
        result = self.execute_with_debug(
            user_id=user_id,
            session_id=session_id,
            query=query,
            messages=messages,
        )
        return str(result.get("response_text") or "当前交易请求处理完成。")

    def execute_with_debug(
        self,
        *,
        user_id: int,
        session_id: int,
        query: str,
        messages: list[BaseMessage] | None = None,
    ) -> dict:
        token = set_agent_context({"user_id": user_id, "session_id": session_id})
        try:
            result = self.graph.invoke(
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "user_message": query,
                    "messages": messages or [HumanMessage(content=query)],
                    "tool_iteration_count": 0,
                    "max_tool_iterations": 6,
                }
            )
            return {
                "response_text": str(result.get("response_text") or "当前交易请求处理完成。"),
                "draft": result.get("draft") or {},
                "draft_status": result.get("draft_status"),
                "agent_result": result.get("agent_result") or {},
                "tool_call_log": result.get("tool_call_log") or [],
            }
        finally:
            reset_agent_context(token)
