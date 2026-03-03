from django.db import IntegrityError
from rest_framework import serializers
from shared.exceptions import LoginFailedError

from .services import (
    authenticate_email_password,
    build_login_payload,
    clear_register_email_code,
    create_user_by_email,
    ensure_email_not_registered,
    send_register_email_code,
    verify_register_email_code,
)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate(self, attrs):
        email = (attrs.get("username") or "").strip().lower()
        password = attrs.get("password") or ""
        if not email or not password:
            raise serializers.ValidationError({"detail": "邮箱和密码必填"})

        user = authenticate_email_password(self.context.get("request"), email=email, password=password)
        if not user:
            raise LoginFailedError("邮箱/用户名或密码错误")

        attrs["user"] = user
        return attrs

    def create(self, validated_data):
        return build_login_payload(validated_data["user"])


class SendRegisterEmailCodeSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        email = value.strip().lower()
        try:
            ensure_email_not_registered(email)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        return email

    def create(self, validated_data):
        send_register_email_code(validated_data["email"])
        return {"detail": "验证码已发送"}


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

    def create(self, validated_data):
        email = validated_data["email"]
        password = validated_data["password"]
        try:
            user = create_user_by_email(email=email, password=password)
        except IntegrityError:
            raise serializers.ValidationError({"email": "该邮箱已注册"})
        clear_register_email_code(email)

        return {
            "id": user.id,
            "email": user.email,
            "username": user.username,
        }
