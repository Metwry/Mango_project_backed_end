from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AccountSummaryView, AccountViewSet, TransactionViewSet


router = DefaultRouter()
router.register(r"accounts", AccountViewSet, basename="accounts")
router.register(r"transactions", TransactionViewSet, basename="transaction")

urlpatterns = [
    path("accounts/summary/", AccountSummaryView.as_view(), name="accounts-summary"),
    path("", include(router.urls)),
]
