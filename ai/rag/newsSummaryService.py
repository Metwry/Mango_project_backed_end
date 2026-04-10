from __future__ import annotations

import json
from datetime import datetime

from django.utils import timezone
from pydantic import BaseModel, Field

from news.service.news_search import NewsSearchResult, NewsSearchService



class NewsSummaryQuery(BaseModel):
    query: str = Field(description="用户的问题")
    response_mode: str = Field(description="回答模式: overview 或 detail")
    top_k: int | None = Field(default=None, description="检索条数")
    published_from: datetime | None = Field(default=None, description="开始时间")
    published_to: datetime | None = Field(default=None, description="结束时间")


class NewsSummaryService:
    EMPTY_RESULT_TEXT = "未检索到足够相关的财经新闻，暂时无法给出可靠回答。"

    def __init__(self) -> None:
        self.search_service = NewsSearchService()

    def rag_summarize(self, request: NewsSummaryQuery) -> str:
        published_from = self._normalize_datetime(request.published_from)
        published_to = self._normalize_datetime(request.published_to)
        result: NewsSearchResult = self.search_service.search(
            query=request.query,
            response_mode=request.response_mode,
            top_k=request.top_k,
            published_from=published_from,
            published_to=published_to,
        )
        payload = {
            "query": request.query,
            "response_mode": request.response_mode,
            "hit_count": result.hit_count,
            "context": result.context,
        }
        if result.hit_count == 0:
            payload["message"] = self.EMPTY_RESULT_TEXT
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value


if __name__ == '__main__':
    rag = NewsSummaryService()
    print(rag.rag_summarize(NewsSummaryQuery(query="最近有什么新闻", response_mode="overview")))
