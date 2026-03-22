from django.db.models import Case, IntegerField, Q, Value, When
from rest_framework.exceptions import ValidationError

from common.utils import normalize_code, safe_payload_data

from ...models import Instrument, UserInstrumentSubscription
from ..data.quote_cache import (
    build_quote_index,
    ensure_instrument_quote,
    get_market_data_payload,
    pop_quote_by_code,
    save_orphan_quote,
    write_market_data,
)
from ..data.utils import (
    filter_snapshot_quotes,
    format_latest_quote_item,
    format_watchlist_instrument,
)
from ..subscription.service import (
    SOURCE_WATCHLIST,
    has_any_subscription_for_instrument,
    set_user_instrument_source,
    user_watchlist_codes_by_market,
)


# 根据代码或名称搜索当前可交易的标的列表。
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


# 为当前用户构建按市场分组的自选行情快照。
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


# 从缓存快照中批量提取指定标的的最新价格摘要。
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


# 将指定标的加入当前用户自选，并确保行情缓存可用。
def add_watchlist_symbol(*, user, symbol: str) -> dict:
    instrument = (
        Instrument.objects
        .filter(symbol=symbol, is_active=True)
        .only("id", "symbol", "short_code", "name", "market", "asset_class", "logo_url", "logo_color")
        .first()
    )
    if instrument is None:
        raise ValidationError({"symbol": "未找到可用股票代码"})
    if instrument.asset_class == Instrument.AssetClass.INDEX:
        raise ValidationError({"symbol": "指数暂不支持加入自选，请使用指数行情接口。"})

    existing_subscription = (
        UserInstrumentSubscription.objects
        .filter(user=user, instrument=instrument)
        .only("id", "from_watchlist")
        .first()
    )
    created = existing_subscription is None or not existing_subscription.from_watchlist
    set_user_instrument_source(
        user=user,
        instrument=instrument,
        source=SOURCE_WATCHLIST,
        enabled=True,
    )
    subscription = UserInstrumentSubscription.objects.get(user=user, instrument=instrument)
    quote_ready, quote_source = ensure_instrument_quote(instrument, fetch_missing=True, use_orphan=True)

    return {
        "created": created,
        "watchlist_item_id": subscription.id,
        "instrument": format_watchlist_instrument(instrument),
        "quote_ready": quote_ready,
        "quote_source": quote_source,
    }


# 按 market + short_code 查找当前用户的自选订阅记录。
def _find_watchlist_subscriptions(*, user, market: str, short_code: str) -> list:
    subscriptions = list(
        UserInstrumentSubscription.objects
        .filter(user=user, from_watchlist=True)
        .select_related("instrument")
        .filter(
            instrument__market__iexact=market,
            instrument__short_code__iexact=short_code,
        )
    )
    if not subscriptions:
        raise ValidationError("该标的不在你的自选中")
    return subscriptions


# 将指定标的从当前用户自选移除，并在无人订阅时清理缓存行情。
def delete_watchlist_symbol(*, user, market: str, short_code: str) -> dict:
    market = normalize_code(market)
    short_code = normalize_code(short_code)
    subscriptions = _find_watchlist_subscriptions(user=user, market=market, short_code=short_code)

    subscription_ids = [item.id for item in subscriptions]
    instruments = {}
    for subscription in subscriptions:
        instrument = subscription.instrument
        instruments[instrument.id] = instrument

    payload = get_market_data_payload()
    data = safe_payload_data(payload)
    updated_markets: set[str] = set()

    for instrument in instruments.values():
        set_user_instrument_source(
            user=user,
            instrument=instrument,
            source=SOURCE_WATCHLIST,
            enabled=False,
        )

        if has_any_subscription_for_instrument(instrument_id=instrument.id):
            continue

        inst_market = normalize_code(instrument.market)
        inst_short_code = normalize_code(instrument.short_code)
        removed_quote = pop_quote_by_code(data, inst_market, inst_short_code)
        if removed_quote is not None:
            updated_markets.add(inst_market)
            save_orphan_quote(inst_market, inst_short_code, removed_quote)

    write_market_data(payload, data, updated_markets)

    return {
        "deleted": len(subscription_ids),
        "updated_markets": sorted(updated_markets),
    }

