from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView


class SerializerPostAPIView(APIView):
    """封装“校验序列化器并执行保存动作”的通用 POST 基类视图。"""

    serializer_class = None
    success_status = status.HTTP_200_OK

    def get_serializer_class(self):
        if self.serializer_class is None:
            raise AssertionError("serializer_class must be set")
        return self.serializer_class

    def get_serializer_context(self):
        return {
            "request": self.request,
            "view": self,
        }

    def get_serializer(self, *args, **kwargs):
        serializer_class = self.get_serializer_class()
        kwargs.setdefault("context", self.get_serializer_context())
        return serializer_class(*args, **kwargs)

    def perform_action(self, serializer):
        return serializer.save()

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = self.perform_action(serializer)
        return Response(payload, status=self.success_status)
