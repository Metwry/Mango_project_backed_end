from celery import shared_task

from news.service.news_ingest_service import YahooNewsIngestService


def ingest_yahoo_news(
    *,
    limit: int = 50,
    concurrency: int = 5,
    analyze: bool = True,
    config_overrides: dict | None = None,
) -> dict[str, int]:
    service = YahooNewsIngestService()
    stats = service.ingest_latest(
        limit=limit,
        concurrency=concurrency,
        analyze=analyze,
        config_overrides=config_overrides,
    )
    return stats.to_dict()


@shared_task(name="news.tasks.task_ingest_yahoo_news")
def task_ingest_yahoo_news(
    limit: int = 50,
    concurrency: int = 10,
    analyze: bool = True,
) -> dict[str, int]:
    return ingest_yahoo_news(limit=limit, concurrency=concurrency, analyze=analyze)
