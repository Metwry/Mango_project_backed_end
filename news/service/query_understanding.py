from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from ai.services import AnalysisService


@dataclass(slots=True)
class NewsQueryPlan:
    raw_query: str
    semantic_query: str
    published_from: datetime | None
    published_to: datetime | None
    response_mode: str


class QueryUnderstandingService:
    def __init__(self) -> None:
        self.analysis_service = AnalysisService()

    def understand(
        self,
        *,
        query: str,
        timezone_name: str | None = None,
        now: datetime | None = None,
        config_overrides: dict | None = None,
    ) -> NewsQueryPlan:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query 不能为空")

        tz_name = timezone_name or timezone.get_current_timezone_name()
        tzinfo = ZoneInfo(tz_name)
        current_time = now or timezone.localtime(timezone.now(), tzinfo)
        if timezone.is_naive(current_time):
            current_time = timezone.make_aware(current_time, tzinfo)

        try:
            result = self.analysis_service.analyze(
                task_name="news_query_understanding",
                variables={
                    "query": normalized_query,
                    "now": current_time.isoformat(),
                    "timezone": tz_name,
                },
                config_overrides=config_overrides,
            )
            return self._parse_plan(normalized_query, result.data, tzinfo)
        except Exception:
            return NewsQueryPlan(
                raw_query=normalized_query,
                semantic_query=normalized_query,
                published_from=None,
                published_to=None,
                response_mode="overview",
            )

    @staticmethod
    def _parse_plan(
        raw_query: str,
        data: dict,
        tzinfo: ZoneInfo,
    ) -> NewsQueryPlan:
        semantic_query = str(data.get("semantic_query", "")).strip() or raw_query
        published_from = QueryUnderstandingService._parse_datetime(
            str(data.get("published_from", "")).strip(),
            tzinfo,
        )
        published_to = QueryUnderstandingService._parse_datetime(
            str(data.get("published_to", "")).strip(),
            tzinfo,
        )
        response_mode = str(data.get("response_mode", "overview")).strip().lower()
        if response_mode not in {"overview", "detail"}:
            response_mode = "overview"
        if published_from and published_to and published_from > published_to:
            published_from, published_to = published_to, published_from
        return NewsQueryPlan(
            raw_query=raw_query,
            semantic_query=semantic_query,
            published_from=published_from,
            published_to=published_to,
            response_mode=response_mode,
        )

    @staticmethod
    def _parse_datetime(value: str, tzinfo: ZoneInfo) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        if timezone.is_naive(parsed):
            return timezone.make_aware(parsed, tzinfo)
        return parsed
