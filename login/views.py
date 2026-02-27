from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = request.data.get('username')
        password = request.data.get('password')

        if not email or not password:
            return Response(
                {'detail': '邮箱和密码必填'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 这里用 email 作为 username 认证，因为我们创建用户时 username=email
        # djiago 验证函数，user为数据库查到的对象
        user = authenticate(request, username=email, password=password)

        if not user:
            return Response(
                {'detail': '邮箱或密码错误'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        # 使用 SimpleJWT 生成 token
        refresh = RefreshToken.for_user(user)

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        return Response(
            {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'username': user.username,
                }
            },
            status=status.HTTP_200_OK
        )




