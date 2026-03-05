from rest_framework import serializers
from shared.exceptions import LoginFailedError

from .services import (
    authenticate_email_password,
    ensure_email_registered,
    ensure_email_not_registered,
    verify_password_reset_email_code,
    verify_register_email_code,
)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate(self, attrs):
        identifier = (attrs.get("username") or attrs.get("email") or "").strip()
        password = attrs.get("password") or ""
        if not identifier or not password:
            raise serializers.ValidationError({"message": "用户名/邮箱和密码必填"})

        user = authenticate_email_password(
            self.context.get("request"),
            identifier=identifier,
            password=password,
        )
        if not user:
            raise LoginFailedError("邮箱/用户名或密码错误")

        attrs["user"] = user
        return attrs


class SendRegisterEmailCodeSerializer(serializers.Serializer):
    email = serializers.EmailField()

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

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

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

    def validate_email(self, value: str) -> str:
        email = value.strip().lower()
        try:
            ensure_email_registered(email)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        return email

    def validate(self, attrs):
        try:
            verify_password_reset_email_code(attrs["email"], attrs["code"])
        except ValueError as exc:
            raise serializers.ValidationError({"code": str(exc)})
        return attrs


class UpdateUsernameSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)

    def validate_username(self, value: str) -> str:
        username = (value or "").strip()
        if not username:
            raise serializers.ValidationError("用户名不能为空")
        return username
