
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("login.urls")),
    path("api/user/", include("accounts.urls")),
    path("api/user/markets/", include("market.urls")),
    path("api/investment/", include("investment.urls")),
    path("api/snapshot/", include("snapshot.urls")),
]
