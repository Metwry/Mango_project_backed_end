from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AccountViewSet,
    TransactionViewSet,
    MarketsView,
    MarketFxRatesView,
    MarketInstrumentSearchView,
    MarketWatchlistAddView,
)




router = DefaultRouter()
router.register(r"accounts", AccountViewSet, basename="accounts")
router.register(r"transactions", TransactionViewSet, basename="transaction")

urlpatterns = [
    path("", include(router.urls)),
    path("markets/", MarketsView.as_view(), name="user-markets"),
    path("markets/fx-rates/", MarketFxRatesView.as_view(), name="user-market-fx-rates"),
    path("markets/search/", MarketInstrumentSearchView.as_view(), name="user-market-search"),
    path("markets/watchlist/", MarketWatchlistAddView.as_view(), name="user-market-watchlist-add"),
]
