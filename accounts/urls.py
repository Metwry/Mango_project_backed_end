from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AccountViewSet, TransactionViewSet


router = DefaultRouter()
router.register(r"accounts", AccountViewSet, basename="accounts")
router.register(r"transactions", TransactionViewSet, basename="transaction")

urlpatterns = [
    path("", include(router.urls)),
]
