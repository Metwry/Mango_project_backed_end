from django.urls import path
from .views import (
    EmailRegisterView,
    LoginView,
    PasswordResetView,
    SendPasswordResetEmailCodeView,
    SendRegisterEmailCodeView,
    UpdateUsernameView,
)
from rest_framework_simplejwt.views import TokenRefreshView, TokenObtainPairView


urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path("register/email/code/", SendRegisterEmailCodeView.as_view(), name="register-email-code"),
    path("register/email/", EmailRegisterView.as_view(), name="register-email"),
    path("password/reset/code/", SendPasswordResetEmailCodeView.as_view(), name="password-reset-code"),
    path("password/reset/", PasswordResetView.as_view(), name="password-reset"),
    path("user/profile/username/", UpdateUsernameView.as_view(), name="user-profile-username-update"),
    # path('login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

]


