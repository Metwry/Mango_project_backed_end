from __future__ import annotations

from collections import defaultdict

from market.models import UserInstrumentSubscription
from shared.utils import normalize_code, resolve_short_code


# 返回全局订阅标的按市场聚合后的元数据。
def global_subscription_meta_by_market() -> dict[str, dict[str, dict]]:
    grouped: dict[str, dict[str, dict]] = defaultdict(dict)
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
        grouped[market_code][code] = {
            "short_code": short_code or code,
            "name": name or "",
            "symbol": symbol or "",
            "logo_url": logo_url or None,
            "logo_color": logo_color or None,
        }
    return dict(grouped)


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
