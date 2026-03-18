from rest_framework.exceptions import ValidationError

from ..models import Instrument, UserInstrumentSubscription
from .subscription_service import (
    SOURCE_WATCHLIST,
    has_any_subscription_for_instrument,
    set_user_instrument_source,
)
from .quote_snapshot_service import (
    ensure_instrument_quote,
    get_snapshot_payload,
    pop_quote_by_code,
    safe_payload_data,
    save_orphan_quote,
    write_snapshot,
)
from shared.utils import normalize_code

# 将指定标的加入当前用户自选，并确保行情缓存可用。
def add_watchlist_symbol(*, user, symbol: str) -> dict:
    normalized_symbol = str(symbol or "").strip()
    instrument = (
        Instrument.objects
        .filter(symbol=normalized_symbol, is_active=True)
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
        "instrument": {
            "symbol": instrument.symbol,
            "short_code": instrument.short_code,
            "name": instrument.name,
            "market": normalize_code(instrument.market),
            "logo_url": instrument.logo_url or None,
            "logo_color": instrument.logo_color or None,
        },
        "quote_ready": quote_ready,
        "quote_source": quote_source,
    }


# 按 symbol 或 market + short_code 查找当前用户的自选订阅记录。
def _find_watchlist_subscriptions(*, user, symbol: str, market: str, short_code: str) -> list:
    if not symbol and not (market and short_code):
        raise ValidationError("请提供 symbol，或同时提供 market + short_code")

    qs = (
        UserInstrumentSubscription.objects
        .filter(user=user, from_watchlist=True)
        .select_related("instrument")
    )
    if symbol:
        qs = qs.filter(instrument__symbol=symbol)
    else:
        qs = qs.filter(
            instrument__market__iexact=market,
            instrument__short_code__iexact=short_code,
        )

    subscriptions = list(qs)
    if not subscriptions:
        raise ValidationError("该标的不在你的自选中")
    return subscriptions


# 将指定标的从当前用户自选移除，并在无人订阅时清理缓存行情。
def delete_watchlist_symbol(*, user, symbol: str = "", market: str = "", short_code: str = "") -> dict:
    symbol = str(symbol or "").strip()
    market = normalize_code(market)
    short_code = normalize_code(short_code)
    subscriptions = _find_watchlist_subscriptions(user=user, symbol=symbol, market=market, short_code=short_code)

    subscription_ids = [x.id for x in subscriptions]
    instruments = {}
    for sub in subscriptions:
        inst = sub.instrument
        instruments[inst.id] = inst

    payload = get_snapshot_payload()
    data = safe_payload_data(payload)
    updated_markets: set[str] = set()

    for inst in instruments.values():
        set_user_instrument_source(
            user=user,
            instrument=inst,
            source=SOURCE_WATCHLIST,
            enabled=False,
        )

        if has_any_subscription_for_instrument(instrument_id=inst.id):
            continue

        inst_market = normalize_code(inst.market)
        inst_short_code = normalize_code(inst.short_code)
        removed_quote = pop_quote_by_code(data, inst_market, inst_short_code)
        if removed_quote is not None:
            updated_markets.add(inst_market)
            save_orphan_quote(inst_market, inst_short_code, removed_quote)

    write_snapshot(payload, data, updated_markets)

    return {
        "deleted": len(subscription_ids),
        "updated_markets": sorted(updated_markets),
    }
