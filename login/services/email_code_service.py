import random

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

EMAIL_CODE_TTL_SECONDS = 10 * 60
EMAIL_CODE_CACHE_KEY_PREFIX = "login:register:email-code:"


def email_code_cache_key(email: str) -> str:
    return f"{EMAIL_CODE_CACHE_KEY_PREFIX}{email.strip().lower()}"


def ensure_email_not_registered(email: str) -> None:
    user_model = get_user_model()
    if user_model.objects.filter(email__iexact=email).exists():
        raise ValueError("该邮箱已注册")


def send_register_email_code(email: str) -> None:
    code = f"{random.randint(0, 999999):06d}"
    cache.set(
        email_code_cache_key(email),
        {"code_hash": make_password(code)},
        timeout=EMAIL_CODE_TTL_SECONDS,
    )

    html = render_to_string(
        "emails/verify_code.html",
        {
            "code": code,
            "minutes": EMAIL_CODE_TTL_SECONDS // 60,
        },
    )
    message = EmailMultiAlternatives(
        subject="Mango Finance 邮箱验证码",
        body=strip_tags(html),
        to=[email],
    )
    message.attach_alternative(html, "text/html")
    message.send(fail_silently=False)


def verify_register_email_code(email: str, code: str) -> None:
    payload = cache.get(email_code_cache_key(email))
    if not isinstance(payload, dict):
        raise ValueError("验证码已过期或不存在")

    code_hash = payload.get("code_hash")
    if not isinstance(code_hash, str) or not check_password(code, code_hash):
        raise ValueError("验证码错误")


def clear_register_email_code(email: str) -> None:
    cache.delete(email_code_cache_key(email))
