from rest_framework import serializers

from ai.models import ChatMessage, ChatSession


class ChatRequestSerializer(serializers.Serializer):
    query = serializers.CharField(allow_blank=False, trim_whitespace=True)
    session_id = serializers.IntegerField(required=False, min_value=1)


class ChatSessionListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ["id", "title", "updated_at"]


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["role", "content", "sequence"]


class ChatSessionDetailSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)

    class Meta:
        model = ChatSession
        fields = ["id", "title", "updated_at", "messages"]


class ChatSessionRenameSerializer(serializers.Serializer):
    title = serializers.CharField(allow_blank=False, trim_whitespace=True, max_length=200)
