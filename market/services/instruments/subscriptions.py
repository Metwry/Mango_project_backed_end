from django.db import transaction
from rest_framework.exceptions import ValidationError

from common.normalize import normalize_code, resolve_short_code
from common.utils import safe_payload_data

from ...models import Instrument, UserInstrumentSubscription
from ..pricing.cache import (
    ensure_instrument_quote,
    get_market_data_payload,
    pop_quote_by_code,
    write_market_data,
)
from ..pricing.utils import format_watchlist_instrument

SOURCE_POSITION = "position"
SOURCE_WATCHLIST = "watchlist"
SOURCE_TO_FIELD = {
    SOURCE_POSITION: "from_position",
    SOURCE_WATCHLIST: "from_watchlist",
}


# 为用户和标的维护订阅来源状态。
def set_user_instrument_source(*, user, instrument, source: str, enabled: bool) -> UserInstrumentSubscription | None:
    field_name = SOURCE_TO_FIELD.get(source)
    if field_name is None:
        raise ValueError(f"unknown source: {source}")

    with transaction.atomic():
        subscription = (
            UserInstrumentSubscription.objects
            .select_for_update()
            .filter(user=user, instrument=instrument)
            .first()
        )

        if subscription is None:
            if not enabled:
                return None

            payload = {
                "from_position": source == SOURCE_POSITION,
                "from_watchlist": source == SOURCE_WATCHLIST,
            }
            return UserInstrumentSubscription.objects.create(
                user=user,
                instrument=instrument,
                **payload,
            )

        setattr(subscription, field_name, bool(enabled))
        if not subscription.from_position and not subscription.from_watchlist:
            subscription.delete()
            return None

        subscription.save(update_fields=[field_name, "updated_at"])
        return subscription


# 判断指定标的是否仍被任意用户订阅。
def has_any_subscription_for_instrument(*, instrument_id: int) -> bool:
    return UserInstrumentSubscription.objects.filter(instrument_id=instrument_id).exists()


# 构建按市场分组的全局订阅标的元数据。
def global_subscription_meta_by_market() -> dict[str, dict[str, dict]]:
    grouped: dict[str, dict[str, dict]] = {}
    rows = (
        UserInstrumentSubscription.objects
        .filter(instrument__is_active=True)
        .values_list(
            "instrument__symbol",
            "instrument__short_code",
            "instrument__name",
            "instrument__market",
            "instrument__logo_url",
            "instrument__logo_color",
        )
        .distinct()
    )
    for symbol, short_code, name, market, logo_url, logo_color in rows:
        market_code = market
        code = resolve_short_code(short_code, symbol)
        if not market_code or not code:
            continue
        grouped.setdefault(market_code, {})[code] = {
            "short_code": short_code or code,
            "name": name or "",
            "symbol": symbol or "",
            "logo_url": logo_url or None,
            "logo_color": logo_color or None,
        }
    return grouped


# 返回当前用户自选按市场分组的代码集合。
def user_watchlist_codes_by_market(user) -> dict[str, set[str]]:
    if not user or not getattr(user, "is_authenticated", False):
        return {}

    grouped: dict[str, set[str]] = {}
    rows = (
        UserInstrumentSubscription.objects
        .filter(user=user, from_watchlist=True)
        .values_list("instrument__market", "instrument__short_code", "instrument__symbol")
    )
    for market, short_code, symbol in rows:
        market_code = market
        code = resolve_short_code(short_code, symbol)
        if not market_code or not code:
            continue
        grouped.setdefault(market_code, set()).add(code)
    return grouped


# 将指定标的加入用户自选并尝试补齐行情。
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
    quote_ready, quote_source = ensure_instrument_quote(instrument, fetch_missing=True)

    return {
        "created": created,
        "watchlist_item_id": subscription.id,
        "instrument": format_watchlist_instrument(instrument),
        "quote_ready": quote_ready,
        "quote_source": quote_source,
    }


# 查找用户在自选中对应市场和代码的订阅记录。
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


# 将指定标的从用户自选中移除并同步缓存。
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

        inst_market = instrument.market
        inst_short_code = instrument.short_code
        removed_quote = pop_quote_by_code(data, inst_market, inst_short_code)
        if removed_quote is not None:
            updated_markets.add(inst_market)

    write_market_data(payload, data, updated_markets)

    return {
        "deleted": len(subscription_ids),
        "updated_markets": sorted(updated_markets),
    }
