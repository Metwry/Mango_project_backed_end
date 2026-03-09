from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    EmailRegisterSerializer,
    LoginSerializer,
    PasswordResetSerializer,
    SendPasswordResetEmailCodeSerializer,
    SendRegisterEmailCodeSerializer,
    UpdateUsernameSerializer,
)
from .services import (
    build_login_payload,
    register_user_by_email,
    reset_user_password_by_email,
    send_password_reset_email_code,
    send_register_email_code,
    update_username_for_user,
)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = build_login_payload(serializer.validated_data["user"])
        return Response(payload, status=status.HTTP_200_OK)


class SendRegisterEmailCodeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        serializer = SendRegisterEmailCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        send_register_email_code(serializer.validated_data["email"])
        return Response({"message": "验证码已发送"}, status=status.HTTP_200_OK)


class EmailRegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        serializer = EmailRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = register_user_by_email(
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
            )
        except ValueError:
            raise ValidationError({"email": "该邮箱已注册"})
        return Response(payload, status=status.HTTP_201_CREATED)


class SendPasswordResetEmailCodeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        serializer = SendPasswordResetEmailCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        send_password_reset_email_code(serializer.validated_data["email"])
        return Response({"message": "验证码已发送"}, status=status.HTTP_200_OK)


class PasswordResetView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reset_user_password_by_email(
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
            )
        except ValueError as exc:
            raise ValidationError({"message": str(exc)})
        return Response({"message": "密码重置成功"}, status=status.HTTP_200_OK)


class UpdateUsernameView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, *args, **kwargs):
        serializer = UpdateUsernameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user_payload = update_username_for_user(
                user=request.user,
                username=serializer.validated_data["username"],
            )
        except ValueError as exc:
            raise ValidationError({"message": str(exc)})
        return Response(
            {"message": "用户名修改成功", "user": user_payload},
            status=status.HTTP_200_OK,
        )
