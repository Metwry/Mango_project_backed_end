from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AccountViewSet, TransactionViewSet, TransferViewSet


router = DefaultRouter()
router.register(r"accounts", AccountViewSet, basename="accounts")
router.register(r"transactions", TransactionViewSet, basename="transaction")
router.register(r"transfers", TransferViewSet, basename="transfer")

urlpatterns = [
    path("", include(router.urls)),
]
