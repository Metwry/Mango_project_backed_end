from __future__ import annotations

from celery import shared_task
from django.core.cache import cache
from django.db.models import Exists, OuterRef

from news.models import NewsArticle, NewsArticleEmbedding
from news.service.news_embedding import NewsArticleEmbeddingService
from news.service.news_put import NewsPutService
from news.service.yahoo_news import fetch_yahoo_finance_articles_sync


EMBEDDING_ENQUEUE_LOCK_TTL = 30


def _embedding_enqueue_lock_key(article_id: int) -> str:
    return f"news:enqueue:embedding:{article_id}"


def enqueue_embedding(article_id: int) -> str:
    if NewsArticleEmbedding.objects.filter(article_id=article_id).exists():
        return "skip_exists"
    if not cache.add(_embedding_enqueue_lock_key(article_id), "1", timeout=EMBEDDING_ENQUEUE_LOCK_TTL):
        return "skip_locked"
    task_embed_news_article.delay(article_id)
    return "queued"


def ingest_yahoo_news(
    *,
    limit: int = 50,
    concurrency: int = 5,
) -> dict[str, int]:
    articles = fetch_yahoo_finance_articles_sync(limit=limit, concurrency=concurrency)
    stats = NewsPutService().put_articles(articles)

    from ai.tasks import enqueue_analysis

    for article_id in stats.affected_article_ids:
        enqueue_embedding(article_id)
        enqueue_analysis(article_id)
    return stats.to_dict()


@shared_task(
    name="news.tasks.task_ingest_yahoo_news",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def task_ingest_yahoo_news(
    limit: int = 50,
    concurrency: int = 10,
) -> dict[str, int]:
    return ingest_yahoo_news(limit=limit, concurrency=concurrency)


@shared_task(
    name="news.tasks.task_embed_news_article",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def task_embed_news_article(article_id: int) -> dict[str, int | str]:
    article = NewsArticle.objects.get(id=article_id)
    if NewsArticleEmbedding.objects.filter(article_id=article_id).exists():
        return {"article_id": article_id, "status": "skip"}

    result = NewsArticleEmbeddingService().embed_article(article)
    return {
        "article_id": article_id,
        "status": "done",
        "chunk_count": result.chunk_count,
    }


def embed_missing_news_articles(*, limit: int = 100) -> dict[str, int]:
    pending_articles = list(
        NewsArticle.objects.annotate(
            has_embedding=Exists(
                NewsArticleEmbedding.objects.filter(article_id=OuterRef("id"))
            )
        )
        .filter(has_embedding=False)
        .order_by("published", "id")[:limit]
    )

    stats = {
        "pending_found": len(pending_articles),
        "queued": 0,
    }
    for article in pending_articles:
        enqueue_embedding(article.id)
        stats["queued"] += 1
    return stats


@shared_task(name="news.tasks.task_embed_missing_news_articles")
def task_embed_missing_news_articles(limit: int = 100) -> dict[str, int]:
    return embed_missing_news_articles(limit=limit)
