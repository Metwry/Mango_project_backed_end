from django.db.models import Case, IntegerField, Q, Value, When

from ..models import Instrument
from .instrument_subscriptions import user_watchlist_codes_by_market
from .market_utils import filter_snapshot_quotes, format_latest_quote_item
from .quote_cache import build_quote_index, get_market_data_payload


# 按代码或名称搜索可用标的。
def search_instruments(*, query: str, limit: int):
    if not query:
        return Instrument.objects.none()

    query_upper = query.upper()

    return (
        Instrument.objects
        .filter(is_active=True)
        .filter(
            Q(short_code__icontains=query_upper)
            | Q(name__icontains=query)
        )
        .annotate(
            priority=Case(
                When(short_code__iexact=query_upper, then=Value(0)),
                When(short_code__istartswith=query_upper, then=Value(1)),
                When(name__istartswith=query, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        .order_by("priority", "short_code", "name")[:limit]
    )


# 基于缓存行情构建当前用户的市场快照。
def build_user_markets_snapshot(user) -> dict:
    payload = get_market_data_payload()
    data = payload.get("data")
    market_data = data if isinstance(data, dict) else {}
    watchlist_codes = user_watchlist_codes_by_market(user)

    markets = []
    for market in sorted(watchlist_codes.keys()):
        allow_codes = watchlist_codes[market]
        raw_quotes = market_data.get(market, [])
        quotes = filter_snapshot_quotes(raw_quotes, allow_codes)
        markets.append(
            {
                "market": market,
                "quotes": quotes,
            }
        )

    return {
        "updated_at": payload.get("updated_at"),
        "markets": markets,
    }


# 批量返回请求项对应的最新价格结果。
def build_latest_quotes(items: list[dict]) -> list[dict]:
    payload = get_market_data_payload()
    quote_index = build_quote_index(payload)

    results = []
    for item in items:
        market = item["market"]
        short_code = item["short_code"]
        row = quote_index.get((market, short_code))
        results.append(format_latest_quote_item(market=market, short_code=short_code, row=row))
    return results
