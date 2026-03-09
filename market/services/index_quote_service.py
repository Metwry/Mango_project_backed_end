from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone as django_timezone
from rest_framework.exceptions import ValidationError

from market.models import Instrument
from shared.utils import to_decimal, trim_decimal_str

from .cache_keys import MARKET_INDEX_QUOTES_KEY, MARKET_INDEX_QUOTES_MARKET_KEY_PREFIX
from .calendar_guard_service import market_guard_decision
from .index_catalog import CORE_INDEX_DEFINITIONS, IndexDefinition, index_definition_by_symbol

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except Exception:
    yf = None


def _index_provider() -> str:
    return str(getattr(settings, "MARKET_INDEX_PROVIDER", "yfinance") or "yfinance").strip().lower()


def _group_instruments_by_market() -> dict[str, list[Instrument]]:
    symbols = [item.symbol for item in CORE_INDEX_DEFINITIONS]
    rows = list(
        Instrument.objects
        .filter(symbol__in=symbols, asset_class=Instrument.AssetClass.INDEX, is_active=True)
        .only("id", "symbol", "short_code", "name", "market", "asset_class")
        .order_by("market", "symbol")
    )
    grouped: dict[str, list[Instrument]] = defaultdict(list)
    for row in rows:
        grouped[row.market].append(row)
    return dict(grouped)


def _safe_str_decimal(value: object) -> str | None:
    parsed = to_decimal(value)
    if parsed is None:
        return None
    return trim_decimal_str(parsed)


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


def _fake_index_rows(instruments: list[Instrument]) -> list[dict]:
    rows = []
    for idx, inst in enumerate(instruments, start=1):
        prev_close = Decimal("1000") + Decimal(idx * 10)
        current = prev_close * Decimal("1.005")
        rows.append(
            {
                "symbol": inst.symbol,
                "instrument_id": inst.id,
                "name": inst.name,
                "prev_close": trim_decimal_str(prev_close),
                "day_high": trim_decimal_str(current * Decimal("1.002")),
                "day_low": trim_decimal_str(prev_close * Decimal("0.998")),
                "pct": trim_decimal_str(Decimal("0.5")),
            }
        )
    return rows


def _extract_series_value(frame, field: str, provider_symbol: str):
    if frame is None:
        return None
    columns = getattr(frame, "columns", None)
    if columns is None:
        return None
    try:
        import pandas as pd  # type: ignore
    except Exception:
        pd = None
    is_multi = pd is not None and isinstance(columns, pd.MultiIndex)
    try:
        if is_multi:
            series = frame[field][provider_symbol].dropna()
        else:
            series = frame[field].dropna()
    except Exception:
        return None
    if len(series) == 0:
        return None
    return series


def _fetch_rows_yfinance(instruments: list[Instrument]) -> list[dict]:
    if yf is None:
        raise ValidationError({"message": "yfinance 未安装，无法拉取指数行情。"})

    symbol_map: dict[str, Instrument] = {}
    provider_symbols: list[str] = []
    for inst in instruments:
        definition = index_definition_by_symbol(inst.symbol)
        if definition is None:
            continue
        provider_symbols.append(definition.provider_symbol)
        symbol_map[definition.provider_symbol] = inst

    if not provider_symbols:
        return []

    frame = yf.download(
        provider_symbols,
        period="5d",
        interval="1d",
        progress=False,
        auto_adjust=False,
        group_by="column",
        threads=False,
    )
    if frame is None or getattr(frame, "empty", True):
        raise ValidationError({"message": "指数行情源返回空数据。"})

    rows: list[dict] = []
    for provider_symbol, inst in symbol_map.items():
        close_series = _extract_series_value(frame, "Close", provider_symbol)
        high_series = _extract_series_value(frame, "High", provider_symbol)
        low_series = _extract_series_value(frame, "Low", provider_symbol)
        if close_series is None or high_series is None or low_series is None:
            rows.append(_build_null_row(inst))
            continue

        last_close = close_series.iloc[-1]
        prev_close = close_series.iloc[-2] if len(close_series) >= 2 else last_close
        pct = None
        prev_decimal = to_decimal(prev_close)
        last_decimal = to_decimal(last_close)
        if prev_decimal not in (None, Decimal("0")) and last_decimal is not None:
            pct = trim_decimal_str(((last_decimal - prev_decimal) / prev_decimal) * Decimal("100"))

        rows.append(
            {
                "symbol": inst.symbol,
                "instrument_id": inst.id,
                "name": inst.name,
                "prev_close": _safe_str_decimal(prev_close),
                "day_high": _safe_str_decimal(high_series.iloc[-1]),
                "day_low": _safe_str_decimal(low_series.iloc[-1]),
                "pct": pct,
            }
        )
    return rows


def _fetch_rows_for_market(instruments: list[Instrument]) -> list[dict]:
    provider = _index_provider()
    quote_provider_mode = str(getattr(settings, "MARKET_QUOTE_PROVIDER", "real") or "real").strip().lower()
    if quote_provider_mode == "fake" or provider == "fake":
        return _fake_index_rows(instruments)
    if provider == "yfinance":
        return _fetch_rows_yfinance(instruments)
    raise ValidationError({"message": f"不支持的指数行情源：{provider}"})


def _previous_payload() -> dict:
    payload = cache.get(MARKET_INDEX_QUOTES_KEY) or {}
    return payload if isinstance(payload, dict) else {}


def _index_by_symbol(rows: object) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol:
            out[symbol] = row
    return out


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


def build_market_indices_snapshot() -> dict:
    grouped = _group_instruments_by_market()
    previous = _previous_payload()
    previous_data = previous.get("data") if isinstance(previous.get("data"), dict) else {}

    merged: dict[str, list[dict]] = {}
    updated_markets: set[str] = set()

    for market, instruments in grouped.items():
        previous_rows = _index_by_symbol(previous_data.get(market, []))
        missing_cache = any(inst.symbol not in previous_rows for inst in instruments)
        decision = market_guard_decision(market)
        should_pull = decision.should_pull or missing_cache or market not in previous_data

        latest_rows: dict[str, dict] = {}
        if should_pull:
            try:
                latest_rows = _index_by_symbol(_fetch_rows_for_market(instruments))
                updated_markets.add(market)
            except Exception:
                logger.exception("index.quote.fetch_failed market=%s", market)

        market_rows: list[dict] = []
        for inst in instruments:
            row = latest_rows.get(inst.symbol) or previous_rows.get(inst.symbol) or _build_null_row(inst)
            market_rows.append(row)
        merged[market] = market_rows

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
