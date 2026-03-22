from django.db import IntegrityError
from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from .email_code_service import clear_password_reset_email_code, clear_register_email_code

# ed 按用户名或邮箱验证用户密码并返回认证成功的用户对象。
def authenticate_email_password(request, *, username: str, password: str):
    user = authenticate(request, username=username, password=password)
    if user:
        return user

    email_user = get_user_model().objects.filter(email__iexact=username).only("username").first()
    if email_user is None:
        return None

    return authenticate(request, username=email_user.username, password=password)


# ed 生成登录成功后的令牌和用户摘要信息。
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


# ed 使用邮箱注册新用户并清理注册验证码缓存。
def register_user_by_email(*, email: str, password: str):
    try:
        user = get_user_model().objects.create_user(
            username=email,
            email=email,
            password=password,
        )
    except IntegrityError as exc:
        raise ValueError("该邮箱已注册") from exc
    clear_register_email_code(email)
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
    }


# 通过邮箱重置用户密码并清理验证码缓存。
def reset_user_password_by_email(*, email: str, password: str) -> None:

    user = get_user_model().objects.filter(email__iexact=email).first()
    if user is None:
        raise ValueError("该邮箱未注册")
    user.set_password(password)
    user.save(update_fields=["password"])
    clear_password_reset_email_code(email)


# 修改当前用户用户名并返回最新用户摘要。
def update_username_for_user(*, user, username: str) -> dict:
    next_username = (username or "").strip()
    if not next_username:
        raise ValueError("用户名不能为空")

    if get_user_model().objects.filter(username__iexact=next_username).exclude(id=user.id).exists():
        raise ValueError("用户名已存在")

    user.username = next_username
    user.save(update_fields=["username"])
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
    }
