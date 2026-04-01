from __future__ import annotations

from celery import shared_task
from django.db.models import Exists, OuterRef

from ai.models import AIAnalysis
from ai.services import NewsAnalysisService
from news.models import NewsArticle


def analyze_pending_news_articles(*, limit: int = 1, config_overrides: dict | None = None) -> dict[str, int]:
    service = NewsAnalysisService()
    pending_articles = list(
        NewsArticle.objects.annotate(
            has_analysis=Exists(
                AIAnalysis.objects.filter(
                    source_type=AIAnalysis.SourceType.NEWS_ARTICLE,
                    source_id=OuterRef("id"),
                )
            )
        )
        .filter(has_analysis=False)
        .order_by("published", "id")[:limit]
    )

    stats = {
        "pending_found": len(pending_articles),
        "analyzed": 0,
        "failed": 0,
    }
    for article in pending_articles:
        try:
            service.analyze_article(article, save=True, config_overrides=config_overrides)
            stats["analyzed"] += 1
        except Exception as exc:
            stats["failed"] += 1
            print(f"Skip analysis: {article.article_url} | {exc}")
    return stats


@shared_task(name="ai.tasks.task_analyze_pending_news_articles")
def task_analyze_pending_news_articles(limit: int = 1) -> dict[str, int]:
    return analyze_pending_news_articles(limit=limit)
