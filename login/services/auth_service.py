from django.db import IntegrityError
from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from .email_code_service import clear_register_email_code

def authenticate_email_password(request, *, email: str, password: str):
    user = authenticate(request, username=email, password=password)
    if not user:
        return None
    return user


def build_login_payload(user) -> dict:
    refresh = RefreshToken.for_user(user)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
        },
    }


def create_user_by_email(*, email: str, password: str):
    user_model = get_user_model()
    return user_model.objects.create_user(
        username=email,
        email=email,
        password=password,
    )


def register_user_by_email(*, email: str, password: str):
    try:
        user = create_user_by_email(email=email, password=password)
    except IntegrityError as exc:
        raise ValueError("该邮箱已注册") from exc
    clear_register_email_code(email)
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
    }
