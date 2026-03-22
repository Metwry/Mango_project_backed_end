import random

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

EMAIL_CODE_TTL_SECONDS = 10 * 60
EMAIL_CODE_CACHE_KEY_PREFIX = "login:register:email-code:"
PASSWORD_RESET_CODE_CACHE_KEY_PREFIX = "login:password-reset:email-code:"


# 生成注册邮箱验证码缓存键。
def email_code_cache_key(email: str) -> str:
    return f"{EMAIL_CODE_CACHE_KEY_PREFIX}{email.strip().lower()}"


# 生成重置密码验证码缓存键。
def password_reset_code_cache_key(email: str) -> str:
    return f"{PASSWORD_RESET_CODE_CACHE_KEY_PREFIX}{email.strip().lower()}"


# 校验邮箱尚未注册，用于注册流程。
def ensure_email_not_registered(email: str) -> None:
    if get_user_model().objects.filter(email__iexact=email).exists():
        raise ValueError("该邮箱已注册")


# 校验邮箱已经注册，用于找回密码流程。
def ensure_email_registered(email: str) -> None:
    if not get_user_model().objects.filter(email__iexact=email).exists():
        raise ValueError("该邮箱未注册")


# 生成验证码、写入缓存并发送邮件模板。
def _send_email_code(*, email: str, subject: str, cache_key: str) -> None:
    code = f"{random.randint(0, 999999):06d}"
    cache.set(
        cache_key,
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
        subject=subject,
        body=strip_tags(html),
        to=[email],
    )
    message.attach_alternative(html, "text/html")
    message.send(fail_silently=False)


# 发送注册邮箱验证码。
def send_register_email_code(email: str) -> None:
    _send_email_code(
        email=email,
        subject="Mango Finance 邮箱验证码",
        cache_key=email_code_cache_key(email),
    )


# 发送密码重置邮箱验证码。
def send_password_reset_email_code(email: str) -> None:
    _send_email_code(
        email=email,
        subject="Mango Finance 重置密码验证码",
        cache_key=password_reset_code_cache_key(email),
    )


# 校验缓存中的邮箱验证码是否正确。
def _verify_email_code(*, cache_key: str, code: str) -> None:
    payload = cache.get(cache_key)
    if not isinstance(payload, dict):
        raise ValueError("验证码已过期或不存在")

    code_hash = payload.get("code_hash")
    if not isinstance(code_hash, str) or not check_password(code, code_hash):
        raise ValueError("验证码错误")


# 校验注册流程使用的邮箱验证码。
def verify_register_email_code(email: str, code: str) -> None:
    _verify_email_code(cache_key=email_code_cache_key(email), code=code)


# 校验重置密码流程使用的邮箱验证码。
def verify_password_reset_email_code(email: str, code: str) -> None:
    _verify_email_code(cache_key=password_reset_code_cache_key(email), code=code)

# 清理注册流程验证码缓存。
def clear_register_email_code(email: str) -> None:
    cache.delete(email_code_cache_key(email))


# 清理重置密码流程验证码缓存。
def clear_password_reset_email_code(email: str) -> None:
    cache.delete(password_reset_code_cache_key(email))
