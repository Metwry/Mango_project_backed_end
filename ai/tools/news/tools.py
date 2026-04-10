from __future__ import annotations

import json
from functools import lru_cache
from zoneinfo import ZoneInfo

from django.utils import timezone
from langchain_core.tools import tool

from ai.rag.newsSummaryService import NewsSummaryQuery, NewsSummaryService


@lru_cache(maxsize=1)
def _news_summary_service() -> NewsSummaryService:
    return NewsSummaryService()


@tool
def get_current_time() -> str:
    """返回当前本地时间、日期和时区。涉及相对时间时优先调用。"""
    now = timezone.now().astimezone(ZoneInfo("Asia/Shanghai"))
    payload = {
        "current_datetime": now.isoformat(),
        "current_date": now.date().isoformat(),
        "timezone": "Asia/Shanghai",
        "weekday": now.strftime("%A"),
    }
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=NewsSummaryQuery)
def news_summarize(**kwargs) -> str:
    """根据用户问题检索财经新闻并返回结构化检索结果。"""
    return _news_summary_service().rag_summarize(NewsSummaryQuery(**kwargs))
