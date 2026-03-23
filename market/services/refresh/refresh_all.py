from __future__ import annotations

import logging

from django.utils import timezone

from accounts.services.investment_account_sync import sync_investment_accounts_after_market_refresh

from ..pricing.cache import UTC8
from .index import refresh_indices
from .usd_rates import refresh_usd_rates
from .watchlist import refresh_watchlist

logger = logging.getLogger(__name__)


def _sync_investment_accounts_after_refresh() -> None:
    try:
        sync_investment_accounts_after_market_refresh()
    except Exception:
        logger.exception("同步投资账户余额失败")


def refresh_all(*, force_full_fetch: bool = False) -> dict:
    now_local = timezone.now().astimezone(UTC8)

    market_data = refresh_watchlist(now_local=now_local, force_full_fetch=force_full_fetch)
    indices_data = refresh_indices(now_local=now_local, force_full_fetch=force_full_fetch)
    usd_baserate_data = refresh_usd_rates(now_local=now_local, market_data=market_data)
    _sync_investment_accounts_after_refresh()

    return {
        "market_data": market_data,
        "indices_data": indices_data,
        "usd_baserate_data": usd_baserate_data,
    }


__all__ = ["refresh_all"]
