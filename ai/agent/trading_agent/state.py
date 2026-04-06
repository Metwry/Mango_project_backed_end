from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class TradingGraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]

    user_id: int
    session_id: int
    user_message: str

    draft: dict[str, Any]
    draft_status: Literal["EMPTY", "DRAFT_EDITING", "READY_CONFIRM", "COMPLETED", "CANCELLED", "EXPIRED"]
    trade_meta: dict[str, Any]

    tool_iteration_count: int
    max_tool_iterations: int
    has_tool_calls: bool
    tool_call_log: list[dict[str, Any]]
    logged_tool_call_ids: list[str]

    agent_result: dict[str, Any]
    preview_result: Literal["SUCCESS", "FAILED"]
    execute_result: Literal["SUCCESS", "FAILED", "INVALID"]
    execution_result: dict[str, Any]
    response_text: str
