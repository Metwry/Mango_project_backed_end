from django.urls import path
from .views import EmailRegisterView, LoginView, SendRegisterEmailCodeView
from rest_framework_simplejwt.views import TokenRefreshView, TokenObtainPairView


urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path("register/email/code/", SendRegisterEmailCodeView.as_view(), name="register-email-code"),
    path("register/email/", EmailRegisterView.as_view(), name="register-email"),
    # path('login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

]


