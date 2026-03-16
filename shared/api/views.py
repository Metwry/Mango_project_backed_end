from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView


class SerializerPostAPIView(APIView):
    """封装“校验序列化器并执行保存动作”的通用 POST 基类视图。"""

    serializer_class = None
    success_status = status.HTTP_200_OK

    # 返回当前视图绑定的序列化器类，未配置时直接报错。
    def get_serializer_class(self):
        if self.serializer_class is None:
            raise AssertionError("serializer_class must be set")
        return self.serializer_class

    # 构造序列化器上下文，向序列化器传递 request 和当前视图。
    def get_serializer_context(self):
        return {
            "request": self.request,
            "view": self,
        }

    # 使用默认上下文实例化序列化器。
    def get_serializer(self, *args, **kwargs):
        serializer_class = self.get_serializer_class()
        kwargs.setdefault("context", self.get_serializer_context())
        return serializer_class(*args, **kwargs)

    # 执行默认业务动作，默认直接调用序列化器保存。
    def perform_action(self, serializer):
        return serializer.save()

    # 处理标准 POST 请求：校验序列化器、执行动作并返回响应。
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = self.perform_action(serializer)
        return Response(payload, status=self.success_status)
