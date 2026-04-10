from __future__ import annotations

from celery import shared_task
from django.core.cache import cache
from django.db.models import Exists, OuterRef

from ai.models import AIAnalysis
from ai.services.news.analysis import NewsAnalysisService
from news.models import NewsArticle


ANALYSIS_ENQUEUE_LOCK_TTL = 30


def _analysis_enqueue_lock_key(article_id: int) -> str:
    return f"news:enqueue:analysis:{article_id}"


def enqueue_analysis(article_id: int) -> str:
    if AIAnalysis.objects.filter(
        source_type=AIAnalysis.SourceType.NEWS_ARTICLE,
        source_id=article_id,
    ).exists():
        return "skip_exists"
    if not cache.add(_analysis_enqueue_lock_key(article_id), "1", timeout=ANALYSIS_ENQUEUE_LOCK_TTL):
        return "skip_locked"
    task_analyze_news_article.delay(article_id)
    return "queued"


@shared_task(
    name="ai.tasks.task_analyze_news_article",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def task_analyze_news_article(article_id: int) -> dict[str, int | str]:
    article = NewsArticle.objects.get(id=article_id)
    if AIAnalysis.objects.filter(
        source_type=AIAnalysis.SourceType.NEWS_ARTICLE,
        source_id=article_id,
    ).exists():
        return {"article_id": article_id, "status": "skip"}

    NewsAnalysisService().analyze_article(article, save=True)
    return {"article_id": article_id, "status": "done"}


def analyze_missing_news_articles(*, limit: int = 100) -> dict[str, int]:
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
        "queued": 0,
    }
    for article in pending_articles:
        enqueue_analysis(article.id)
        stats["queued"] += 1
    return stats


def analyze_pending_news_articles(*, limit: int = 100) -> dict[str, int]:
    return analyze_missing_news_articles(limit=limit)


@shared_task(name="ai.tasks.task_analyze_missing_news_articles")
def task_analyze_missing_news_articles(limit: int = 100) -> dict[str, int]:
    return analyze_missing_news_articles(limit=limit)


@shared_task(name="ai.tasks.task_analyze_pending_news_articles")
def task_analyze_pending_news_articles(limit: int = 100) -> dict[str, int]:
    return analyze_missing_news_articles(limit=limit)
