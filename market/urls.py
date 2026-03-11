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
    path("", MarketsView.as_view(), name="user-markets"),
    path("indices/", MarketIndexSnapshotView.as_view(), name="user-market-indices"),
    path("fx-rates/", MarketFxRatesView.as_view(), name="user-market-fx-rates"),
    path("search/", MarketInstrumentSearchView.as_view(), name="user-market-search"),
    path("quotes/latest/", MarketLatestQuoteBatchView.as_view(), name="user-market-latest-quotes"),
    path("watchlist/", MarketWatchlistAddView.as_view(), name="user-market-watchlist-add"),
]
