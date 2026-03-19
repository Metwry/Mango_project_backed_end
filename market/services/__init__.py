from .subscription_service import (
    SOURCE_POSITION,
    SOURCE_WATCHLIST,
    has_any_subscription_for_instrument,
    set_user_instrument_source,
)


def get_fx_rates(*args, **kwargs):
    from .fx_rate_service import get_fx_rates as impl
    return impl(*args, **kwargs)


def build_market_indices_snapshot(*args, **kwargs):
    from .index_quote_service import build_market_indices_snapshot as impl
    return impl(*args, **kwargs)


def search_instruments(*args, **kwargs):
    from .api_service import search_instruments as impl
    return impl(*args, **kwargs)


def build_latest_quotes(*args, **kwargs):
    from .api_service import build_latest_quotes as impl
    return impl(*args, **kwargs)


def build_user_markets_snapshot(*args, **kwargs):
    from .api_service import build_user_markets_snapshot as impl
    return impl(*args, **kwargs)


def ensure_instrument_quote(*args, **kwargs):
    from .quote_snapshot_service import ensure_instrument_quote as impl
    return impl(*args, **kwargs)


def sync_watchlist_snapshot(*args, **kwargs):
    from .snapshot_sync_service import sync_watchlist_snapshot as impl
    return impl(*args, **kwargs)


def add_watchlist_symbol(*args, **kwargs):
    from .api_service import add_watchlist_symbol as impl
    return impl(*args, **kwargs)


def delete_watchlist_symbol(*args, **kwargs):
    from .api_service import delete_watchlist_symbol as impl
    return impl(*args, **kwargs)

__all__ = [
    "get_fx_rates",
    "build_market_indices_snapshot",
    "search_instruments",
    "build_latest_quotes",
    "build_user_markets_snapshot",
    "ensure_instrument_quote",
    "sync_watchlist_snapshot",
    "SOURCE_POSITION",
    "SOURCE_WATCHLIST",
    "has_any_subscription_for_instrument",
    "set_user_instrument_source",
    "add_watchlist_symbol",
    "delete_watchlist_symbol",
]
