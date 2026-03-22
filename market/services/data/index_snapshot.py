from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from django.core.cache import cache
from django.utils import timezone as django_timezone

from market.models import Instrument

from ..quote_cache import MARKET_INDEX_QUOTES_KEY, MARKET_INDEX_QUOTES_MARKET_KEY_PREFIX
from ..market_schedule import market_guard_decision
from .core_index_definitions import CORE_INDEX_DEFINITIONS, index_definition_by_symbol
from .market_data_gateway import fetch_index_snapshot_rows

logger = logging.getLogger(__name__)


# 读取核心指数标的并按市场分组。
def _group_instruments_by_market() -> dict[str, list[Instrument]]:
    symbols = [item.symbol for item in CORE_INDEX_DEFINITIONS]
    rows = list(
        Instrument.objects
        .filter(symbol__in=symbols, asset_class=Instrument.AssetClass.INDEX, is_active=True)
        .only("id", "symbol", "name", "market")
        .order_by("market", "symbol")
    )
    grouped: dict[str, list[Instrument]] = defaultdict(list)
    for row in rows:
        grouped[row.market].append(row)
    return dict(grouped)


# 构造指数行情缺失时的空白行。
def _build_null_row(inst: Instrument) -> dict:
    return {
        "symbol": inst.symbol,
        "instrument_id": inst.id,
        "name": inst.name,
        "prev_close": None,
        "day_high": None,
        "day_low": None,
        "pct": None,
    }


# 通过统一指数行情入口拉取指数快照行。
def _fetch_rows_yfinance(instruments: list[Instrument]) -> list[dict]:
    items: list[tuple[str, str, int, str]] = []
    for inst in instruments:
        definition = index_definition_by_symbol(inst.symbol)
        if definition is None:
            continue
        items.append((inst.symbol, definition.provider_symbol, inst.id, inst.name))
    return fetch_index_snapshot_rows(items)


# 读取上一版指数行情缓存。
def _previous_payload() -> dict:
    payload = cache.get(MARKET_INDEX_QUOTES_KEY) or {}
    return payload if isinstance(payload, dict) else {}


# 按 symbol 为指数行情列表建立索引。
def _index_by_symbol(rows: object) -> dict[str, dict]:
    if not isinstance(rows, list):
        return {}
    return {
        symbol: row
        for row in rows
        if isinstance(row, dict) and (symbol := str(row.get("symbol") or "").strip().upper())
    }


# 将指数行情结果写回缓存。
def _write_payload(data: dict[str, list[dict]], updated_markets: set[str]) -> dict:
    now_iso = django_timezone.now().astimezone(timezone.utc).isoformat()
    stale_markets = sorted(set(data.keys()) - updated_markets)
    payload = {
        "updated_at": now_iso,
        "updated_markets": sorted(updated_markets),
        "stale_markets": stale_markets,
        "data": data,
    }
    cache.set(MARKET_INDEX_QUOTES_KEY, payload, timeout=None)
    for market, rows in data.items():
        cache.set(
            f"{MARKET_INDEX_QUOTES_MARKET_KEY_PREFIX}{market}",
            {
                "updated_at": now_iso,
                "market": market,
                "stale": market in stale_markets,
                "data": rows,
            },
            timeout=None,
        )
    return payload


# 拉取并组装核心指数行情快照。
def pull_indices(*, now_local: datetime | None = None) -> dict:
    grouped = _group_instruments_by_market()
    previous = _previous_payload()
    previous_data = previous.get("data") if isinstance(previous.get("data"), dict) else {}
    current_time = now_local.astimezone(timezone.utc) if now_local is not None else None

    merged: dict[str, list[dict]] = {}
    updated_markets: set[str] = set()

    for market, instruments in grouped.items():
        previous_rows = _index_by_symbol(previous_data.get(market, []))
        latest_rows: dict[str, dict] = {}

        if market_guard_decision(market, now_utc=current_time).should_pull:
            try:
                latest_rows = _index_by_symbol(_fetch_rows_yfinance(instruments))
                updated_markets.add(market)
            except Exception:
                logger.exception("index.quote.fetch_failed market=%s", market)

        merged[market] = [
            latest_rows.get(inst.symbol) or previous_rows.get(inst.symbol) or _build_null_row(inst)
            for inst in instruments
        ]

    payload = _write_payload(merged, updated_markets)
    row_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row
        for rows in merged.values()
        for row in rows
        if isinstance(row, dict)
    }
    items: list[dict] = []
    for definition in CORE_INDEX_DEFINITIONS:
        row = row_by_symbol.get(definition.symbol)
        if not row:
            continue
        items.append(
            {
                "instrument_id": row.get("instrument_id"),
                "name": row.get("name"),
                "prev_close": row.get("prev_close"),
                "day_high": row.get("day_high"),
                "day_low": row.get("day_low"),
                "pct": row.get("pct"),
            }
        )

    return {
        "updated_at": payload.get("updated_at"),
        "items": items,
    }
