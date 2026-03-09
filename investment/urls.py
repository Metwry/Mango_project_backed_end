from django.urls import path

from .views import (
    InvestmentBuyView,
    InvestmentHistoryListView,
    InvestmentPositionDeleteView,
    InvestmentPositionListView,
    InvestmentSellView,
)

urlpatterns = [
    path("investment/buy/", InvestmentBuyView.as_view(), name="investment-buy"),
    path("investment/sell/", InvestmentSellView.as_view(), name="investment-sell"),
    path("investment/positions/", InvestmentPositionListView.as_view(), name="investment-positions"),
    path("investment/history/", InvestmentHistoryListView.as_view(), name="investment-history"),
    path(
        "investment/positions/<int:instrument_id>/",
        InvestmentPositionDeleteView.as_view(),
        name="investment-position-delete",
    ),
]
