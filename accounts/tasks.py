from celery import shared_task

from market.services.cache_keys import (
    FX_REFRESH_INTERVAL,
    USD_EXCHANGE_RATES_KEY,
    UTC8,
    WATCHLIST_QUOTES_KEY,
    WATCHLIST_QUOTES_MARKET_KEY_PREFIX,
)
from market.services.snapshot_sync_service import sync_watchlist_snapshot

@shared_task
def task_pull_watchlist_quotes():
    return sync_watchlist_snapshot()
