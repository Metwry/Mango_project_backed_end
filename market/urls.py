from django.urls import path

from .views import (
    MarketFxRatesView,
    MarketIndexSnapshotView,
    MarketInstrumentSearchView,
    MarketLatestQuoteBatchView,
    MarketsView,
    MarketWatchlistAddView,
)

urlpatterns = [
    path("markets/", MarketsView.as_view(), name="user-markets"),
    path("markets/indices/", MarketIndexSnapshotView.as_view(), name="user-market-indices"),
    path("markets/fx-rates/", MarketFxRatesView.as_view(), name="user-market-fx-rates"),
    path("markets/search/", MarketInstrumentSearchView.as_view(), name="user-market-search"),
    path("markets/quotes/latest/", MarketLatestQuoteBatchView.as_view(), name="user-market-latest-quotes"),
    path("markets/watchlist/", MarketWatchlistAddView.as_view(), name="user-market-watchlist-add"),
]
