from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.db.models import Max
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from ai.agent.trading.schema import render_response as render_trading_response
from ai.services.trading.store import has_active_trade_draft

if TYPE_CHECKING:
    from ai.agent.general_agent import GeneralAgent
    from ai.agent.news_agent import NewsAgent
    from ai.agent.route import RouteAgent
    from ai.agent.trading.graph import TradingWorkflow
    from ai.models import ChatMessage, ChatSession


class SessionMessage(TypedDict):
    role: str
    content: str


GENERIC_WORKFLOW_ERROR_MESSAGE = "当前请求处理失败，请稍后重试。"


_general_agent: GeneralAgent | None = None
_news_agent: NewsAgent | None = None
_route_agent: RouteAgent | None = None
_trading_workflow: TradingWorkflow | None = None


def _get_general_agent() -> GeneralAgent:
    global _general_agent
    if _general_agent is None:
        from ai.agent.general_agent import GeneralAgent

        _general_agent = GeneralAgent()
    return _general_agent


def _get_news_agent() -> NewsAgent:
    global _news_agent
    if _news_agent is None:
        from ai.agent.news_agent import NewsAgent

        _news_agent = NewsAgent()
    return _news_agent


def _get_route_agent() -> RouteAgent:
    global _route_agent
    if _route_agent is None:
        from ai.agent.route import RouteAgent

        _route_agent = RouteAgent()
    return _route_agent


def _get_trading_workflow() -> TradingWorkflow:
    global _trading_workflow
    if _trading_workflow is None:
        from ai.agent.trading.graph import TradingWorkflow

        _trading_workflow = TradingWorkflow()
    return _trading_workflow


def _get_chat_models():
    from ai.models import ChatMessage, ChatSession

    return ChatMessage, ChatSession


def get_or_create_session(*, user, session_id: int | None = None, title: str | None = None) -> ChatSession:
    _, ChatSession = _get_chat_models()
    if session_id is not None:
        return ChatSession.objects.get(id=session_id, user=user)
    session_title = (title or "").strip() or "新对话"
    return ChatSession.objects.create(user=user, title=session_title)


def next_message_sequence(*, session: ChatSession) -> int:
    current_max = session.messages.aggregate(max_sequence=Max("sequence"))["max_sequence"]
    return int(current_max or 0) + 1


def append_message(*, session: ChatSession, role: str, content: str) -> ChatMessage:
    ChatMessage, _ = _get_chat_models()
    message = ChatMessage.objects.create(
        session=session,
        role=role,
        content=content,
        sequence=next_message_sequence(session=session),
    )
    session.save(update_fields=["updated_at"])
    return message


def append_user_message(*, session: ChatSession, content: str) -> ChatMessage:
    ChatMessage, _ = _get_chat_models()
    return append_message(session=session, role=ChatMessage.Role.USER, content=content)


def append_assistant_message(*, session: ChatSession, content: str) -> ChatMessage:
    ChatMessage, _ = _get_chat_models()
    return append_message(session=session, role=ChatMessage.Role.ASSISTANT, content=content)


def build_session_messages(*, session: ChatSession, max_messages: int | None = 30) -> list[SessionMessage]:
    queryset = session.messages.order_by("-sequence", "-id")
    if max_messages is not None:
        queryset = queryset[:max_messages]
    rows = list(queryset)
    rows.reverse()
    return [{"role": message.role.lower(), "content": message.content} for message in rows]


def build_langchain_messages(*, session: ChatSession, max_messages: int | None = 30) -> list[BaseMessage]:
    ChatMessage, _ = _get_chat_models()
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


def prepare_session(state: dict) -> dict:
    session = get_or_create_session(
        user=state["user"],
        session_id=state.get("session_id"),
        title=str(state["query"])[:20],
    )
    append_user_message(session=session, content=state["query"])
    return {
        "session": session,
        "session_id": session.id,
        "session_messages": build_session_messages(session=session),
        "lc_messages": build_langchain_messages(session=session),
        "has_active_trade_draft": has_active_trade_draft(user_id=state["user"].id, session_id=session.id),
    }


def decide_intent(state: dict) -> dict:
    try:
        route = _get_route_agent().execute(
            query=state["query"],
            has_active_trade_draft=state["has_active_trade_draft"],
        )
        return {"route": route}
    except Exception:
        return {
            "route": "ERROR",
            "response_message": GENERIC_WORKFLOW_ERROR_MESSAGE,
            "emit_direct_response": True,
        }


def news_agent(state: dict) -> dict:
    try:
        answer = _get_news_agent().execute(
            messages=state["session_messages"],
            context={"user_id": state["user"].id, "session_id": state["session"].id},
        ).strip()
        return {"response_message": answer}
    except Exception:
        return {
            "response_message": GENERIC_WORKFLOW_ERROR_MESSAGE,
            "emit_direct_response": True,
        }


def general_agent(state: dict) -> dict:
    try:
        answer = _get_general_agent().execute(
            messages=state["session_messages"],
            context={"user_id": state["user"].id, "session_id": state["session"].id},
        ).strip()
        return {"response_message": answer}
    except Exception:
        return {
            "response_message": GENERIC_WORKFLOW_ERROR_MESSAGE,
            "emit_direct_response": True,
        }


def trading_agent(state: dict, *, stream: bool = False):
    try:
        workflow = _get_trading_workflow()
        if stream:
            return workflow.stream_run(
                user_id=state["user"].id,
                session_id=state["session"].id,
                query=state["query"],
                messages=state["lc_messages"],
            )
        result = workflow.run(
            user_id=state["user"].id,
            session_id=state["session"].id,
            query=state["query"],
            messages=state["lc_messages"],
        )
        answer = render_trading_response(
            event=str(result.get("event") or ""),
            payload=result.get("payload") or {},
        )
    except Exception:
        answer = GENERIC_WORKFLOW_ERROR_MESSAGE
    return {
        "response_message": answer,
        "emit_direct_response": True,
    }
