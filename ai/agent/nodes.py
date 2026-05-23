from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Max
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from ai.agent.general_agent import GeneralAgent
from ai.agent.news_agent import NewsAgent
from ai.agent.route import RouteAgent
from ai.agent.trading.schema import render_response as render_trading_response
from ai.models import ChatMessage, ChatSession
from ai.services.trading.store import has_active_trade_draft

if TYPE_CHECKING:
    from ai.agent.trading.graph import TradingWorkflow


GENERIC_WORKFLOW_ERROR_MESSAGE = "当前请求处理失败，请稍后重试。"


_general_agent: GeneralAgent | None = None
_news_agent: NewsAgent | None = None
_route_agent: RouteAgent | None = None
_trading_workflow: TradingWorkflow | None = None


def _get_trading_workflow() -> TradingWorkflow:
    global _trading_workflow
    if _trading_workflow is None:
        from ai.agent.trading.graph import TradingWorkflow

        _trading_workflow = TradingWorkflow()
    return _trading_workflow


def prepare_session(state: dict, *, max_messages: int = 30) -> dict:
    user = state["user"]
    session_id = state.get("session_id")
    query = state["query"]

    if session_id is not None:
        session = ChatSession.objects.get(id=session_id, user=user)
    else:
        session = ChatSession.objects.create(
            user=user,
            title=(query or "").strip()[:20] or "新对话",
        )

    current_max = session.messages.aggregate(max_sequence=Max("sequence"))["max_sequence"]
    next_sequence = int(current_max or 0) + 1
    ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.USER,
        content=query,
        sequence=next_sequence,
    )
    session.save(update_fields=["updated_at"])

    rows = list(session.messages.order_by("-sequence", "-id")[:max_messages])
    rows.reverse()

    lc_messages: list[BaseMessage] = []
    for row in rows:
        if row.role == ChatMessage.Role.USER:
            lc_messages.append(HumanMessage(content=row.content))
        elif row.role == ChatMessage.Role.ASSISTANT:
            lc_messages.append(AIMessage(content=row.content))

    return {
        "session_id": session.id,
        "lc_messages": lc_messages,
        "has_active_trade_draft": has_active_trade_draft(
            user_id=user.id,
            session_id=session.id,
        ),
    }

def decide_intent(state: dict) -> dict:
    try:
        global _route_agent
        if _route_agent is None:
            _route_agent = RouteAgent()
        route = _route_agent.execute(
            query=state["query"],
            has_active_trade_draft=state["has_active_trade_draft"],
        )
        return {"route": route}
    except Exception:
        return {
            "route": "ERROR",
            "response_message": GENERIC_WORKFLOW_ERROR_MESSAGE,
        }


def route_after_intent(state: dict) -> str:
    route = str(state.get("route") or "ERROR").upper()
    if route == "GENERAL":
        return "general_agent"
    if route == "NEWS":
        return "news_agent"
    if route == "TRADING":
        return "trading_agent"
    return "finalize"


def news_agent(state: dict) -> dict:
    try:
        global _news_agent
        if _news_agent is None:
            _news_agent = NewsAgent()
        answer = _news_agent.execute(
            messages=state["lc_messages"],
            context={"user_id": state["user"].id, "session_id": state["session_id"]},
        ).strip()
        return {"response_message": answer}
    except Exception:
        return {
            "response_message": GENERIC_WORKFLOW_ERROR_MESSAGE,
        }


def general_agent(state: dict) -> dict:
    try:
        global _general_agent
        if _general_agent is None:
            _general_agent = GeneralAgent()
        answer = _general_agent.execute(
            messages=state["lc_messages"],
            context={"user_id": state["user"].id, "session_id": state["session_id"]},
        ).strip()
        return {"response_message": answer}
    except Exception:
        return {
            "response_message": GENERIC_WORKFLOW_ERROR_MESSAGE,
        }


def trading_agent(state: dict):
    try:
        workflow = _get_trading_workflow()
        result = workflow.run(
            user_id=state["user"].id,
            session_id=state["session_id"],
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
    }


def finalize_response(state: dict) -> dict:
    answer = str(state.get("response_message") or GENERIC_WORKFLOW_ERROR_MESSAGE).strip()
    session = ChatSession.objects.get(id=int(state["session_id"]))
    current_max = session.messages.aggregate(max_sequence=Max("sequence"))["max_sequence"]
    next_sequence = int(current_max or 0) + 1
    ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.ASSISTANT,
        content=answer,
        sequence=next_sequence,
    )
    session.save(update_fields=["updated_at"])
    return {
        "response_message": answer,
    }
