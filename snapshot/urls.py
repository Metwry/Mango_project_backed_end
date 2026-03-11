from django.urls import path

from .views import AccountSnapshotQueryView, PositionSnapshotQueryView

urlpatterns = [
    path("accounts/", AccountSnapshotQueryView.as_view(), name="snapshot-accounts-query"),
    path("positions/", PositionSnapshotQueryView.as_view(), name="snapshot-positions-query"),
]
