from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from common.utils.cache_utils import safe_payload_data
from common.utils.code_utils import normalize_code, resolve_short_code
from common.utils.decimal_utils import to_decimal, trim_decimal_str

from .cache_keys import (
    DEFAULT_WATCHLIST_ORPHAN_TTL,
    UTC8,
    WATCHLIST_QUOTES_KEY,
    WATCHLIST_QUOTES_MARKET_KEY_PREFIX,
    WATCHLIST_QUOTES_ORPHAN_KEY_PREFIX,
)


# 将原始价格值安全转换为前端展示字符串。
def safe_price_str(raw: object) -> str | None:
    value = to_decimal(raw)
    if value is None:
        return None
    return trim_decimal_str(value)


# 代理单标的行情拉取，兼容测试 patch 和延迟导入。
def pull_single_instrument_quote(*args, **kwargs):
    from accounts.services.quote_fetcher import pull_single_instrument_quote as impl
    return impl(*args, **kwargs)


# 构造孤儿行情缓存键。
def orphan_quote_cache_key(market: object, short_code: object) -> str:
    market_code = normalize_code(market)
    code = normalize_code(short_code)
    return f"{WATCHLIST_QUOTES_ORPHAN_KEY_PREFIX}{market_code}:{code}"


# 读取并规范化孤儿行情缓存 TTL 配置。
def watchlist_orphan_ttl() -> int:
    raw = getattr(settings, "WATCHLIST_ORPHAN_QUOTE_TTL", DEFAULT_WATCHLIST_ORPHAN_TTL)
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        ttl = DEFAULT_WATCHLIST_ORPHAN_TTL
    return max(60, ttl)


# 读取当前自选行情总快照缓存。
def get_snapshot_payload() -> dict:
    payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
    return payload if isinstance(payload, dict) else {}


# 将行情快照数据构建为按市场和短代码索引的字典。
def build_quote_index(payload: object) -> dict[tuple[str, str], dict]:
    data = payload.get("data") if isinstance(payload, dict) else {}
    quote_index: dict[tuple[str, str], dict] = {}
    if not isinstance(data, dict):
        return quote_index

    for market, rows in data.items():
        market_code = normalize_code(market)
        if not market_code or not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue
            short_code = resolve_short_code(row.get("short_code"), row.get("symbol"))
            if short_code:
                quote_index[(market_code, short_code)] = row
    return quote_index


# 在单个市场行情列表中按短代码查找记录。
def find_quote_by_code(rows: object, short_code: str) -> dict | None:
    if not isinstance(rows, list):
        return None
    code = normalize_code(short_code)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if normalize_code(row.get("short_code")) == code:
            return row
    return None


# 在指定市场行情列表中更新或追加一条行情记录。
def upsert_market_quote(data: dict, market: str, quote_row: dict) -> None:
    market_rows = data.setdefault(market, [])
    if not isinstance(market_rows, list):
        market_rows = []
        data[market] = market_rows

    code = normalize_code(quote_row.get("short_code"))
    for idx, row in enumerate(market_rows):
        if isinstance(row, dict) and normalize_code(row.get("short_code")) == code:
            market_rows[idx] = quote_row
            return

    market_rows.append(quote_row)


# 将更新后的行情快照和市场级缓存写回缓存系统。
def write_snapshot(payload: dict, data: dict, updated_markets: set[str]) -> None:
    if not updated_markets:
        return

    updated_at = timezone.now().astimezone(UTC8).isoformat()
    existing_updated = {
        normalize_code(m)
        for m in (payload.get("updated_markets") or [])
        if isinstance(m, str)
    }
    existing_updated.update(updated_markets)

    stale_markets = [
        m for m in (payload.get("stale_markets") or [])
        if normalize_code(m) not in updated_markets
    ]

    next_payload = dict(payload) if isinstance(payload, dict) else {}
    next_payload.update(
        {
            "updated_at": updated_at,
            "updated_markets": sorted(existing_updated),
            "stale_markets": stale_markets,
            "data": data,
        }
    )

    timeout = None
    cache.set(WATCHLIST_QUOTES_KEY, next_payload, timeout=timeout)

    for market in updated_markets:
        rows = data.get(market, [])
        market_key = f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{market}"
        if rows:
            cache.set(
                market_key,
                {
                    "updated_at": updated_at,
                    "market": market,
                    "stale": False,
                    "data": rows,
                },
                timeout=timeout,
            )
        else:
            cache.delete(market_key)


# 从指定市场行情列表中移除某个短代码对应的行情记录。
def pop_quote_by_code(data: dict, market: str, short_code: str) -> dict | None:
    rows = data.get(market, [])
    if not isinstance(rows, list):
        return None

    code = normalize_code(short_code)
    kept = []
    removed_row = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_code = resolve_short_code(row.get("short_code"), row.get("symbol"))
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


# 读取某个被移出快照但暂存的孤儿行情。
def get_orphan_quote(market: str, short_code: str) -> dict | None:
    orphan_key = orphan_quote_cache_key(market, short_code)
    orphan_quote = cache.get(orphan_key)
    return orphan_quote if isinstance(orphan_quote, dict) else None


# 保存一条孤儿行情，便于后续重新加入自选时复用。
def save_orphan_quote(market: str, short_code: str, quote_row: dict) -> str:
    orphan_key = orphan_quote_cache_key(market, short_code)
    cache.set(orphan_key, quote_row, timeout=watchlist_orphan_ttl())
    return orphan_key


# 删除指定孤儿行情缓存。
def delete_orphan_quote(market: str, short_code: str) -> None:
    cache.delete(orphan_quote_cache_key(market, short_code))


# 确保某个标的在行情缓存中存在，必要时从孤儿缓存或外部接口补齐。
def ensure_instrument_quote(instrument, fetch_missing: bool = True, use_orphan: bool = True) -> tuple[bool, str]:
    market = normalize_code(instrument.market)
    short_code = normalize_code(instrument.short_code)
    if not market or not short_code:
        return False, "none"

    payload = get_snapshot_payload()
    data = safe_payload_data(payload)
    market_rows = data.get(market, [])
    existing_quote = find_quote_by_code(market_rows, short_code)
    if existing_quote is not None:
        return True, "redis"

    if use_orphan:
        orphan_quote = get_orphan_quote(market, short_code)
        if orphan_quote is not None:
            one_quote = dict(orphan_quote)
            one_quote["short_code"] = one_quote.get("short_code") or instrument.short_code
            one_quote["name"] = one_quote.get("name") or instrument.name
            one_quote["logo_url"] = instrument.logo_url or None
            one_quote["logo_color"] = instrument.logo_color or None
            upsert_market_quote(data, market, one_quote)
            write_snapshot(payload, data, {market})
            delete_orphan_quote(market, short_code)
            return True, "redis_orphan"

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

    one_quote["short_code"] = one_quote.get("short_code") or instrument.short_code
    one_quote["name"] = one_quote.get("name") or instrument.name
    one_quote["logo_url"] = instrument.logo_url or None
    one_quote["logo_color"] = instrument.logo_color or None
    upsert_market_quote(data, market, one_quote)
    write_snapshot(payload, data, {market})
    return True, "api"

