from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai.agent.runtime_context import get_agent_context
from ai.config import get_prompt_path
from ai.llmmodels.model_factory import LLMModelFactory
from ai.services.trade_workflow_store import (
    build_trade_workflow_payload,
    clear_trade_draft,
    load_trade_draft,
    save_trade_draft,
)
from common.utils import to_decimal
from investment.services.trade_preview_service import preview_trade_draft
from investment.services.trade_service import execute_buy, execute_sell


TRADING_SYSTEM_PROMPT = get_prompt_path("trading.txt").read_text(encoding="utf-8").strip()
logger = logging.getLogger(__name__)

CORE_DRAFT_FIELDS = {"side", "instrument_id", "cash_account_id", "quantity", "price"}
ALLOWED_ACTIONS = {"ASK_CLARIFY", "PREVIEW", "EXECUTE", "CANCEL", "INVALID"}


def load_trade_draft_node(state):
    stored = load_trade_draft(user_id=state["user_id"], session_id=state["session_id"]) or {}
    stored_draft = stored.get("draft") if isinstance(stored.get("draft"), dict) else {}
    stored_meta = stored.get("meta") if isinstance(stored.get("meta"), dict) else {}
    draft = {key: value for key, value in stored_draft.items() if key in CORE_DRAFT_FIELDS and value not in (None, "", [], {})}
    trade_meta = {
        "price_source": stored_meta.get("price_source"),
        "price_timestamp": stored_meta.get("price_timestamp"),
        "preview_payload": stored_meta.get("preview_payload"),
        "awaiting_slot": stored_meta.get("awaiting_slot"),
        "pending_account_candidate_ids": stored_meta.get("pending_account_candidate_ids"),
        "pending_instrument_candidate_ids": stored_meta.get("pending_instrument_candidate_ids"),
        "preferred_account_currency": stored_meta.get("preferred_account_currency"),
    }
    draft_status = str(stored_meta.get("draft_status") or "EMPTY")
    return {
        "draft": draft,
        "draft_status": draft_status,
        "trade_meta": trade_meta,
        "tool_iteration_count": int(state.get("tool_iteration_count") or 0),
        "max_tool_iterations": int(state.get("max_tool_iterations") or 6),
        "tool_call_log": list(state.get("tool_call_log") or []),
        "logged_tool_call_ids": list(state.get("logged_tool_call_ids") or []),
    }


def trading_agent_node(state):
    iteration_count = int(state.get("tool_iteration_count") or 0)
    tool_call_log = list(state.get("tool_call_log") or [])
    logged_tool_call_ids = list(state.get("logged_tool_call_ids") or [])
    current_draft = _normalize_draft(state.get("draft") if isinstance(state.get("draft"), dict) else {})

    get_agent_context()["current_draft"] = dict(current_draft)
    get_agent_context()["draft_status"] = str(state.get("draft_status") or "EMPTY")
    get_agent_context()["current_trade_meta"] = dict(state.get("trade_meta") if isinstance(state.get("trade_meta"), dict) else {})

    context_prompt = HumanMessage(
        content=(
            f"{TRADING_SYSTEM_PROMPT}\n\n"
            "当前交易上下文如下，请基于它继续处理本轮请求。\n"
            f"当前草案(JSON): {json.dumps(current_draft, ensure_ascii=False)}\n"
            f"当前草案状态: {str(state.get('draft_status') or 'EMPTY')}\n"
            f"当前草案元数据(JSON): {json.dumps(state.get('trade_meta') if isinstance(state.get('trade_meta'), dict) else {}, ensure_ascii=False)}\n"
            f"本轮用户消息: {str(state.get('user_message') or '')}"
        )
    )

    messages = [context_prompt]
    current_messages = state.get("messages") or []
    if current_messages:
        messages.extend(current_messages)

    new_tool_results, new_logged_ids = _collect_new_tool_results(current_messages, logged_tool_call_ids)
    if new_tool_results:
        tool_call_log.extend(new_tool_results)
        logged_tool_call_ids = new_logged_ids

    model = LLMModelFactory.create_chat_model(task_name="news_answer").bind_tools(
        __import__("ai.agent.trading_agent.tools", fromlist=["TRADING_TOOLS"]).TRADING_TOOLS
    )
    result = model.invoke(messages)
    has_tool_calls = bool(getattr(result, "tool_calls", None))
    updates = {
        "messages": [result],
        "has_tool_calls": has_tool_calls,
        "tool_iteration_count": iteration_count + 1,
        "tool_call_log": tool_call_log,
        "logged_tool_call_ids": logged_tool_call_ids,
    }
    if has_tool_calls:
        tool_entries = _summarize_tool_calls(result, iteration_count + 1)
        if tool_entries:
            updates["tool_call_log"] = tool_call_log + tool_entries
            logger.warning(
                "trading_agent.tool_calls session=%s user=%s entries=%s",
                state.get("session_id"),
                state.get("user_id"),
                tool_entries,
            )
        return updates

    payload = _parse_agent_json_result(result.content, current_draft)
    merged_draft = _merge_draft(current_draft, payload.get("draft") if isinstance(payload.get("draft"), dict) else {})
    changed_fields = {
        key for key in CORE_DRAFT_FIELDS
        if key in merged_draft and current_draft.get(key) != merged_draft.get(key)
    }
    if changed_fields and _is_complete_draft(merged_draft) and str(payload.get("next_action") or "").upper() == "ASK_CLARIFY":
        payload["next_action"] = "PREVIEW"
    merged_draft, next_status, next_meta = _apply_draft_change_effects(
        previous_draft=current_draft,
        next_draft=merged_draft,
        previous_status=str(state.get("draft_status") or "EMPTY"),
        previous_meta=state.get("trade_meta") if isinstance(state.get("trade_meta"), dict) else {},
    )
    next_meta = _derive_trade_meta_from_tool_log(
        tool_call_log=tool_call_log,
        current_meta=next_meta,
        draft=merged_draft,
        next_action=str(payload.get("next_action") or "").upper(),
    )
    payload["draft"] = merged_draft
    updates["agent_result"] = payload
    updates["draft"] = merged_draft
    updates["draft_status"] = next_status
    updates["trade_meta"] = next_meta
    updates["response_text"] = str(payload.get("message") or "当前交易请求处理完成。")

    action = str(payload.get("next_action") or "").upper()
    if action == "ASK_CLARIFY" and merged_draft:
        save_trade_draft(
            user_id=state["user_id"],
            session_id=state["session_id"],
            draft=build_trade_workflow_payload(
                draft=merged_draft,
                meta=_serialize_trade_meta(next_status, next_meta),
            ),
        )
    return updates


def preview_trade_node(state):
    payload = state.get("agent_result") or {}
    draft = _normalize_draft(payload.get("draft") if isinstance(payload.get("draft"), dict) else state.get("draft") or {})
    user = _get_user_from_state(state)
    try:
        preview = preview_trade_draft(user=user, draft=draft)
    except Exception as exc:
        save_trade_draft(
            user_id=state["user_id"],
            session_id=state["session_id"],
            draft=build_trade_workflow_payload(
                draft=draft,
                meta=_serialize_trade_meta("DRAFT_EDITING", {}),
            ),
        )
        return {
            "preview_result": "FAILED",
            "draft": draft,
            "draft_status": "DRAFT_EDITING",
            "trade_meta": {},
            "response_text": str(exc),
        }

    updated_draft = {
        "side": preview["side"],
        "instrument_id": int(preview["instrument_id"]),
        "cash_account_id": int(preview["cash_account_id"]),
        "quantity": str(preview["quantity"]),
        "price": str(preview["price"]),
    }
    trade_meta = {
        "price_source": preview["price_source"],
        "price_timestamp": preview["price_timestamp"],
        "preview_payload": preview,
    }
    save_trade_draft(
        user_id=state["user_id"],
        session_id=state["session_id"],
        draft=build_trade_workflow_payload(
            draft=updated_draft,
            meta=_serialize_trade_meta("READY_CONFIRM", trade_meta),
        ),
    )
    if preview.get("can_execute"):
        status_text = "当前条件满足，可以继续执行。回复“确认”执行，回复“取消”放弃。"
    else:
        side = str(preview.get("side") or "").upper()
        if side == "BUY":
            status_text = "当前条件暂不满足：账户余额不足。"
        elif side == "SELL":
            status_text = "当前条件暂不满足：持仓数量不足。"
        else:
            status_text = "当前条件暂不满足。"
    quantity_unit = _quantity_unit_from_symbol(str(preview.get("instrument_symbol") or ""))
    text = (
        f"交易预览：{preview['side']} {preview['instrument_name']}({preview['instrument_symbol']}) "
        f"{preview['quantity']}{quantity_unit}，使用 {preview['cash_account_name']}，价格 {preview['price']}，"
        f"预计金额 {preview['estimated_amount']}。{status_text}"
    )
    return {
        "draft": updated_draft,
        "draft_status": "READY_CONFIRM",
        "trade_meta": trade_meta,
        "preview_result": "SUCCESS",
        "response_text": text,
    }


def execute_trade_node(state):
    draft = _normalize_draft(state.get("draft") if isinstance(state.get("draft"), dict) else {})
    draft_status = str(state.get("draft_status") or "EMPTY")
    agent_result = state.get("agent_result") or {}
    trade_meta = state.get("trade_meta") if isinstance(state.get("trade_meta"), dict) else {}
    next_action = str(agent_result.get("next_action") or "").upper()
    if next_action != "EXECUTE":
        return {"execute_result": "INVALID", "response_text": "当前请求不是执行交易动作。"}
    if draft_status != "READY_CONFIRM":
        return {"execute_result": "INVALID", "response_text": "当前草案尚未进入可执行状态，请先生成交易预览。"}
    preview_payload = trade_meta.get("preview_payload") if isinstance(trade_meta.get("preview_payload"), dict) else {}
    if preview_payload and not bool(preview_payload.get("can_execute")):
        save_trade_draft(
            user_id=state["user_id"],
            session_id=state["session_id"],
            draft=build_trade_workflow_payload(
                draft=draft,
                meta=_serialize_trade_meta("READY_CONFIRM", trade_meta),
            ),
        )
        if str(draft.get("side") or "").upper() == "BUY":
            return {
                "execute_result": "INVALID",
                "draft": draft,
                "draft_status": "READY_CONFIRM",
                "response_text": "当前预览条件不满足，无法执行：账户余额不足，请修改数量、价格或账户后再试。",
            }
        return {
            "execute_result": "INVALID",
            "draft": draft,
            "draft_status": "READY_CONFIRM",
            "response_text": "当前预览条件不满足，无法执行：持仓数量不足，请调整后再试。",
        }
    if _is_price_expired(trade_meta):
        save_trade_draft(
            user_id=state["user_id"],
            session_id=state["session_id"],
            draft=build_trade_workflow_payload(
                draft=draft,
                meta=_serialize_trade_meta("EXPIRED", trade_meta),
            ),
        )
        return {
            "execute_result": "INVALID",
            "draft": draft,
            "draft_status": "EXPIRED",
            "response_text": "当前预览价格已过期，请重新生成交易预览后再执行。",
        }

    user = _get_user_from_state(state)
    try:
        payload = {
            "user": user,
            "instrument_id": int(draft["instrument_id"]),
            "quantity": Decimal(str(draft["quantity"])),
            "price": Decimal(str(draft["price"])),
            "cash_account_id": int(draft["cash_account_id"]),
        }
        result = execute_sell(**payload) if str(draft.get("side") or "").upper() == "SELL" else execute_buy(**payload)
        clear_trade_draft(user_id=state["user_id"], session_id=state["session_id"])
        instrument_name, instrument_symbol, account_name = _describe_trade_entities_from_ids(
            instrument_id=int(draft["instrument_id"]),
            cash_account_id=int(draft["cash_account_id"]),
        )
        side_text = "买入" if str(draft.get("side") or "").upper() == "BUY" else "卖出"
        quantity_text = str(draft.get("quantity") or "")
        price_text = str(draft.get("price") or "")
        balance_after = str(result.get("balance_after") or "") if isinstance(result, dict) else ""
        instrument_label = (
            f"{instrument_name}({instrument_symbol})"
            if instrument_name and instrument_symbol
            else instrument_symbol or instrument_name or "该标的"
        )
        account_label = account_name or "所选账户"
        quantity_unit = _quantity_unit_from_symbol(instrument_symbol)
        message = (
            f"交易执行成功：已{side_text}{instrument_label} {quantity_text}{quantity_unit}，成交价格 {price_text}。"
            f"资金账户为 {account_label}，当前余额 {balance_after}。"
        )
        return {
            "execute_result": "SUCCESS",
            "execution_result": result,
            "draft_status": "COMPLETED",
            "response_text": message,
        }
    except Exception as exc:
        save_trade_draft(
            user_id=state["user_id"],
            session_id=state["session_id"],
            draft=build_trade_workflow_payload(
                draft=draft,
                meta=_serialize_trade_meta("READY_CONFIRM", state.get("trade_meta") or {}),
            ),
        )
        return {
            "execute_result": "FAILED",
            "execution_result": {"message": str(exc)},
            "draft": draft,
            "draft_status": "READY_CONFIRM",
            "response_text": str(exc),
        }


def cancel_trade_node(state):
    clear_trade_draft(user_id=state["user_id"], session_id=state["session_id"])
    return {
        "draft_status": "CANCELLED",
        "response_text": "本次交易已取消。",
    }


def _get_user_from_state(state):
    user_id = state.get("user_id") or get_agent_context().get("user_id")
    return get_user_model().objects.get(id=user_id)


def _normalize_draft(draft: dict | None) -> dict:
    normalized: dict[str, object] = {}
    if not isinstance(draft, dict):
        return normalized
    side = str(draft.get("side") or "").upper()
    if side in {"BUY", "SELL"}:
        normalized["side"] = side
    for key in ("instrument_id", "cash_account_id"):
        value = draft.get(key)
        if value not in (None, "", [], {}):
            normalized[key] = int(value)
    for key in ("quantity", "price"):
        value = draft.get(key)
        if value not in (None, "", [], {}):
            normalized[key] = str(value)
    return normalized


def _parse_agent_json_result(content: object, current_draft: dict) -> dict:
    invalid = {
        "next_action": "INVALID",
        "draft": dict(current_draft or {}),
        "message": "agent 输出不是合法 JSON",
    }
    raw = str(content).strip()
    try:
        payload = json.loads(raw)
    except Exception:
        payload = _extract_json_object(raw)
        if payload is None:
            return invalid
    if not isinstance(payload, dict):
        return invalid
    next_action = str(payload.get("next_action") or "").upper()
    if next_action not in ALLOWED_ACTIONS:
        return invalid
    draft = _normalize_draft(payload.get("draft") if isinstance(payload.get("draft"), dict) else {})
    message = str(payload.get("message") or "").strip() or "当前交易请求处理完成。"
    return {
        "next_action": next_action,
        "draft": draft,
        "message": message,
    }


def _extract_json_object(raw: str) -> dict | None:
    start = raw.find("{")
    while start != -1:
        depth = 0
        for idx in range(start, len(raw)):
            ch = raw[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start:idx + 1]
                    try:
                        payload = json.loads(candidate)
                    except Exception:
                        break
                    if isinstance(payload, dict):
                        return payload
                    break
        start = raw.find("{", start + 1)
    return None


def _merge_draft(base: dict | None, override: dict | None) -> dict:
    merged = _normalize_draft(base)
    for key, value in _normalize_draft(override).items():
        merged[key] = value
    return merged


def _is_complete_draft(draft: dict | None) -> bool:
    normalized = _normalize_draft(draft)
    return all(normalized.get(key) not in (None, "", [], {}) for key in ("side", "instrument_id", "cash_account_id", "quantity", "price"))


def _apply_draft_change_effects(*, previous_draft: dict, next_draft: dict, previous_status: str, previous_meta: dict) -> tuple[dict, str, dict]:
    merged = dict(next_draft)
    changed = {
        key for key in CORE_DRAFT_FIELDS
        if key in merged and previous_draft.get(key) != merged.get(key)
    }
    meta = dict(previous_meta or {})
    status = previous_status or "EMPTY"
    if changed:
        meta = {}
        status = "DRAFT_EDITING"
    if not merged:
        status = "EMPTY"
    return merged, status, meta


def _serialize_trade_meta(draft_status: str, trade_meta: dict | None) -> dict:
    payload = {"draft_status": draft_status}
    meta = trade_meta or {}
    if meta.get("price_source"):
        payload["price_source"] = meta["price_source"]
    if meta.get("price_timestamp"):
        payload["price_timestamp"] = meta["price_timestamp"]
    if meta.get("preview_payload"):
        payload["preview_payload"] = meta["preview_payload"]
    if meta.get("awaiting_slot"):
        payload["awaiting_slot"] = meta["awaiting_slot"]
    if meta.get("pending_account_candidate_ids"):
        payload["pending_account_candidate_ids"] = meta["pending_account_candidate_ids"]
    if meta.get("pending_instrument_candidate_ids"):
        payload["pending_instrument_candidate_ids"] = meta["pending_instrument_candidate_ids"]
    if meta.get("preferred_account_currency"):
        payload["preferred_account_currency"] = meta["preferred_account_currency"]
    return payload


def _is_price_expired(trade_meta: dict) -> bool:
    if str(trade_meta.get("price_source") or "").upper() == "USER_INPUT":
        return False
    timestamp_value = trade_meta.get("price_timestamp")
    if not timestamp_value:
        return True
    try:
        ts = timezone.datetime.fromisoformat(str(timestamp_value))
    except Exception:
        return True
    if ts.tzinfo is None:
        ts = timezone.make_aware(ts, timezone.get_current_timezone())
    return timezone.now() - ts > timezone.timedelta(minutes=5)


def _describe_trade_entities_from_ids(*, instrument_id: int, cash_account_id: int) -> tuple[str, str, str]:
    from ai.agent.trading_agent.tools import describe_trade_entities

    try:
        payload = json.loads(describe_trade_entities.invoke({"instrument_id": instrument_id, "cash_account_id": cash_account_id}))
    except Exception:
        return "", "", ""
    if not isinstance(payload, dict):
        return "", "", ""
    return (
        str(payload.get("instrument_name") or ""),
        str(payload.get("instrument_symbol") or ""),
        str(payload.get("cash_account_name") or ""),
    )


def _quantity_unit_from_symbol(symbol: str) -> str:
    upper_symbol = str(symbol or "").upper()
    if upper_symbol.endswith(".CRYPTO"):
        return "个"
    return "股"




def _summarize_tool_calls(message: AIMessage, iteration: int) -> list[dict]:
    entries: list[dict] = []
    for call in getattr(message, "tool_calls", None) or []:
        args = call.get("args") if isinstance(call, dict) else {}
        entries.append(
            {
                "kind": "tool_call",
                "iteration": iteration,
                "tool_call_id": str(call.get("id") or ""),
                "tool_name": str(call.get("name") or ""),
                "args": args if isinstance(args, dict) else args,
            }
        )
    return entries


def _collect_new_tool_results(messages: list, logged_ids: list[str]) -> tuple[list[dict], list[str]]:
    known_ids = set(logged_ids)
    entries: list[dict] = []
    updated_ids = list(logged_ids)
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        tool_call_id = str(getattr(message, "tool_call_id", "") or "")
        if not tool_call_id or tool_call_id in known_ids:
            continue
        known_ids.add(tool_call_id)
        updated_ids.append(tool_call_id)
        content = message.content
        if isinstance(content, list):
            content = " ".join(str(item) for item in content)
        text = str(content or "")
        entries.append(
            {
                "kind": "tool_result",
                "tool_call_id": tool_call_id,
                "content_preview": text[:500],
            }
        )
    if entries:
        logger.warning("trading_agent.tool_results entries=%s", entries)
    return entries, updated_ids


def _derive_trade_meta_from_tool_log(*, tool_call_log: list[dict], current_meta: dict, draft: dict, next_action: str) -> dict:
    meta = dict(current_meta or {})
    if next_action == "PREVIEW":
        return meta

    calls_by_id: dict[str, str] = {}
    for entry in tool_call_log:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == "tool_call":
            calls_by_id[str(entry.get("tool_call_id") or "")] = str(entry.get("tool_name") or "")

    latest_recent = None
    latest_instrument = None
    latest_account = None
    for entry in reversed(tool_call_log):
        if not isinstance(entry, dict) or entry.get("kind") != "tool_result":
            continue
        tool_name = calls_by_id.get(str(entry.get("tool_call_id") or ""), "")
        payload = None
        try:
            payload = json.loads(str(entry.get("content_preview") or ""))
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            continue
        if tool_name == "get_recent_trade_recommendation" and latest_recent is None:
            latest_recent = payload
        elif tool_name == "resolve_trade_instrument" and latest_instrument is None:
            latest_instrument = payload
        elif tool_name == "resolve_trade_account" and latest_account is None:
            latest_account = payload
        if latest_recent is not None and latest_instrument is not None and latest_account is not None:
            break

    if latest_instrument and not draft.get("instrument_id"):
        candidates = latest_instrument.get("candidates") if isinstance(latest_instrument.get("candidates"), list) else []
        candidate_ids = [int(item.get("instrument_id")) for item in candidates if isinstance(item, dict) and item.get("instrument_id") is not None]
        if len(candidate_ids) > 1:
            meta["awaiting_slot"] = "instrument_id"
            meta["pending_instrument_candidate_ids"] = candidate_ids
            first_currency = str(candidates[0].get("base_currency") or "").upper() if isinstance(candidates[0], dict) else ""
            if first_currency:
                meta["preferred_account_currency"] = first_currency

    if latest_recent:
        recommended_account = latest_recent.get("recommended_account") if isinstance(latest_recent.get("recommended_account"), dict) else None
        if recommended_account and not draft.get("cash_account_id"):
            currency = str(recommended_account.get("cash_account_currency") or "").upper()
            if currency:
                meta["preferred_account_currency"] = currency
        account_candidates = latest_recent.get("account_candidates") if isinstance(latest_recent.get("account_candidates"), list) else []
        account_candidate_ids = [int(item.get("cash_account_id")) for item in account_candidates if isinstance(item, dict) and item.get("cash_account_id") is not None]
        if len(account_candidate_ids) > 1 and not draft.get("cash_account_id"):
            meta["awaiting_slot"] = "cash_account_id"
            meta["pending_account_candidate_ids"] = account_candidate_ids

    if latest_account and not draft.get("cash_account_id"):
        candidates = latest_account.get("candidates") if isinstance(latest_account.get("candidates"), list) else []
        candidate_ids = [int(item.get("cash_account_id")) for item in candidates if isinstance(item, dict) and item.get("cash_account_id") is not None]
        if len(candidate_ids) > 1:
            meta["awaiting_slot"] = "cash_account_id"
            meta["pending_account_candidate_ids"] = candidate_ids

    if draft.get("instrument_id"):
        meta.pop("pending_instrument_candidate_ids", None)
        if meta.get("awaiting_slot") == "instrument_id":
            meta.pop("awaiting_slot", None)
    if draft.get("cash_account_id"):
        meta.pop("pending_account_candidate_ids", None)
        if meta.get("awaiting_slot") == "cash_account_id":
            meta.pop("awaiting_slot", None)
    return meta
