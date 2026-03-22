from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from common.utils import normalize_code, safe_payload_data

from .cache import (
    DEFAULT_WATCHLIST_ORPHAN_TTL,
    UTC8,
    WATCHLIST_QUOTES_KEY,
    WATCHLIST_QUOTES_MARKET_KEY_PREFIX,
    WATCHLIST_QUOTES_ORPHAN_KEY_PREFIX,
)
from .quote_rows import find_quote_by_code, market_rows, pop_quote_by_code, quote_code, upsert_market_quote
from .utils import safe_price_str


def pull_single_instrument_quote(*args, **kwargs):
    from accounts.services.quote_fetcher import pull_single_instrument_quote as impl

    return impl(*args, **kwargs)


def orphan_quote_cache_key(market: object, short_code: object) -> str:
    market_code = normalize_code(market)
    code = normalize_code(short_code)
    return f"{WATCHLIST_QUOTES_ORPHAN_KEY_PREFIX}{market_code}:{code}"


def watchlist_orphan_ttl() -> int:
    raw = getattr(settings, "WATCHLIST_ORPHAN_QUOTE_TTL", DEFAULT_WATCHLIST_ORPHAN_TTL)
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        ttl = DEFAULT_WATCHLIST_ORPHAN_TTL
    return max(60, ttl)


def get_market_data_payload() -> dict:
    payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
    return payload if isinstance(payload, dict) else {}


def build_quote_index(payload: object) -> dict[tuple[str, str], dict]:
    data = safe_payload_data(payload)
    return {
        (market_code, code): row
        for market, rows in data.items()
        if (market_code := normalize_code(market))
        for row in market_rows(data, market)
        if (code := quote_code(row))
    }


def write_market_data(payload: dict, data: dict, updated_markets: set[str]) -> None:
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


def get_orphan_quote(market: str, short_code: str) -> dict | None:
    orphan_quote = cache.get(orphan_quote_cache_key(market, short_code))
    return orphan_quote if isinstance(orphan_quote, dict) else None


def save_orphan_quote(market: str, short_code: str, quote_row: dict) -> str:
    orphan_key = orphan_quote_cache_key(market, short_code)
    cache.set(orphan_key, quote_row, timeout=watchlist_orphan_ttl())
    return orphan_key


def delete_orphan_quote(market: str, short_code: str) -> None:
    cache.delete(orphan_quote_cache_key(market, short_code))


def ensure_instrument_quote(instrument, fetch_missing: bool = True, use_orphan: bool = True) -> tuple[bool, str]:
    market = normalize_code(instrument.market)
    short_code = normalize_code(instrument.short_code)
    if not market or not short_code:
        return False, "none"

    payload = get_market_data_payload()
    data = safe_payload_data(payload)
    existing_rows = data.get(market, [])
    existing_quote = find_quote_by_code(existing_rows, short_code)
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
            write_market_data(payload, data, {market})
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
    write_market_data(payload, data, {market})
    return True, "api"
