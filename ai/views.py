import json

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.models import ChatSession
from ai.serializers import (
    ChatRequestSerializer,
    ChatSessionDetailSerializer,
    ChatSessionListItemSerializer,
    ChatSessionRenameSerializer,
)
from ai.services.chat_service import stream_chat


def _format_sse(event: str, data) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


class AIChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query = serializer.validated_data["query"]
        session_id = serializer.validated_data.get("session_id")

        def event_stream():
            for item in stream_chat(user=request.user, query=query, session_id=session_id):
                yield _format_sse(item["event"], item["data"])

        response = StreamingHttpResponse(
            streaming_content=event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class ChatSessionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        sessions = ChatSession.objects.filter(user=request.user).order_by("-updated_at", "-id")
        serializer = ChatSessionListItemSerializer(sessions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ChatSessionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id: int, *args, **kwargs):
        session = get_object_or_404(ChatSession.objects.prefetch_related("messages"), id=session_id, user=request.user)
        serializer = ChatSessionDetailSerializer(session)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, session_id: int, *args, **kwargs):
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        serializer = ChatSessionRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session.title = serializer.validated_data["title"]
        session.save(update_fields=["title", "updated_at"])

        response_serializer = ChatSessionListItemSerializer(session)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, session_id: int, *args, **kwargs):
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
