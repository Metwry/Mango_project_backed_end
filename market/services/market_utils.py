from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from django.conf import settings

from common.normalize import normalize_code, resolve_short_code
from common.utils import format_decimal_str, to_decimal

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


# 标准化市场代码。
def normalize_market_code(market: object) -> str:
    return normalize_code(market)


# 返回指定市场对应的时区名称。
def market_timezone_name(market: object) -> str:
    market_code = normalize_market_code(market)
    if market_code == MARKET_US:
        return "America/New_York"
    if market_code == MARKET_CN:
        return "Asia/Shanghai"
    if market_code == MARKET_HK:
        return "Asia/Hong_Kong"
    return "UTC"


# 返回指定市场对应的时区对象。
def market_timezone(market: object) -> ZoneInfo:
    return ZoneInfo(market_timezone_name(market))


# 判断本地时间是否为工作日。
def is_weekday(dt_local: datetime) -> bool:
    return dt_local.weekday() < 5


# 返回市场对应的交易所日历名称。
def exchange_calendar_name(market: object) -> str | None:
    return CALENDAR_NAME_BY_MARKET.get(normalize_market_code(market))


# 读取并缓存指定市场的交易所日历对象。
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


# 将时间统一转换为交易所分钟粒度时间戳。
def _to_exchange_minute(now_utc: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(now_utc)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.floor("min")


# 在无交易所日历时使用兜底交易时段判断是否开市。
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


# 判断当前时间市场是否处于可拉取行情的交易时段。
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


# 读取指定市场的行情拉取间隔分钟数。
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


# 判断当前分钟是否命中该市场的拉取节奏。
def should_pull_market_tick(market: str, now_utc: datetime | None = None) -> bool:
    now_utc = now_utc or datetime.now(timezone.utc)
    market_code = normalize_market_code(market)
    if not should_fetch_market(market_code, now_utc):
        return False

    interval_minutes = market_pull_interval_minutes(market_code)
    now_local = now_utc.astimezone(market_timezone(market_code))
    minutes_since_day_start = now_local.hour * 60 + now_local.minute
    return (minutes_since_day_start % interval_minutes) == 0


# 安全地将价格值格式化为字符串。
def safe_price_str(raw: object) -> str | None:
    value = to_decimal(raw)
    return format_decimal_str(value) if value is not None else None


# 规范化单条行情中的可选展示字段。
def normalize_quote_row(row: dict) -> dict:
    normalized_row = dict(row)
    normalized_row["logo_url"] = normalized_row.get("logo_url") or None
    normalized_row["logo_color"] = normalized_row.get("logo_color") or None
    return normalized_row


# 从行情行中解析统一代码。
def _quote_code(row: dict) -> str:
    return resolve_short_code(row.get("short_code"), row.get("symbol"))


# 将缓存行情格式化为最新价接口返回项。
def format_latest_quote_item(*, market: str, short_code: str, row: dict | None) -> dict:
    latest_price = safe_price_str(row.get("price")) if isinstance(row, dict) else None
    return {
        "market": market,
        "short_code": short_code,
        "latest_price": latest_price,
        "logo_url": (row.get("logo_url") or None) if isinstance(row, dict) else None,
        "logo_color": (row.get("logo_color") or None) if isinstance(row, dict) else None,
    }


# 将标的对象格式化为自选接口使用的结构。
def format_watchlist_instrument(instrument) -> dict:
    return {
        "symbol": instrument.symbol,
        "short_code": instrument.short_code,
        "name": instrument.name,
        "market": instrument.market,
        "logo_url": instrument.logo_url,
        "logo_color": instrument.logo_color,
    }


# 按允许代码集合过滤行情快照列表。
def filter_snapshot_quotes(rows: object, allow_codes: set[str]) -> list[dict]:
    if not isinstance(rows, list):
        return []

    filtered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _quote_code(row) in allow_codes:
            filtered.append(normalize_quote_row(row))
    return filtered
