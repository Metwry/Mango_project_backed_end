from __future__ import annotations

import logging

from django.utils import timezone

from accounts.services.investment_account_sync import sync_investment_accounts_after_market_refresh

from ..quote_cache import UTC8
from .index_snapshot import pull_indices
from .usd_base_rates import pull_usd_base_rate
from .watchlist_snapshot import pull_market

logger = logging.getLogger(__name__)


def _sync_investment_accounts_after_refresh() -> None:
    try:
        sync_investment_accounts_after_market_refresh()
    except Exception:
        logger.exception("同步投资账户余额失败")


def pull_data() -> dict:
    now_local = timezone.now().astimezone(UTC8)

    market_data = pull_market(now_local=now_local)
    indices_data = pull_indices(now_local=now_local)
    usd_baserate_data = pull_usd_base_rate(now_local=now_local, market_data=market_data)
    _sync_investment_accounts_after_refresh()

    return {
        "market_data": market_data,
        "indices_data": indices_data,
        "usd_baserate_data": usd_baserate_data,
    }


__all__ = ["pull_data"]
