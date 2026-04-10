from __future__ import annotations

import json
from decimal import Decimal

from django.contrib.auth import get_user_model

from ai.agent.runtime_context import get_agent_context
from ai.llmmodels.model_factory import LLMModelFactory
from ai.services.trading.store import (
    build_trade_workflow_payload,
    clear_trade_draft,
    load_trade_draft,
    save_trade_draft,
)
from ai.tools.trading.tools import TRADING_TOOLS, describe_trade_entities
from investment.services.trade_preview_service import preview_trade_draft
from investment.services.trade_service import execute_buy, execute_sell

from .schema import (
    DECISION_TOOL_NAME,
    AgentDecision,
    TradeDraft,
    build_agent_messages,
    derive_draft_status,
    submit_trade_decision,
)


MAX_TOOL_ITERATIONS = 6


def load_trade_draft_node(state):
    stored = load_trade_draft(user_id=state["user_id"], session_id=state["session_id"]) or {}
    draft = TradeDraft.from_payload(stored.get("draft"))
    return {
        "draft": draft.to_payload(),
        "draft_status": str(stored.get("draft_status") or "EMPTY"),
        "tool_iteration_count": state["tool_iteration_count"],
    }


def trading_agent_node(state):
    iteration_count = state["tool_iteration_count"]
    current_draft = TradeDraft.from_payload(state.get("draft"))
    draft_status = state.get("draft_status", "EMPTY")
    current_messages = state.get("messages", [])

    get_agent_context()["current_draft"] = current_draft.to_payload()
    get_agent_context()["draft_status"] = draft_status

    model = LLMModelFactory.create_chat_model(task_name="trading_agent").bind_tools(
        [*TRADING_TOOLS, submit_trade_decision]
    )
    response = model.invoke(
        build_agent_messages(
            draft=current_draft,
            draft_status=draft_status,
            user_message=state["user_message"],
            current_messages=current_messages,
        )
    )

    updates = {"messages": [response], "tool_iteration_count": iteration_count}
    tool_calls = list(getattr(response, "tool_calls", None) or [])
    if tool_calls:
        decision_calls = [call for call in tool_calls if call.get("name") == DECISION_TOOL_NAME]
        external_calls = [call for call in tool_calls if call.get("name") != DECISION_TOOL_NAME]

        if decision_calls and external_calls:
            updates["next_action"] = "INVALID"
            updates["event"] = "AGENT_INVALID"
            updates["payload"] = {"message": "agent 同时提交了决策和工具调用。"}
            return updates

        if external_calls:
            next_count = iteration_count + 1
            updates["tool_iteration_count"] = next_count
            if next_count >= MAX_TOOL_ITERATIONS:
                updates["next_action"] = "INVALID"
                updates["event"] = "TOOL_LIMIT_REACHED"
                updates["payload"] = {}
                return updates
            updates["next_action"] = "TOOL"
            updates["event"] = "TOOL_REQUESTED"
            updates["payload"] = {}
            return updates

        return _apply_decision(
            state=state,
            current_draft=current_draft,
            draft_status=draft_status,
            updates=updates,
            decision=AgentDecision.from_tool_args(decision_calls[0].get("args") or {}),
        )

    decision = _parse_decision_from_response(response)
    if decision is not None:
        return _apply_decision(
            state=state,
            current_draft=current_draft,
            draft_status=draft_status,
            updates=updates,
            decision=decision,
        )

    updates["next_action"] = "INVALID"
    updates["event"] = "AGENT_INVALID"
    updates["payload"] = {"message": "agent 没有返回结构化决策。"}
    return updates


def preview_trade_node(state):
    draft = TradeDraft.from_payload(state.get("draft"))
    user = _get_user_from_state(state)
    try:
        preview = preview_trade_draft(user=user, draft=draft.to_payload())
    except Exception as exc:
        save_trade_draft(
            user_id=state["user_id"],
            session_id=state["session_id"],
            draft=build_trade_workflow_payload(
                draft=draft.to_payload(),
                draft_status="DRAFT_EDITING",
            ),
        )
        return {
            "draft": draft.to_payload(),
            "draft_status": "DRAFT_EDITING",
            "event": "PREVIEW_FAILED",
            "payload": {"message": str(exc)},
        }

    next_draft = TradeDraft.from_payload(
        {
            "side": preview["side"],
            "instrument_id": preview["instrument_id"],
            "cash_account_id": preview["cash_account_id"],
            "quantity": preview["quantity"],
            "price": preview["price"],
        }
    )
    save_trade_draft(
        user_id=state["user_id"],
        session_id=state["session_id"],
        draft=build_trade_workflow_payload(
            draft=next_draft.to_payload(),
            draft_status="READY_CONFIRM",
        ),
    )
    return {
        "draft": next_draft.to_payload(),
        "draft_status": "READY_CONFIRM",
        "event": "PREVIEW_READY",
        "payload": {"preview": preview},
    }


def execute_trade_node(state):
    draft = TradeDraft.from_payload(state.get("draft"))
    if state.get("next_action") != "EXECUTE":
        return {
            "event": "EXECUTE_INVALID",
            "payload": {"message": "当前请求不是执行交易动作。"},
        }
    if state.get("draft_status", "EMPTY") != "READY_CONFIRM":
        return {
            "event": "EXECUTE_INVALID",
            "payload": {"message": "当前草案尚未进入可执行状态，请先生成交易预览。"},
        }

    user = _get_user_from_state(state)
    try:
        preview = preview_trade_draft(user=user, draft=draft.to_payload())
    except Exception as exc:
        save_trade_draft(
            user_id=state["user_id"],
            session_id=state["session_id"],
            draft=build_trade_workflow_payload(
                draft=draft.to_payload(),
                draft_status="READY_CONFIRM",
            ),
        )
        return {
            "draft": draft.to_payload(),
            "draft_status": "READY_CONFIRM",
            "event": "EXECUTE_FAILED",
            "payload": {"message": str(exc)},
        }

    if not bool(preview.get("can_execute")):
        save_trade_draft(
            user_id=state["user_id"],
            session_id=state["session_id"],
            draft=build_trade_workflow_payload(
                draft=draft.to_payload(),
                draft_status="READY_CONFIRM",
            ),
        )
        message = "当前预览条件不满足，无法执行：持仓数量不足，请调整后再试。"
        if draft.side == "BUY":
            message = "当前预览条件不满足，无法执行：账户余额不足，请修改数量、价格或账户后再试。"
        return {
            "draft": draft.to_payload(),
            "draft_status": "READY_CONFIRM",
            "event": "EXECUTE_BLOCKED",
            "payload": {"message": message},
        }

    try:
        execution_result = execute_sell(
            user=user,
            instrument_id=int(preview["instrument_id"]),
            quantity=Decimal(str(preview["quantity"])),
            price=Decimal(str(preview["price"])),
            cash_account_id=int(preview["cash_account_id"]),
        ) if draft.side == "SELL" else execute_buy(
            user=user,
            instrument_id=int(preview["instrument_id"]),
            quantity=Decimal(str(preview["quantity"])),
            price=Decimal(str(preview["price"])),
            cash_account_id=int(preview["cash_account_id"]),
        )
        clear_trade_draft(user_id=state["user_id"], session_id=state["session_id"])
        instrument_name, instrument_symbol, account_name = _describe_trade_entities_from_ids(
            instrument_id=int(preview["instrument_id"]),
            cash_account_id=int(preview["cash_account_id"]),
        )
        instrument_label = (
            f"{instrument_name}({instrument_symbol})"
            if instrument_name and instrument_symbol
            else instrument_symbol or instrument_name or "该标的"
        )
        side_text = "买入" if draft.side == "BUY" else "卖出"
        message = (
            f"交易执行成功：已{side_text}{instrument_label} {preview['quantity']}，"
            f"成交价格 {preview['price']}。资金账户为 {account_name or '所选账户'}，"
            f"当前余额 {str(execution_result.get('balance_after') or '')}。"
        )
        return {
            "draft_status": "COMPLETED",
            "event": "EXECUTE_SUCCEEDED",
            "payload": {"message": message},
        }
    except Exception as exc:
        save_trade_draft(
            user_id=state["user_id"],
            session_id=state["session_id"],
            draft=build_trade_workflow_payload(
                draft=draft.to_payload(),
                draft_status="READY_CONFIRM",
            ),
        )
        return {
            "draft": draft.to_payload(),
            "draft_status": "READY_CONFIRM",
            "event": "EXECUTE_FAILED",
            "payload": {"message": str(exc)},
        }


def cancel_trade_node(state):
    clear_trade_draft(user_id=state["user_id"], session_id=state["session_id"])
    return {
        "draft_status": "CANCELLED",
        "event": "CANCELLED",
        "payload": {},
    }


def _get_user_from_state(state):
    return get_user_model().objects.get(id=state["user_id"])


def _describe_trade_entities_from_ids(*, instrument_id: int, cash_account_id: int) -> tuple[str, str, str]:
    try:
        payload = json.loads(
            describe_trade_entities.invoke(
                {"instrument_id": instrument_id, "cash_account_id": cash_account_id}
            )
        )
    except Exception:
        return "", "", ""
    if not isinstance(payload, dict):
        return "", "", ""
    return (
        str(payload.get("instrument_name") or ""),
        str(payload.get("instrument_symbol") or ""),
        str(payload.get("cash_account_name") or ""),
    )


def _apply_decision(*, state, current_draft: TradeDraft, draft_status: str, updates: dict, decision: AgentDecision):
    next_draft = current_draft.merge(decision.draft)
    next_action = decision.next_action
    if current_draft.has_changes(next_draft) and next_draft.is_complete() and next_action == "ASK_CLARIFY":
        next_action = "PREVIEW"
    next_status = derive_draft_status(
        previous_draft=current_draft,
        next_draft=next_draft,
        previous_status=draft_status,
    )
    updates["draft"] = next_draft.to_payload()
    updates["draft_status"] = next_status
    updates["next_action"] = next_action
    updates["event"] = "ASK_CLARIFY" if next_action == "ASK_CLARIFY" else "AGENT_ROUTED"
    updates["payload"] = {"message": decision.message}

    if next_action == "ASK_CLARIFY" and next_draft.to_payload():
        save_trade_draft(
            user_id=state["user_id"],
            session_id=state["session_id"],
            draft=build_trade_workflow_payload(
                draft=next_draft.to_payload(),
                draft_status=next_status,
            ),
        )
    return updates


def _parse_decision_from_response(response) -> AgentDecision | None:
    content = getattr(response, "content", None)
    text = content if isinstance(content, str) else str(content or "")
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        payload = json.loads(stripped)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    draft_payload = payload.get("draft")
    flattened_payload = {
        "next_action": payload.get("next_action"),
        "message": payload.get("message"),
    }
    if isinstance(draft_payload, dict):
        for key in ("side", "instrument_id", "cash_account_id", "quantity", "price"):
            if key in draft_payload:
                flattened_payload[key] = draft_payload.get(key)
    else:
        for key in ("side", "instrument_id", "cash_account_id", "quantity", "price"):
            if key in payload:
                flattened_payload[key] = payload.get(key)

    try:
        return AgentDecision.from_tool_args(flattened_payload)
    except Exception:
        return None
