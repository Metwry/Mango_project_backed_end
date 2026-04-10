from __future__ import annotations

from collections.abc import Iterator
import re
import time
from typing import Any, Literal, NotRequired, TypedDict

from .nodes import (
    GENERIC_WORKFLOW_ERROR_MESSAGE,
    append_assistant_message,
    decide_intent,
    general_agent,
    news_agent,
    prepare_session,
    trading_agent,
)


class GlobalAgentState(TypedDict):
    user: Any
    query: str
    session_id: NotRequired[int | None]

    session: NotRequired[Any]
    session_messages: NotRequired[list[dict[str, str]]]
    lc_messages: NotRequired[list[Any]]
    has_active_trade_draft: NotRequired[bool]

    route: NotRequired[Literal["NEWS", "GENERAL", "TRADING", "ERROR"]]
    response_message: NotRequired[str]
    emit_direct_response: NotRequired[bool]


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
        pass

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
        state: GlobalAgentState = {
            "user": user,
            "query": query,
            "session_id": session_id,
        }

        state.update(prepare_session(state))
        current_session_id = state["session_id"]
        yield {
            "event": "session",
            "data": {
                "session_id": current_session_id,
            },
        }

        state.update(decide_intent(state))
        route = state.get("route", "GENERAL")

        if route in {"GENERAL", "NEWS"}:
            response = general_agent(state) if route == "GENERAL" else news_agent(state)
            answer = str(response.get("response_message") or GENERIC_WORKFLOW_ERROR_MESSAGE).strip()
        elif route == "TRADING":
            trading_workflow = trading_agent(state, stream=True)
            final_payload: dict[str, Any] | None = None
            for event in trading_workflow:
                if event["event"] == "status":
                    yield event
                    continue
                if event["event"] == "done":
                    final_payload = event["data"] if isinstance(event["data"], dict) else {}
            response_message = (
                str(final_payload.get("response_message") or "").strip()
                if isinstance(final_payload, dict)
                else ""
            )
            answer = response_message or GENERIC_WORKFLOW_ERROR_MESSAGE
        else:
            answer = str(state.get("response_message") or GENERIC_WORKFLOW_ERROR_MESSAGE).strip()

        append_assistant_message(session=state["session"], content=answer)
        yield from self._emit_fake_stream(content=answer)
        yield {
            "event": "done",
            "data": {
                "session_id": current_session_id,
            },
        }
