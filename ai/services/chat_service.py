from __future__ import annotations
from typing import TypedDict
from django.db.models import Max
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ai.agent.agent import ReactAgent
from ai.agent.trading_agent import TradingWorkflow
from ai.models import ChatMessage, ChatSession
from ai.services.trade_workflow_store import has_active_trade_draft

class SessionMessage(TypedDict):
    role: str
    content: str


_react_agent: ReactAgent | None = None
_trading_workflow: TradingWorkflow | None = None


def _get_react_agent() -> ReactAgent:
    global _react_agent
    if _react_agent is None:
        _react_agent = ReactAgent()
    return _react_agent


def _get_trading_workflow() -> TradingWorkflow:
    global _trading_workflow
    if _trading_workflow is None:
        _trading_workflow = TradingWorkflow()
    return _trading_workflow


def _looks_like_trade_query(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    keywords = ["买", "卖", "加仓", "减仓", "清仓", "确认", "取消", "执行"]
    return any(token in text for token in keywords)


def _should_use_trading_workflow(*, user, session: ChatSession, query: str) -> bool:
    if has_active_trade_draft(user_id=user.id, session_id=session.id):
        return True
    return _looks_like_trade_query(query)


def get_or_create_session(*, user, session_id: int | None = None, title: str | None = None) -> ChatSession:
    if session_id is not None:
        return ChatSession.objects.get(id=session_id, user=user)

    session_title = (title or "").strip() or "新对话"
    return ChatSession.objects.create(user=user, title=session_title)


def next_message_sequence(*, session: ChatSession) -> int:
    current_max = session.messages.aggregate(max_sequence=Max("sequence"))["max_sequence"]
    return int(current_max or 0) + 1


def append_message(*, session: ChatSession, role: str, content: str) -> ChatMessage:
    message = ChatMessage.objects.create(
        session=session,
        role=role,
        content=content,
        sequence=next_message_sequence(session=session),
    )
    session.save(update_fields=["updated_at"])
    return message


def append_user_message(*, session: ChatSession, content: str) -> ChatMessage:
    return append_message(session=session, role=ChatMessage.Role.USER, content=content)


def append_assistant_message(*, session: ChatSession, content: str) -> ChatMessage:
    return append_message(session=session, role=ChatMessage.Role.ASSISTANT, content=content)


def build_session_messages(*, session: ChatSession, max_messages: int | None = 30) -> list[SessionMessage]:
    queryset = session.messages.order_by("-sequence", "-id")
    if max_messages is not None:
        queryset = queryset[:max_messages]

    rows = list(queryset)
    rows.reverse()

    return [
        {
            "role": message.role.lower(),
            "content": message.content,
        }
        for message in rows
    ]


def build_langchain_messages(*, session: ChatSession, max_messages: int | None = 30) -> list[BaseMessage]:
    session_messages = build_session_messages(session=session, max_messages=max_messages)
    result: list[BaseMessage] = []
    for item in session_messages:
        role = str(item.get("role") or "").upper()
        content = str(item.get("content") or "")
        if role == ChatMessage.Role.USER:
            result.append(HumanMessage(content=content))
        elif role == ChatMessage.Role.ASSISTANT:
            result.append(AIMessage(content=content))
    return result

def run_chat(*, user, query: str, session_id: int | None = None) -> dict:
    session = get_or_create_session(
        user = user,
        session_id=session_id,
        title=query[:20]
    )
    append_user_message(session=session, content=query)
    messages = build_session_messages(session=session)
    lc_messages = build_langchain_messages(session=session)
    if _should_use_trading_workflow(user=user, session=session, query=query):
        answer = _get_trading_workflow().execute(
            user_id=user.id,
            session_id=session.id,
            query=query,
            messages=lc_messages,
        )
    else:
        answer = _get_react_agent().execute(
            messages=messages,
            context={
                "user_id": user.id,
                "session_id": session.id,
            },
        )
    append_assistant_message(session=session, content=answer)
    return {
        "session_id": session.id,
        "answer": answer,
    }


def stream_chat(*, user, query: str, session_id: int | None = None):
    session = get_or_create_session(
        user=user,
        session_id=session_id,
        title=query[:20],
    )
    append_user_message(session=session, content=query)
    messages = build_session_messages(session=session)
    lc_messages = build_langchain_messages(session=session)
    context = {
        "user_id": user.id,
        "session_id": session.id,
    }

    yield {
        "event": "start",
        "data": {
            "session_id": session.id,
        },
    }

    chunks: list[str] = []
    try:
        if _should_use_trading_workflow(user=user, session=session, query=query):
            answer = _get_trading_workflow().execute(
                user_id=user.id,
                session_id=session.id,
                query=query,
                messages=lc_messages,
            )
            chunks.append(answer)
            yield {
                "event": "delta",
                "data": answer,
            }
        else:
            for chunk in _get_react_agent().stream_execute(messages=messages, context=context):
                if not chunk:
                    continue
                chunks.append(chunk)
                yield {
                    "event": "delta",
                    "data": chunk,
                }

        answer = "".join(chunks).strip()
        append_assistant_message(session=session, content=answer)
        yield {
            "event": "done",
            "data": {
                "session_id": session.id,
            },
        }
    except Exception:
        error_message = "当前请求处理失败，请稍后重试。"
        append_assistant_message(session=session, content=error_message)
        yield {
            "event": "error",
            "data": {
                "session_id": session.id,
                "message": error_message,
            },
        }
