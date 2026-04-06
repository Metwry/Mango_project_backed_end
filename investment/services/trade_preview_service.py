from __future__ import annotations

from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import NotFound

from accounts.models import Accounts
from common.utils import format_decimal_str, market_currency, to_decimal
from investment.models import Position
from market.models import Instrument
from market.services.pricing.cache import find_quote_by_code, get_market_data_payload, market_rows


def preview_trade_draft(*, user, draft: dict) -> dict:
    side = str(draft.get("side") or "").upper()
    instrument_id = draft.get("instrument_id")
    if not instrument_id:
        raise ValueError("缺少 instrument_id")

    instrument = Instrument.objects.filter(id=instrument_id).only(
        "id", "symbol", "short_code", "name", "market", "base_currency", "is_active"
    ).first()
    if instrument is None:
        raise NotFound("标的不存在")
    if not instrument.is_active:
        raise ValueError("标的不可交易")

    account_id = draft.get("cash_account_id")
    if not account_id:
        raise ValueError("缺少 cash_account_id")
    account = Accounts.objects.filter(id=account_id, user=user).only(
        "id", "name", "currency", "balance", "status"
    ).first()
    if account is None:
        raise NotFound("账户不存在")
    if account.status != Accounts.Status.ACTIVE:
        raise ValueError("账户未启用")

    position = None
    if side == "SELL":
        position = Position.objects.filter(user=user, instrument=instrument).only("quantity").first()

    price = _resolve_price(instrument=instrument, draft=draft)
    quantity = _resolve_quantity(draft=draft)
    amount = (quantity * price).quantize(Decimal("0.01"))

    instrument_currency = str(instrument.base_currency or market_currency(instrument.market, "USD")).upper()
    if account.currency != instrument_currency:
        raise ValueError(f"账户币种不匹配，当前标的需要 {instrument_currency} 账户")

    can_execute = True
    balance_after = account.balance
    if side == "BUY":
        can_execute = account.balance >= amount
        balance_after = account.balance - amount
    elif side == "SELL":
        can_execute = position is not None and position.quantity >= quantity
        balance_after = account.balance + amount
    else:
        raise ValueError("side 只能是 BUY 或 SELL")

    return {
        "side": side,
        "instrument_id": instrument.id,
        "instrument_symbol": instrument.symbol,
        "instrument_name": instrument.name,
        "quantity": format_decimal_str(quantity),
        "price": format_decimal_str(price),
        "price_source": "USER_INPUT" if draft.get("price") else "QUOTE_SNAPSHOT",
        "price_timestamp": timezone.now().isoformat(),
        "cash_account_id": str(account.id),
        "cash_account_name": account.name,
        "cash_account_currency": account.currency,
        "estimated_amount": format_decimal_str(amount),
        "balance_before": format_decimal_str(account.balance),
        "balance_after": format_decimal_str(balance_after),
        "can_execute": can_execute,
    }


def _resolve_price(*, instrument: Instrument, draft: dict) -> Decimal:
    explicit = to_decimal(draft.get("price"))
    if explicit is not None and explicit > 0:
        return explicit.quantize(Decimal("0.000001"))

    payload = get_market_data_payload()
    data = payload.get("data") if isinstance(payload, dict) else {}
    rows = market_rows(data if isinstance(data, dict) else {}, instrument.market)
    quote = find_quote_by_code(rows, instrument.short_code)
    value = to_decimal((quote or {}).get("price"))
    if value is None or value <= 0:
        raise ValueError("缺少可用价格，请补充价格或稍后重试")
    return value.quantize(Decimal("0.000001"))


def _resolve_quantity(*, draft: dict) -> Decimal:
    quantity = to_decimal(draft.get("quantity"))
    if quantity is not None and quantity > 0:
        return quantity.quantize(Decimal("0.000001"))
    raise ValueError("缺少 quantity")
