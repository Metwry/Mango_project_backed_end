from django.urls import path

from .views import (
    InvestmentBuyView,
    InvestmentHistoryListView,
    InvestmentPositionDeleteView,
    InvestmentPositionListView,
    InvestmentSellView,
)

urlpatterns = [
    path("buy/", InvestmentBuyView.as_view(), name="investment-buy"),
    path("sell/", InvestmentSellView.as_view(), name="investment-sell"),
    path("positions/", InvestmentPositionListView.as_view(), name="investment-positions"),
    path("history/", InvestmentHistoryListView.as_view(), name="investment-history"),
    path(
        "positions/<int:instrument_id>/",
        InvestmentPositionDeleteView.as_view(),
        name="investment-position-delete",
    ),
]
