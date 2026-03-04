from django.urls import path

from .views import AccountSnapshotQueryView, PositionSnapshotQueryView

urlpatterns = [
    path("snapshot/accounts/", AccountSnapshotQueryView.as_view(), name="snapshot-accounts-query"),
    path("snapshot/positions/", PositionSnapshotQueryView.as_view(), name="snapshot-positions-query"),
]
