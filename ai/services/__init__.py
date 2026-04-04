from __future__ import annotations

from importlib import import_module
from typing import Any


__all__ = [
    "AnalysisResult",
    "AnalysisService",
    "append_assistant_message",
    "append_user_message",
    "build_session_messages",
    "EmbeddingService",
    "get_or_create_session",
    "NewsAnalysisService",
    "NewsQueryPlan",
    "next_message_sequence",
    "QueryUnderstandingService",
    "run_chat",
    "stream_chat",
]

_EXPORTS = {
    "AnalysisResult": ("ai.services.content_analysis", "AnalysisResult"),
    "AnalysisService": ("ai.services.content_analysis", "AnalysisService"),
    "append_assistant_message": ("ai.services.chat_service", "append_assistant_message"),
    "append_user_message": ("ai.services.chat_service", "append_user_message"),
    "build_session_messages": ("ai.services.chat_service", "build_session_messages"),
    "EmbeddingService": ("ai.services.content_embedding", "EmbeddingService"),
    "get_or_create_session": ("ai.services.chat_service", "get_or_create_session"),
    "NewsAnalysisService": ("ai.services.news_summary", "NewsAnalysisService"),
    "NewsQueryPlan": ("ai.services.query_rewrite", "NewsQueryPlan"),
    "next_message_sequence": ("ai.services.chat_service", "next_message_sequence"),
    "QueryUnderstandingService": ("ai.services.query_rewrite", "QueryUnderstandingService"),
    "run_chat": ("ai.services.chat_service", "run_chat"),
    "stream_chat": ("ai.services.chat_service", "stream_chat"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attr_name)
