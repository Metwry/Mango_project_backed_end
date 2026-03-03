from .quote_snapshot_service import (
    build_quote_index,
    get_snapshot_payload,
    safe_price_str,
)
from ..models import UserInstrumentSubscription
from shared.utils import normalize_code, strip_market_suffix


def _watchlist_codes_by_market(user) -> dict[str, set[str]]:
    if not user or not getattr(user, "is_authenticated", False):
        return {}

    grouped: dict[str, set[str]] = {}
    rows = (
        UserInstrumentSubscription.objects
        .filter(user=user, from_watchlist=True)
        .values_list("instrument__market", "instrument__short_code", "instrument__symbol")
    )

    for market, short_code, symbol in rows:
        m = normalize_code(market)
        code = normalize_code(short_code) or strip_market_suffix(symbol)
        if not m or not code:
            continue
        grouped.setdefault(m, set()).add(code)

    return grouped


def _filter_quotes(rows, allow_codes):
    if not isinstance(rows, list):
        return []

    filtered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = normalize_code(row.get("short_code")) or strip_market_suffix(row.get("symbol"))
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
    watchlist_codes = _watchlist_codes_by_market(user)

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
