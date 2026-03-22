from rest_framework import serializers
from common.exceptions import LoginFailedError

from .services.auth_service import authenticate_email_password
from .services.email_code_service import (
    ensure_email_registered,
    ensure_email_not_registered,
    verify_password_reset_email_code,
    verify_register_email_code,
)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)

    # 校验登录标识与密码，并解析出对应用户对象。
    def validate(self, attrs):
        username = attrs.get("username")
        password = attrs.get("password")
        if not username or not password:
            raise serializers.ValidationError({"message": "用户名和密码必填"})

        user = authenticate_email_password(
            self.context.get("request"),
            username=username,
            password=password,
        )
        if not user:
            raise LoginFailedError("邮箱/用户名或密码错误")

        attrs["user"] = user
        return attrs


class SendRegisterEmailCodeSerializer(serializers.Serializer):
    email = serializers.EmailField()

    # ed 校验注册邮箱格式并确认该邮箱尚未注册。
    def validate_email(self, value: str) -> str:
        email = value.strip().lower()
        try:
            ensure_email_not_registered(email)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        return email


class EmailRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6, max_length=128)
    code = serializers.RegexField(regex=r"^\d{6}$")

    # 标准化注册邮箱为小写格式。
    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    # 校验邮箱注册请求，确保邮箱未被占用且验证码有效。
    def validate(self, attrs):
        email = attrs["email"]
        code = attrs["code"]

        try:
            ensure_email_not_registered(email)
        except ValueError:
            raise serializers.ValidationError({"email": "该邮箱已注册"})

        try:
            verify_register_email_code(email, code)
        except ValueError as exc:
            raise serializers.ValidationError({"code": str(exc)})

        return attrs


class SendPasswordResetEmailCodeSerializer(serializers.Serializer):
    email = serializers.EmailField()

    # ed校验找回密码邮箱必须已注册。
    def validate_email(self, value: str) -> str:
        email = value.strip().lower()
        try:
            ensure_email_registered(email)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        return email


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6, max_length=128)
    code = serializers.RegexField(regex=r"^\d{6}$")

    # 标准化重置密码邮箱并校验其已注册。
    def validate_email(self, value: str) -> str:
        email = value.strip().lower()
        try:
            ensure_email_registered(email)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        return email

    # 校验密码重置验证码是否正确。
    def validate(self, attrs):
        try:
            verify_password_reset_email_code(attrs["email"], attrs["code"])
        except ValueError as exc:
            raise serializers.ValidationError({"code": str(exc)})
        return attrs


class UpdateUsernameSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)

    # 校验并清理用户提交的新用户名。
    def validate_username(self, value: str) -> str:
        username = (value or "").strip()
        if not username:
            raise serializers.ValidationError("用户名不能为空")
        return username
