from __future__ import annotations

from collections.abc import Iterator
import re
import time
from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from .nodes import (
    GENERIC_WORKFLOW_ERROR_MESSAGE,
    decide_intent,
    finalize_response,
    general_agent,
    news_agent,
    prepare_session,
    route_after_intent,
    trading_agent,
)


class GlobalAgentState(TypedDict):
    user: Any
    query: str
    session_id: NotRequired[int | None]

    lc_messages: NotRequired[list[Any]]
    has_active_trade_draft: NotRequired[bool]

    route: NotRequired[Literal["NEWS", "GENERAL", "TRADING", "ERROR"]]
    response_message: NotRequired[str]


class GraphResponseEvent(TypedDict):
    event: str
    data: dict[str, Any]


def _iter_fake_stream_chunks(text: str, *, max_chunk_size: int = 72) -> Iterator[str]:
    content = str(text or "").strip()
    if not content:
        return

    parts = re.split(r"(\n\n|[。！？!?]\s*)", content)
    buffer = ""

    for part in parts:
        if not part:
            continue
        candidate = f"{buffer}{part}"
        if len(candidate) <= max_chunk_size:
            buffer = candidate
            continue
        if buffer:
            yield buffer
            buffer = ""
        if len(part) <= max_chunk_size:
            buffer = part
            continue
        start = 0
        while start < len(part):
            yield part[start:start + max_chunk_size]
            start += max_chunk_size

    if buffer:
        yield buffer


class GlobalAgentWorkflow:
    def __init__(self):
        graph = StateGraph(GlobalAgentState)
        graph.add_node("prepare_session", prepare_session)
        graph.add_node("decide_intent", decide_intent)
        graph.add_node("general_agent", general_agent)
        graph.add_node("news_agent", news_agent)
        graph.add_node("trading_agent", trading_agent)
        graph.add_node("finalize", finalize_response)

        graph.add_edge(START, "prepare_session")
        graph.add_edge("prepare_session", "decide_intent")
        graph.add_conditional_edges(
            "decide_intent",
            route_after_intent,
            {
                "general_agent": "general_agent",
                "news_agent": "news_agent",
                "trading_agent": "trading_agent",
                "finalize": "finalize",
            },
        )
        graph.add_edge("general_agent", "finalize")
        graph.add_edge("news_agent", "finalize")
        graph.add_edge("trading_agent", "finalize")
        graph.add_edge("finalize", END)

        self.graph = graph.compile()

    @staticmethod
    def _emit_fake_stream(*, content: str) -> Iterator[GraphResponseEvent]:
        for chunk in _iter_fake_stream_chunks(content):
            yield {
                "event": "delta",
                "data": {
                    "content": chunk,
                },
            }
            time.sleep(0.05)

    def stream_message(
        self,
        *,
        user: Any,
        query: str,
        session_id: int | None = None,
    ) -> Iterator[GraphResponseEvent]:
        initial_state: GlobalAgentState = {
            "user": user,
            "query": query,
            "session_id": session_id,
        }
        latest_state: dict[str, Any] = dict(initial_state)
        session_emitted = False

        for snapshot in self.graph.stream(initial_state, stream_mode="values"):
            if not isinstance(snapshot, dict):
                continue
            latest_state = snapshot
            current_session_id = latest_state.get("session_id")
            if not session_emitted and current_session_id is not None:
                yield {
                    "event": "session",
                    "data": {
                        "session_id": current_session_id,
                    },
                }
                session_emitted = True

        answer = str(latest_state.get("response_message") or GENERIC_WORKFLOW_ERROR_MESSAGE).strip()
        yield from self._emit_fake_stream(content=answer)
        yield {
            "event": "done",
            "data": {
                "session_id": latest_state.get("session_id"),
            },
        }
