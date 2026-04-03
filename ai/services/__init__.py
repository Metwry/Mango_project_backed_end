from __future__ import annotations

from importlib import import_module
from typing import Any


__all__ = [
    "AnalysisResult",
    "AnalysisService",
    "EmbeddingService",
    "NewsAnalysisService",
    "NewsQueryPlan",
    "QueryUnderstandingService",
]

_EXPORTS = {
    "AnalysisResult": ("ai.services.content_analysis", "AnalysisResult"),
    "AnalysisService": ("ai.services.content_analysis", "AnalysisService"),
    "EmbeddingService": ("ai.services.content_embedding", "EmbeddingService"),
    "NewsAnalysisService": ("ai.services.news_summary", "NewsAnalysisService"),
    "NewsQueryPlan": ("ai.services.query_rewrite", "NewsQueryPlan"),
    "QueryUnderstandingService": ("ai.services.query_rewrite", "QueryUnderstandingService"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attr_name)
