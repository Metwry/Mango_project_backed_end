from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    EmailRegisterSerializer,
    LoginSerializer,
    SendRegisterEmailCodeSerializer,
)
from .services import (
    build_login_payload,
    register_user_by_email,
    send_register_email_code,
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
