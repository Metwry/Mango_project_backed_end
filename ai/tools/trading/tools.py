from __future__ import annotations

import json
from typing import Annotated
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from langchain.tools import InjectedState
from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator

from accounts.models import Accounts
from accounts.services.query_service import get_account_summary
from common.utils import to_decimal
from investment.models import Position
from investment.services.query_service import get_recent_trades
from market.models import Instrument
from market.services.pricing.cache import find_quote_by_code, get_market_data_payload, market_rows


def _get_current_user(user_id: int):
    if not user_id:
        raise ValueError("缺少 user_id 上下文")
    return get_user_model().objects.get(id=user_id)


@tool
def get_current_time() -> str:
    """返回当前本地时间、日期和时区。涉及相对时间时优先调用。"""
    now = timezone.now().astimezone(ZoneInfo("Asia/Shanghai"))
    payload = {
        "current_datetime": now.isoformat(),
        "current_date": now.date().isoformat(),
        "timezone": "Asia/Shanghai",
        "weekday": now.strftime("%A"),
    }
    return json.dumps(payload, ensure_ascii=False)


class InstrumentResolveInput(BaseModel):
    query: str = Field(min_length=1)
    candidate_ids: list[int] | None = None


class AccountResolveInput(BaseModel):
    account_name: str | None = None
    currency: str | None = None
    account_id: int | None = None
    candidate_ids: list[int] | None = None

    @model_validator(mode="after")
    def validate_any_field(self):
        if self.account_id is None and not (self.account_name or "").strip() and not (self.currency or "").strip():
            raise ValueError("account_id、account_name、currency 至少提供一个")
        return self


class InstrumentIdInput(BaseModel):
    instrument_id: int


class RecentTradeRecommendationInput(BaseModel):
    instrument_id: int | None = None
    instrument_query: str | None = None
    need_instrument_recommendation: bool = True
    need_account_recommendation: bool = True

    @model_validator(mode="after")
    def validate_any_field(self):
        if self.instrument_id is None and not (self.instrument_query or "").strip():
            raise ValueError("instrument_id、instrument_query 至少提供一个")
        return self


class EntityDescribeInput(BaseModel):
    instrument_id: int | None = None
    cash_account_id: int | None = None


@tool(args_schema=InstrumentResolveInput)
def resolve_trade_instrument(query: str, candidate_ids: list[int] | None = None) -> str:
    """用结构化参数解析交易标的。query 是用户说的标的文本；candidate_ids 存在时只在这些候选里筛选。"""
    raw = str(query or "").strip()
    normalized = raw.upper()
    if not raw:
        return json.dumps({"matched": False, "selected": None, "candidates": []}, ensure_ascii=False)

    queryset = Instrument.objects.all()
    if candidate_ids:
        queryset = queryset.filter(id__in=candidate_ids)

    exact_queryset = (
        queryset.filter(
            Q(symbol__iexact=normalized)
            | Q(short_code__iexact=normalized)
            | Q(name__iexact=raw)
        )
        .only("id", "symbol", "short_code", "name", "market", "base_currency", "is_active")
        .order_by("symbol", "name")[:8]
    )
    queryset = exact_queryset if exact_queryset.exists() else (
        queryset.filter(
            Q(symbol__icontains=normalized)
            | Q(short_code__icontains=normalized)
            | Q(name__icontains=raw)
        )
        .only("id", "symbol", "short_code", "name", "market", "base_currency", "is_active")
        .order_by("symbol", "name")[:8]
    )

    candidates = [
        {
            "instrument_id": item.id,
            "instrument_symbol": item.symbol,
            "instrument_name": item.name,
            "market": item.market,
            "base_currency": item.base_currency,
            "is_active": item.is_active,
        }
        for item in queryset
    ]
    payload = {"matched": len(candidates) == 1, "selected": candidates[0] if len(candidates) == 1 else None, "candidates": candidates}
    return json.dumps(payload, ensure_ascii=False)


@tool
def resolve_trade_account(
    account_name: str | None = None,
    currency: str | None = None,
    account_id: int | None = None,
    candidate_ids: list[int] | None = None,
    user_id: Annotated[int, InjectedState("user_id")] = 0,
) -> str:
    """用结构化参数解析账户。优先 account_id；否则按 account_name + currency + candidate_ids 组合过滤。"""
    if account_id is None and not (account_name or "").strip() and not (currency or "").strip():
        raise ValueError("account_id、account_name、currency 至少提供一个")
    user = _get_current_user(user_id)
    summary = get_account_summary(user=user)
    active_accounts = [item for item in summary.get("accounts", []) if str(item.get("status")) == "active"]

    if candidate_ids:
        allowed_ids = {int(item) for item in candidate_ids}
        active_accounts = [item for item in active_accounts if int(item.get("account_id") or 0) in allowed_ids]

    normalized_name = str(account_name or "").strip().lower()
    normalized_currency = str(currency or "").strip().upper()

    candidates = []
    for item in active_accounts:
        current_account_id = int(item.get("account_id") or 0)
        current_name = str(item.get("name") or "")
        current_currency = str(item.get("currency") or "").upper()

        matched = True
        if account_id is not None:
            matched = current_account_id == int(account_id)
        else:
            if normalized_name:
                matched = normalized_name in current_name.lower()
            if matched and normalized_currency:
                matched = current_currency == normalized_currency

        if matched:
            candidates.append(
                {
                    "cash_account_id": current_account_id,
                    "cash_account_name": current_name,
                    "cash_account_currency": current_currency,
                    "balance": str(item.get("balance") or ""),
                    "status": str(item.get("status") or ""),
                }
            )

    payload = {
        "matched": len(candidates) == 1,
        "selected_account": candidates[0] if len(candidates) == 1 else None,
        "candidates": candidates,
    }
    return json.dumps(payload, ensure_ascii=False)


@tool
def get_recent_trade_recommendation(
    instrument_id: int | None = None,
    instrument_query: str | None = None,
    need_instrument_recommendation: bool = True,
    need_account_recommendation: bool = True,
    user_id: Annotated[int, InjectedState("user_id")] = 0,
) -> str:
    """根据 instrument_id 或 instrument_query 查询最近交易推荐。可分别请求标的推荐和账户推荐。"""
    if instrument_id is None and not (instrument_query or "").strip():
        raise ValueError("instrument_id、instrument_query 至少提供一个")
    user = _get_current_user(user_id)
    symbol_filter: list[str] | None = None
    if instrument_id:
        instrument = Instrument.objects.filter(id=instrument_id).only("short_code", "symbol").first()
        if instrument is not None:
            symbol_filter = [str(instrument.short_code or instrument.symbol)]
    elif instrument_query:
        symbol_filter = [str(instrument_query).strip()]

    payload = get_recent_trades(user=user, symbols=symbol_filter, limit=5)
    items = payload.get("items", []) if isinstance(payload, dict) else []

    instrument_candidates: dict[int, dict] = {}
    account_candidates: dict[int, dict] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        trade_symbol = str(item.get("symbol") or "").strip().upper()
        instrument = (
            Instrument.objects.filter(Q(short_code__iexact=trade_symbol) | Q(symbol__iexact=trade_symbol))
            .only("id", "symbol", "name", "market", "base_currency")
            .first()
        )
        if instrument is not None and instrument.id not in instrument_candidates:
            instrument_candidates[instrument.id] = {
                "instrument_id": instrument.id,
                "instrument_symbol": instrument.symbol,
                "instrument_name": instrument.name,
                "market": instrument.market,
                "base_currency": instrument.base_currency,
            }

        account_id_raw = item.get("cash_account_id")
        if account_id_raw is None:
            continue
        current_account_id = int(account_id_raw)
        if current_account_id not in account_candidates:
            account_candidates[current_account_id] = {
                "cash_account_id": current_account_id,
                "cash_account_name": str(item.get("cash_account_name") or ""),
                "cash_account_currency": str(item.get("cash_account_currency") or ""),
            }

    instrument_values = list(instrument_candidates.values())
    account_values = list(account_candidates.values())
    result = {
        "count": str(len(items)),
        "items": items,
        "instrument_candidates": instrument_values if need_instrument_recommendation else [],
        "account_candidates": account_values if need_account_recommendation else [],
        "recommended_instrument": instrument_values[0] if need_instrument_recommendation and len(instrument_values) == 1 else None,
        "recommended_account": account_values[0] if need_account_recommendation and len(account_values) == 1 else None,
    }
    return json.dumps(result, ensure_ascii=False)


@tool
def load_trade_position_context(
    instrument_id: int,
    user_id: Annotated[int, InjectedState("user_id")] = 0,
) -> str:
    """查询当前标的持仓数量。用于卖出场景把“一半/全部”换算成最终 quantity。"""
    user = _get_current_user(user_id)
    position = (
        Position.objects.select_related("instrument")
        .filter(user=user, instrument_id=instrument_id)
        .only("quantity", "instrument__id", "instrument__symbol", "instrument__name")
        .first()
    )
    if position is None:
        return json.dumps({"matched": False, "quantity": None}, ensure_ascii=False)
    return json.dumps(
        {
            "matched": True,
            "instrument_id": instrument_id,
            "instrument_symbol": position.instrument.symbol,
            "instrument_name": position.instrument.name,
            "quantity": str(position.quantity),
        },
        ensure_ascii=False,
    )


@tool(args_schema=InstrumentIdInput)
def get_market_quote(instrument_id: int) -> str:
    """查询标的当前市场价。返回 price；agent 需要把 price 写回 draft。"""
    instrument = Instrument.objects.filter(id=instrument_id).only("id", "symbol", "short_code", "name", "market").first()
    if instrument is None:
        return json.dumps({"matched": False, "price": None}, ensure_ascii=False)

    payload = get_market_data_payload()
    data = payload.get("data") if isinstance(payload, dict) else {}
    rows = market_rows(data if isinstance(data, dict) else {}, instrument.market)
    quote = find_quote_by_code(rows, instrument.short_code)
    value = to_decimal((quote or {}).get("price"))
    if value is None or value <= 0:
        return json.dumps({"matched": False, "price": None}, ensure_ascii=False)
    return json.dumps(
        {
            "matched": True,
            "instrument_id": instrument.id,
            "instrument_symbol": instrument.symbol,
            "instrument_name": instrument.name,
            "price": str(value),
        },
        ensure_ascii=False,
    )


@tool(args_schema=EntityDescribeInput)
def describe_trade_entities(instrument_id: int | None = None, cash_account_id: int | None = None) -> str:
    """根据 instrument_id / cash_account_id 查询展示用名称。只用于组织返回给用户的 message。"""
    payload: dict[str, object] = {}
    if instrument_id is not None:
        instrument = Instrument.objects.filter(id=instrument_id).only("symbol", "name").first()
        if instrument is not None:
            payload["instrument_symbol"] = instrument.symbol
            payload["instrument_name"] = instrument.name
    if cash_account_id is not None:
        account = Accounts.objects.filter(id=cash_account_id).only("name", "currency").first()
        if account is not None:
            payload["cash_account_name"] = account.name
            payload["cash_account_currency"] = account.currency
    return json.dumps(payload, ensure_ascii=False)


TRADING_TOOLS = [
    get_current_time,
    resolve_trade_instrument,
    resolve_trade_account,
    get_recent_trade_recommendation,
    load_trade_position_context,
    get_market_quote,
    describe_trade_entities,
]
