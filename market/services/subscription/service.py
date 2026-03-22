from django.db import transaction

from ...models import UserInstrumentSubscription
from common.utils import normalize_code, resolve_short_code

SOURCE_POSITION = "position"
SOURCE_WATCHLIST = "watchlist"
SOURCE_TO_FIELD = {
    SOURCE_POSITION: "from_position",
    SOURCE_WATCHLIST: "from_watchlist",
}


# 设置用户与标的之间的订阅来源标记，并在无来源时自动删除订阅。
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


# 判断某个标的是否仍然存在任意用户订阅。
def has_any_subscription_for_instrument(*, instrument_id: int) -> bool:
    return UserInstrumentSubscription.objects.filter(instrument_id=instrument_id).exists()


# 返回全局订阅标的按市场聚合后的元数据。
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
        market_code = normalize_code(market)
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


# 返回当前用户自选订阅按市场分组的短代码集合。
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
        market_code = normalize_code(market)
        code = resolve_short_code(short_code, symbol)
        if not market_code or not code:
            continue
        grouped.setdefault(market_code, set()).add(code)
    return grouped
