from django.urls import path

from .views import (
    InvestmentBuyView,
    InvestmentHistoryListView,
    InvestmentPositionListView,
    InvestmentSellView,
)

urlpatterns = [
    path("buy/", InvestmentBuyView.as_view(), name="investment-buy"),
    path("sell/", InvestmentSellView.as_view(), name="investment-sell"),
    path("positions/", InvestmentPositionListView.as_view(), name="investment-positions"),
    path("history/", InvestmentHistoryListView.as_view(), name="investment-history"),
]
