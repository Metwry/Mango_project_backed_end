from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.utils import timezone

from common.normalize import normalize_code, resolve_short_code
from common.utils import safe_payload_data

from ..sources.fetch import pull_single_instrument_quote

WATCHLIST_QUOTES_KEY = "markets:instrument:instrument_all"
WATCHLIST_QUOTES_MARKET_KEY_PREFIX = "markets:instrument:"
USD_EXCHANGE_RATES_KEY = "markets:usd-base-rates"
MARKET_INDEX_QUOTES_KEY = "markets:indices"
CELERY_STARTUP_PULL_LOCK_KEY = "runtime:celery:startup-pull-lock"

UTC8 = ZoneInfo("Asia/Shanghai")
FX_REFRESH_INTERVAL = timedelta(hours=4)


def instrument_market_cache_key(market: object) -> str:
    return f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{normalize_code(market)}"


def _cache_mapping(key: str) -> dict:
    payload = cache.get(key)
    return payload if isinstance(payload, dict) else {}


# 从行情行中解析统一使用的代码标识。
def quote_code(row: dict) -> str:
    return resolve_short_code(row.get("short_code"), row.get("symbol"))


# 读取指定市场的行情列表并保证返回列表结构。
def market_rows(data: dict, market: str) -> list[dict]:
    rows = data.get(market, [])
    return rows if isinstance(rows, list) else []


def ensure_market_rows(data: dict, market: str) -> list[dict]:
    rows = data.get(market)
    if isinstance(rows, list):
        return rows

    normalized_rows: list[dict] = []
    data[market] = normalized_rows
    return normalized_rows


# 提取行情列表中的代码集合。
def snapshot_code_set(rows: list[dict]) -> set[str]:
    return {code for row in rows if (code := quote_code(row))}


# 按代码为行情列表建立索引字典。
def index_rows_by_code(rows: list[dict]) -> dict[str, dict]:
    return {code: row for row in rows if (code := quote_code(row))}


# 在行情列表中按短代码查找单条行情。
def find_quote_by_code(rows: object, short_code: str) -> dict | None:
    if not isinstance(rows, list):
        return None
    code = normalize_code(short_code)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if quote_code(row) == code:
            return row
    return None


# 在指定市场行情列表中插入或更新一条行情。
def upsert_market_quote(data: dict, market: str, quote_row: dict) -> None:
    market_quotes = ensure_market_rows(data, market)
    normalized_quote = dict(quote_row)
    code = quote_code(normalized_quote)
    if not code:
        return
    normalized_quote["short_code"] = code
    for idx, row in enumerate(market_quotes):
        if isinstance(row, dict) and quote_code(row) == code:
            market_quotes[idx] = normalized_quote
            return
    market_quotes.append(normalized_quote)


# 从指定市场行情列表中移除目标代码对应的行情。
def pop_quote_by_code(data: dict, market: str, short_code: str) -> dict | None:
    rows = market_rows(data, market)
    code = normalize_code(short_code)
    kept = []
    removed_row = None
    for row in rows:
        row_code = quote_code(row)
        if row_code == code:
            if removed_row is None:
                removed_row = row
            continue
        kept.append(row)

    if removed_row is None:
        return None
    if kept:
        data[market] = kept
    else:
        data.pop(market, None)
    return removed_row


# 读取自选行情总快照缓存。
def get_market_data_payload() -> dict:
    return _cache_mapping(WATCHLIST_QUOTES_KEY)


def get_index_quote_payload() -> dict:
    return _cache_mapping(MARKET_INDEX_QUOTES_KEY)


def get_usd_rate_payload() -> dict:
    return _cache_mapping(USD_EXCHANGE_RATES_KEY)


# 将行情快照构建为按市场和代码索引的映射。
def build_quote_index(payload: object) -> dict[tuple[str, str], dict]:
    data = safe_payload_data(payload)
    return {
        (market_code, code): row
        for market, rows in data.items()
        if (market_code := normalize_code(market))
        for row in market_rows(data, market)
        if (code := quote_code(row))
    }


# 将更新后的自选行情快照写回缓存。
def write_market_data(payload: dict, data: dict, updated_markets: set[str]) -> None:
    if not updated_markets:
        return

    updated_at = timezone.now().astimezone(UTC8).isoformat()
    next_payload = dict(payload) if isinstance(payload, dict) else {}
    next_payload.update(
        {
            "updated_at": updated_at,
            "data": data,
        }
    )

    timeout = None
    cache.set(WATCHLIST_QUOTES_KEY, next_payload, timeout=timeout)

    for market in updated_markets:
        rows = data.get(market, [])
        market_key = instrument_market_cache_key(market)
        if rows:
            cache.set(
                market_key,
                {
                    "updated_at": updated_at,
                    "market": market,
                    "data": rows,
                },
                timeout=timeout,
            )
        else:
            cache.delete(market_key)


# 确保指定标的在缓存中有可用行情并返回来源。
def ensure_instrument_quote(instrument, fetch_missing: bool = True) -> tuple[bool, str]:
    market = instrument.market
    short_code = instrument.short_code
    if not market or not short_code:
        return False, "none"

    payload = get_market_data_payload()
    data = safe_payload_data(payload)
    existing_rows = market_rows(data, market)
    existing_quote = find_quote_by_code(existing_rows, short_code)
    if existing_quote is not None:
        return True, "redis"

    if not fetch_missing:
        return False, "none"

    one_quote = pull_single_instrument_quote(
        symbol=instrument.symbol,
        short_code=instrument.short_code,
        name=instrument.name,
        market=market,
    )
    if not one_quote:
        return False, "none"

    one_quote["short_code"] = quote_code(one_quote) or instrument.short_code
    one_quote["name"] = one_quote.get("name") or instrument.name
    one_quote["logo_url"] = instrument.logo_url or None
    one_quote["logo_color"] = instrument.logo_color or None
    upsert_market_quote(data, market, one_quote)
    write_market_data(payload, data, {market})
    return True, "api"
