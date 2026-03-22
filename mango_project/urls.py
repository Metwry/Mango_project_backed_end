from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularSwaggerView,
    SpectacularRedocView,
)

urlpatterns = [

    path("admin/", admin.site.urls),

    path("docs/swagger/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="swagger-ui"),
    path("docs/redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="redoc"),


    path("api/", include("login.urls")),
    path("api/user/", include("accounts.urls")),
    path("api/user/markets/", include("market.urls")),
    path("api/investment/", include("investment.urls")),
    path("api/snapshot/", include("snapshot.urls")),
]
