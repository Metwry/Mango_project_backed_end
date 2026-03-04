from .quote_snapshot_service import (
    build_quote_index,
    get_snapshot_payload,
    safe_price_str,
)
from .subscription_query_service import user_watchlist_codes_by_market
from shared.utils import resolve_short_code


def _filter_quotes(rows, allow_codes):
    if not isinstance(rows, list):
        return []

    filtered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = resolve_short_code(row.get("short_code"), row.get("symbol"))
        if code in allow_codes:
            normalized_row = dict(row)
            normalized_row["logo_url"] = normalized_row.get("logo_url") or None
            normalized_row["logo_color"] = normalized_row.get("logo_color") or None
            filtered.append(normalized_row)
    return filtered


def build_user_markets_snapshot(user) -> dict:
    payload = get_snapshot_payload()
    data = payload.get("data")
    market_data = data if isinstance(data, dict) else {}
    stale_markets = {
        str(m).strip().upper()
        for m in (payload.get("stale_markets") or [])
        if isinstance(m, str)
    }
    watchlist_codes = user_watchlist_codes_by_market(user)

    markets = []
    for market in sorted(watchlist_codes.keys()):
        allow_codes = watchlist_codes[market]
        raw_quotes = market_data.get(market, [])
        quotes = _filter_quotes(raw_quotes, allow_codes)
        markets.append(
            {
                "market": market,
                "stale": market in stale_markets,
                "quotes": quotes,
            }
        )

    return {
        "updated_at": payload.get("updated_at"),
        "markets": markets,
    }


def build_latest_quotes(items: list[dict]) -> list[dict]:
    payload = get_snapshot_payload()
    quote_index = build_quote_index(payload)

    results = []
    for item in items:
        market = item["market"]
        short_code = item["short_code"]
        row = quote_index.get((market, short_code))
        latest_price = safe_price_str(row.get("price")) if isinstance(row, dict) else None
        results.append(
            {
                "market": market,
                "short_code": short_code,
                "latest_price": latest_price,
                "logo_url": (row.get("logo_url") or None) if isinstance(row, dict) else None,
                "logo_color": (row.get("logo_color") or None) if isinstance(row, dict) else None,
            }
        )
    return results
