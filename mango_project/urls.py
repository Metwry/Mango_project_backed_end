
from django.contrib import admin
from django.urls import path , include



urlpatterns = [
    path("admin/", admin.site.urls),
    path('api/', include('login.urls')),

    path("api/user/", include("accounts.urls")),
    path("api/user/", include("market.urls")),
    path("api/", include("investment.urls")),

]
