from django.db.models import Case, IntegerField, Q, Value, When
from rest_framework.exceptions import ValidationError

from common.utils.code_utils import normalize_code, resolve_short_code

from ...models import Instrument, UserInstrumentSubscription
from ..snapshot.quote_store import (
    build_quote_index,
    ensure_instrument_quote,
    get_snapshot_payload,
    pop_quote_by_code,
    safe_payload_data,
    safe_price_str,
    save_orphan_quote,
    write_snapshot,
)
from ..subscription.service import (
    SOURCE_WATCHLIST,
    has_any_subscription_for_instrument,
    set_user_instrument_source,
    user_watchlist_codes_by_market,
)


# 统一清洗行情行里的可空 logo 字段。
def _format_quote_row(row: dict) -> dict:
    normalized_row = dict(row)
    normalized_row["logo_url"] = normalized_row.get("logo_url") or None
    normalized_row["logo_color"] = normalized_row.get("logo_color") or None
    return normalized_row


# 统一构造最新价接口的返回项。
def _format_latest_quote_item(*, market: str, short_code: str, row: dict | None) -> dict:
    latest_price = safe_price_str(row.get("price")) if isinstance(row, dict) else None
    return {
        "market": market,
        "short_code": short_code,
        "latest_price": latest_price,
        "logo_url": (row.get("logo_url") or None) if isinstance(row, dict) else None,
        "logo_color": (row.get("logo_color") or None) if isinstance(row, dict) else None,
    }


# 统一构造自选添加接口里的标的信息返回结构。
def _format_watchlist_instrument(instrument) -> dict:
    return {
        "symbol": instrument.symbol,
        "short_code": instrument.short_code,
        "name": instrument.name,
        "market": instrument.market,
        "logo_url": instrument.logo_url,
        "logo_color": instrument.logo_color,
    }


# 从原始快照列表中过滤当前用户允许看到的标的。
def _filter_quotes(rows, allow_codes):
    if not isinstance(rows, list):
        return []

    filtered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = resolve_short_code(row.get("short_code"), row.get("symbol"))
        if code in allow_codes:
            filtered.append(_format_quote_row(row))
    return filtered


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
    payload = get_snapshot_payload()
    data = payload.get("data")
    market_data = data if isinstance(data, dict) else {}
    watchlist_codes = user_watchlist_codes_by_market(user)

    markets = []
    for market in sorted(watchlist_codes.keys()):
        allow_codes = watchlist_codes[market]
        raw_quotes = market_data.get(market, [])
        quotes = _filter_quotes(raw_quotes, allow_codes)
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
    payload = get_snapshot_payload()
    quote_index = build_quote_index(payload)

    results = []
    for item in items:
        market = item["market"]
        short_code = item["short_code"]
        row = quote_index.get((market, short_code))
        results.append(_format_latest_quote_item(market=market, short_code=short_code, row=row))
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
        "instrument": _format_watchlist_instrument(instrument),
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

    payload = get_snapshot_payload()
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

    write_snapshot(payload, data, updated_markets)

    return {
        "deleted": len(subscription_ids),
        "updated_markets": sorted(updated_markets),
    }

