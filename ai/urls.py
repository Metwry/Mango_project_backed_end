from django.urls import path

from ai.views import AIChatView, ChatSessionDetailView, ChatSessionListView


urlpatterns = [
    path("chat/", AIChatView.as_view(), name="ai-chat"),
    path("chat/sessions/", ChatSessionListView.as_view(), name="ai-chat-session-list"),
    path("chat/sessions/<int:session_id>/", ChatSessionDetailView.as_view(), name="ai-chat-session-detail"),
]
