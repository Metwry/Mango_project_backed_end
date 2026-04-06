from django.db.models import Q

from investment.models import Position
from common.utils import market_currency


def _normalize_symbols(symbols: list[str] | None) -> list[str] | None:
    if symbols is None:
        return None
    normalized = []
    seen = set()
    for symbol in symbols:
        value = str(symbol or "").strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def get_position_data(*, user, symbols: list[str] | None = None) -> dict:
    queryset = (
        Position.objects
        .filter(user=user, quantity__gt=0)
        .select_related("instrument")
        .only(
            "instrument_id",
            "quantity",
            "avg_cost",
            "cost_total",
            "realized_pnl_total",
            "instrument__symbol",
            "instrument__short_code",
            "instrument__name",
            "instrument__market",
            "instrument__base_currency",
        )
        .order_by("instrument__symbol")
    )
    normalized_symbols = _normalize_symbols(symbols)
    if normalized_symbols is not None:
        queryset = queryset.filter(
            Q(instrument__short_code__in=normalized_symbols)
            | Q(instrument__symbol__in=normalized_symbols)
        )

    positions = []
    for position in queryset:
        instrument = position.instrument
        short_code = str(getattr(instrument, "short_code", "") or "").upper()
        raw_symbol = str(getattr(instrument, "symbol", "") or "").upper()
        currency = str(getattr(instrument, "base_currency", "") or "").upper()
        if not currency:
            currency = market_currency(instrument.market, "CNY")

        positions.append(
            {
                "symbol": short_code or raw_symbol,
                "name": instrument.name,
                "market": instrument.market,
                "currency": currency,
                "quantity": str(position.quantity),
                "avg_cost": str(position.avg_cost),
                "cost_total": str(position.cost_total),
                "realized_pnl_total": str(position.realized_pnl_total),
            }
        )

    return {"positions": positions}


# 按筛选条件查询当前用户的投资交易历史。
def query_investment_history(*, user, params: dict):
    queryset = (
        user.investment_records
        .select_related("instrument", "cash_account", "cash_transaction")
        .order_by("-trade_at", "-id")
    )
    if params.get("account_id") is not None:
        queryset = queryset.filter(cash_account_id=params["account_id"])
    if params.get("instrument_id") is not None:
        queryset = queryset.filter(instrument_id=params["instrument_id"])
    if params.get("side") is not None:
        queryset = queryset.filter(side=params["side"])
    if params.get("start") is not None:
        queryset = queryset.filter(trade_at__gte=params["start"])
    if params.get("end") is not None:
        queryset = queryset.filter(trade_at__lte=params["end"])

    total = queryset.count()
    offset = params["offset"]
    limit = params["limit"]
    rows = list(queryset[offset: offset + limit])
    return {
        "count": total,
        "offset": offset,
        "limit": limit,
        "rows": rows,
    }


def get_recent_trades(*, user, symbols: list[str] | None = None, limit: int | None = None) -> dict:
    normalized_symbols = _normalize_symbols(symbols)
    raw_symbols = [str(symbol or "").strip() for symbol in (symbols or []) if str(symbol or "").strip()]
    effective_limit = int(limit or 10)

    queryset = (
        user.investment_records
        .select_related("instrument", "cash_account")
        .order_by("-trade_at", "-id")
    )
    if normalized_symbols is not None:
        symbol_filter = Q(instrument__short_code__in=normalized_symbols) | Q(instrument__symbol__in=normalized_symbols)
        for raw in raw_symbols:
            symbol_filter |= Q(instrument__name__icontains=raw)
        queryset = queryset.filter(symbol_filter)

    rows = list(queryset[:effective_limit])
    return {
        "count": str(len(rows)),
        "items": [
            {
                "id": str(row.id),
                "side": row.side,
                "symbol": str(getattr(row.instrument, "short_code", "") or getattr(row.instrument, "symbol", "")),
                "name": row.instrument.name,
                "cash_account_id": str(row.cash_account_id) if row.cash_account_id is not None else None,
                "cash_account_name": str(getattr(row.cash_account, "name", "") or "") if getattr(row, "cash_account", None) else None,
                "cash_account_currency": str(getattr(row.cash_account, "currency", "") or "") if getattr(row, "cash_account", None) else None,
                "quantity": str(row.quantity),
                "price": str(row.price),
                "trade_at": row.trade_at.isoformat(),
            }
            for row in rows
        ],
    }
