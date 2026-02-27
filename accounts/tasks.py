import logging
from collections import defaultdict
from typing import Dict, List, Set
from zoneinfo import ZoneInfo

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from accounts.services.quote_fetcher import (
    get_unique_instruments_from_watchlist,
    pull_usd_exchange_rates,
    pull_watchlist_quotes,
)

logger = logging.getLogger(__name__)

WATCHLIST_QUOTES_KEY = "watchlist:quotes:latest"
WATCHLIST_QUOTES_MARKET_KEY_PREFIX = "watchlist:quotes:market:"
USD_EXCHANGE_RATES_KEY = "watchlist:fx:usd-rates:latest"
UTC8 = ZoneInfo("Asia/Shanghai")


def _normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def _strip_market_suffix(symbol: object) -> str:
    s = _normalize_code(symbol)
    if "." not in s:
        return s
    return s.rsplit(".", 1)[0]


def _safe_payload_data(payload: object) -> Dict[str, List[dict]]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    safe: Dict[str, List[dict]] = {}
    for market, quotes in data.items():
        if isinstance(market, str) and isinstance(quotes, list):
            safe[market] = quotes
    return safe


def _watchlist_codes_by_market() -> Dict[str, Set[str]]:
    grouped: Dict[str, Set[str]] = defaultdict(set)
    for symbol, short_code, _, market in get_unique_instruments_from_watchlist():
        m = str(market or "").strip().upper()
        code = _normalize_code(short_code) or _strip_market_suffix(symbol)
        if m and code:
            grouped[m].add(code)
    return dict(grouped)


def _filter_snapshot_by_watchlist(
    snapshot: Dict[str, List[dict]],
    watchlist_codes: Dict[str, Set[str]],
) -> Dict[str, List[dict]]:
    filtered: Dict[str, List[dict]] = {}
    for market, allow_codes in watchlist_codes.items():
        market_quotes = snapshot.get(market, [])
        if not isinstance(market_quotes, list):
            filtered[market] = []
            continue
        kept = []
        for row in market_quotes:
            if not isinstance(row, dict):
                continue
            code = _normalize_code(row.get("short_code")) or _strip_market_suffix(row.get("symbol"))
            if code in allow_codes:
                kept.append(row)
        filtered[market] = kept
    return filtered


@shared_task
def task_pull_watchlist_quotes():
    previous_payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
    previous_data = _safe_payload_data(previous_payload)
    need_bootstrap = not previous_data

    quotes = pull_watchlist_quotes(force_fetch_all_markets=need_bootstrap)
    watchlist_codes = _watchlist_codes_by_market()

    merged_data = dict(previous_data)
    if quotes:
        merged_data.update(quotes)
    merged_data = _filter_snapshot_by_watchlist(merged_data, watchlist_codes)

    updated_markets = set(quotes.keys())
    stale_markets = sorted(set(merged_data.keys()) - updated_markets)

    updated_at = timezone.now().astimezone(UTC8).isoformat()
    payload = {
        "updated_at": updated_at,
        "bootstrap_mode": need_bootstrap,
        "updated_markets": sorted(updated_markets),
        "stale_markets": stale_markets,
        "data": merged_data,
    }

    timeout = None

    try:
        cache.set(WATCHLIST_QUOTES_KEY, payload, timeout=timeout)
        removed_markets = set(previous_data.keys()) - set(merged_data.keys())
        for market in removed_markets:
            cache.delete(f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{market}")

        for market, market_quotes in merged_data.items():
            cache.set(
                f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{market}",
                {
                    "updated_at": payload["updated_at"],
                    "market": market,
                    "stale": market in stale_markets,
                    "data": market_quotes,
                },
                timeout=timeout,
            )
    except Exception:
        logger.exception("write watchlist quotes to redis failed")

    try:
        fx_rows = merged_data.get("FX", [])
        if not isinstance(fx_rows, list):
            fx_rows = []
        usd_rates = pull_usd_exchange_rates(seed_rows=fx_rows)
        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {
                "base": "USD",
                "updated_at": updated_at,
                "rates": usd_rates,
            },
            timeout=timeout,
        )
    except Exception:
        logger.exception("write usd exchange rates to redis failed")

    if not quotes and previous_data:
        logger.info("no market updated, served stale snapshot markets=%s", stale_markets)

    return payload
