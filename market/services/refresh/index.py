from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from django.core.cache import cache
from django.utils import timezone as django_timezone

from common.normalize import normalize_code, resolve_short_code
from market.models import Instrument

from ..pricing.cache import MARKET_INDEX_QUOTES_KEY, get_index_quote_payload
from ..pricing.schedule import market_guard_decision
from ..sources.gateway import fetch_index_snapshot_rows
from ..sources.index_definitions import CORE_INDEX_DEFINITIONS, index_definition_by_symbol

logger = logging.getLogger(__name__)


def _group_instruments_by_market() -> dict[str, list[Instrument]]:
    symbols = [item.symbol for item in CORE_INDEX_DEFINITIONS]
    rows = list(
        Instrument.objects
        .filter(symbol__in=symbols, asset_class=Instrument.AssetClass.INDEX, is_active=True)
        .only("symbol", "short_code", "name", "market")
        .order_by("market", "symbol")
    )
    grouped: dict[str, list[Instrument]] = defaultdict(list)
    for row in rows:
        grouped[row.market].append(row)
    return dict(grouped)


def _build_null_row(inst: Instrument) -> dict:
    return {
        "market": inst.market,
        "short_code": resolve_short_code(inst.short_code, inst.symbol),
        "name": inst.name,
        "prev_close": None,
        "day_high": None,
        "day_low": None,
        "pct": None,
    }


def _fetch_rows_yfinance(instruments: list[Instrument]) -> list[dict]:
    items: list[tuple[str, str, str, str]] = []
    for inst in instruments:
        definition = index_definition_by_symbol(inst.symbol)
        if definition is None:
            continue
        items.append((inst.symbol, definition.provider_symbol, definition.short_code, inst.name))
    return fetch_index_snapshot_rows(items)


def _previous_payload() -> dict:
    return get_index_quote_payload()


def _group_previous_rows_by_market(payload: dict) -> dict[str, list[dict]]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        return {}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        market = normalize_code(row.get("market"))
        short_code = normalize_code(row.get("short_code"))
        if not market or not short_code:
            continue
        grouped[market].append(row)
    return dict(grouped)


def _index_by_short_code(rows: object) -> dict[str, dict]:
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = normalize_code(row.get("short_code")) or resolve_short_code(None, row.get("symbol"))
        if code:
            out[code] = row
    return out


def _normalize_row(row: dict, inst: Instrument) -> dict:
    return {
        "market": inst.market,
        "short_code": normalize_code(row.get("short_code")) or resolve_short_code(inst.short_code, row.get("symbol") or inst.symbol),
        "name": row.get("name") or inst.name,
        "prev_close": row.get("prev_close"),
        "day_high": row.get("day_high"),
        "day_low": row.get("day_low"),
        "pct": row.get("pct"),
    }


def _write_payload(items: list[dict], updated_markets: set[str], all_markets: set[str]) -> dict:
    payload = {
        "updated_at": django_timezone.now().astimezone(timezone.utc).isoformat(),
        "data": items,
    }
    cache.set(MARKET_INDEX_QUOTES_KEY, payload, timeout=None)
    return payload


def refresh_indices(*, now_local: datetime | None = None, force_full_fetch: bool = False) -> dict:
    grouped = _group_instruments_by_market()
    previous = _group_previous_rows_by_market(_previous_payload())
    current_time = now_local.astimezone(timezone.utc) if now_local is not None else None

    merged_by_market: dict[str, list[dict]] = {}
    updated_markets: set[str] = set()

    for market, instruments in grouped.items():
        previous_rows = _index_by_short_code(previous.get(market, []))
        latest_rows: dict[str, dict] = {}

        if force_full_fetch or market_guard_decision(market, now_utc=current_time).should_pull:
            try:
                latest_rows = _index_by_short_code(_fetch_rows_yfinance(instruments))
                updated_markets.add(market)
            except Exception:
                logger.exception("index.quote.fetch_failed market=%s", market)

        merged_by_market[market] = [
            _normalize_row(
                latest_rows.get(resolve_short_code(inst.short_code, inst.symbol))
                or previous_rows.get(resolve_short_code(inst.short_code, inst.symbol))
                or _build_null_row(inst),
                inst,
            )
            for inst in instruments
        ]

    row_by_key = {
        (row.get("market"), row.get("short_code")): row
        for rows in merged_by_market.values()
        for row in rows
        if isinstance(row, dict)
    }
    items: list[dict] = []
    for definition in CORE_INDEX_DEFINITIONS:
        market = definition.market
        short_code = definition.short_code or resolve_short_code(None, definition.symbol)
        row = row_by_key.get((market, short_code))
        if row:
            items.append(row)

    payload = _write_payload(items, updated_markets, set(grouped.keys()))
    return {
        "updated_at": payload.get("updated_at"),
        "items": payload.get("data", []),
    }
