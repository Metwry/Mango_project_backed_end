from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from django.conf import settings

from common.utils import format_decimal_str, normalize_code, to_decimal

from .quote_rows import quote_code

MARKET_CRYPTO = "CRYPTO"
MARKET_CN = "CN"
MARKET_HK = "HK"
MARKET_US = "US"
MARKET_FX = "FX"
DEFAULT_MARKET_PULL_INTERVAL_MINUTES = 10
CALENDAR_NAME_BY_MARKET = {
    MARKET_US: "XNYS",
    MARKET_HK: "XHKG",
    MARKET_CN: "XSHG",
}

try:
    import exchange_calendars as xcals
except Exception:  # pragma: no cover - runtime dependency
    xcals = None

_EXCHANGE_CALENDAR_CACHE: dict[str, object] = {}


def normalize_market_code(market: object) -> str:
    return normalize_code(market)


def market_timezone_name(market: object) -> str:
    market_code = normalize_market_code(market)
    if market_code == MARKET_US:
        return "America/New_York"
    if market_code == MARKET_CN:
        return "Asia/Shanghai"
    if market_code == MARKET_HK:
        return "Asia/Hong_Kong"
    return "UTC"


def market_timezone(market: object) -> ZoneInfo:
    return ZoneInfo(market_timezone_name(market))


def is_weekday(dt_local: datetime) -> bool:
    return dt_local.weekday() < 5


def exchange_calendar_name(market: object) -> str | None:
    return CALENDAR_NAME_BY_MARKET.get(normalize_market_code(market))


def get_exchange_calendar(market: object):
    market_code = normalize_market_code(market)
    cached = _EXCHANGE_CALENDAR_CACHE.get(market_code)
    if cached is not None:
        return cached

    calendar_name = exchange_calendar_name(market_code)
    if calendar_name is None or xcals is None:
        return None

    calendar = xcals.get_calendar(calendar_name)
    _EXCHANGE_CALENDAR_CACHE[market_code] = calendar
    return calendar


def _to_exchange_minute(now_utc: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(now_utc)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.floor("min")


def _fallback_open_hours_market(market: str, now_utc: datetime) -> bool:
    market_code = normalize_market_code(market)
    if market_code == MARKET_US:
        dt = now_utc.astimezone(market_timezone(market_code))
        return is_weekday(dt) and time(9, 30) <= dt.time() <= time(16, 0)
    if market_code == MARKET_CN:
        dt = now_utc.astimezone(market_timezone(market_code))
        current = dt.time()
        return is_weekday(dt) and ((time(9, 30) <= current <= time(11, 30)) or (time(13, 0) <= current <= time(15, 0)))
    if market_code == MARKET_HK:
        dt = now_utc.astimezone(market_timezone(market_code))
        current = dt.time()
        return is_weekday(dt) and ((time(9, 30) <= current <= time(12, 0)) or (time(13, 0) <= current <= time(16, 0)))
    return False


def should_fetch_market(market: str, now_utc: datetime | None = None) -> bool:
    now_utc = now_utc or datetime.now(timezone.utc)
    market_code = normalize_market_code(market)
    if market_code == MARKET_CRYPTO:
        return True
    if market_code in CALENDAR_NAME_BY_MARKET:
        calendar = get_exchange_calendar(market_code)
        if calendar is None:
            return _fallback_open_hours_market(market_code, now_utc)
        return bool(calendar.is_open_on_minute(_to_exchange_minute(now_utc)))
    if market_code == MARKET_FX:
        return is_weekday(now_utc.astimezone(ZoneInfo("UTC")))
    return False


def market_pull_interval_minutes(market: object) -> int:
    market_code = normalize_market_code(market)
    if market_code == MARKET_FX:
        raw = getattr(settings, "MARKET_FX_PULL_INTERVAL_MINUTES", 240)
    elif market_code == MARKET_CRYPTO:
        raw = getattr(settings, "MARKET_CRYPTO_PULL_INTERVAL_MINUTES", 10)
    else:
        raw = getattr(settings, "MARKET_PULL_INTERVAL_MINUTES", DEFAULT_MARKET_PULL_INTERVAL_MINUTES)

    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_MARKET_PULL_INTERVAL_MINUTES
    return max(1, min(value, 240))


def should_pull_market_tick(market: str, now_utc: datetime | None = None) -> bool:
    now_utc = now_utc or datetime.now(timezone.utc)
    market_code = normalize_market_code(market)
    if not should_fetch_market(market_code, now_utc):
        return False

    interval_minutes = market_pull_interval_minutes(market_code)
    now_local = now_utc.astimezone(market_timezone(market_code))
    minutes_since_day_start = now_local.hour * 60 + now_local.minute
    return (minutes_since_day_start % interval_minutes) == 0


def safe_price_str(raw: object) -> str | None:
    value = to_decimal(raw)
    return format_decimal_str(value) if value is not None else None


def normalize_quote_row(row: dict) -> dict:
    normalized_row = dict(row)
    normalized_row["logo_url"] = normalized_row.get("logo_url") or None
    normalized_row["logo_color"] = normalized_row.get("logo_color") or None
    return normalized_row


def format_latest_quote_item(*, market: str, short_code: str, row: dict | None) -> dict:
    latest_price = safe_price_str(row.get("price")) if isinstance(row, dict) else None
    return {
        "market": market,
        "short_code": short_code,
        "latest_price": latest_price,
        "logo_url": (row.get("logo_url") or None) if isinstance(row, dict) else None,
        "logo_color": (row.get("logo_color") or None) if isinstance(row, dict) else None,
    }


def format_watchlist_instrument(instrument) -> dict:
    return {
        "symbol": instrument.symbol,
        "short_code": instrument.short_code,
        "name": instrument.name,
        "market": instrument.market,
        "logo_url": instrument.logo_url,
        "logo_color": instrument.logo_color,
    }


def filter_snapshot_quotes(rows: object, allow_codes: set[str]) -> list[dict]:
    if not isinstance(rows, list):
        return []

    filtered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if quote_code(row) in allow_codes:
            filtered.append(normalize_quote_row(row))
    return filtered
