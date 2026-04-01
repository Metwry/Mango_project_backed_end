from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone as dt_timezone
from email.utils import parsedate_to_datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from ai.models import AIAnalysis
from ai.services import NewsAnalysisService
from news.models import NewsArticle
from news.service.hash_utils import calculate_content_md5
from news.service.yahoo_news import (
    DEFAULT_CONCURRENCY,
    DEFAULT_LIMIT,
    YahooNewsArticle,
    fetch_yahoo_finance_articles_sync,
)


@dataclass(slots=True)
class YahooNewsIngestStats:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    duplicate_content: int = 0
    analyzed: int = 0
    skipped_analysis: int = 0
    failed_analysis: int = 0
    failed_ingest: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class YahooNewsIngestService:
    def __init__(self, news_analysis_service: NewsAnalysisService | None = None) -> None:
        self.news_analysis_service = news_analysis_service or NewsAnalysisService()

    def ingest_latest(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        concurrency: int = DEFAULT_CONCURRENCY,
        analyze: bool = True,
        config_overrides: dict[str, Any] | None = None,
    ) -> YahooNewsIngestStats:
        articles = fetch_yahoo_finance_articles_sync(limit=limit, concurrency=concurrency)
        stats = YahooNewsIngestStats(fetched=len(articles))
        for article in articles:
            try:
                saved_article, content_changed = self._ingest_article(
                    article,
                    stats=stats,
                )
                self._maybe_analyze_article(
                    saved_article,
                    analyze=analyze,
                    content_changed=content_changed,
                    stats=stats,
                    config_overrides=config_overrides,
                )
            except Exception as exc:
                stats.failed_ingest += 1
                print(f"Skip ingest: {article.link} | {exc}")
        return stats

    def _ingest_article(
        self,
        article: YahooNewsArticle,
        *,
        stats: YahooNewsIngestStats,
    ) -> tuple[NewsArticle | None, bool]:
        content_hash = calculate_content_md5(article.content)
        fetched_at = timezone.now()
        published_at = self._parse_published_at(article.published_at)

        with transaction.atomic():
            existing = NewsArticle.objects.select_for_update().filter(article_url=article.link).first()
            if existing is not None:
                content_changed = existing.content_hash != content_hash
                changed_fields = self._update_existing_article(
                    existing,
                    article=article,
                    content_hash=content_hash,
                    published_at=published_at,
                    fetched_at=fetched_at,
                )
                if changed_fields:
                    stats.updated += 1
                    existing.save(update_fields=changed_fields)
                return existing, content_changed

            duplicate = NewsArticle.objects.filter(content_hash=content_hash).first()
            if duplicate is not None:
                stats.duplicate_content += 1
                return None, False

            created = NewsArticle.objects.create(
                provider="yahoo",
                source=article.source,
                article_url=article.link,
                title=article.title,
                content=article.content,
                content_hash=content_hash,
                language="en",
                published=published_at,
                fetched_at=fetched_at,
            )
            stats.created += 1
            return created, True

    @staticmethod
    def _update_existing_article(
        existing: NewsArticle,
        *,
        article: YahooNewsArticle,
        content_hash: str,
        published_at: datetime,
        fetched_at: datetime,
    ) -> list[str]:
        changed_fields: list[str] = []
        field_updates = {
            "provider": "yahoo",
            "source": article.source,
            "title": article.title,
            "content": article.content,
            "content_hash": content_hash,
            "language": "en",
            "published": published_at,
            "fetched_at": fetched_at,
        }
        for field_name, new_value in field_updates.items():
            if getattr(existing, field_name) != new_value:
                setattr(existing, field_name, new_value)
                changed_fields.append(field_name)
        return changed_fields

    def _maybe_analyze_article(
        self,
        article: NewsArticle,
        *,
        analyze: bool,
        content_changed: bool,
        stats: YahooNewsIngestStats,
        config_overrides: dict[str, Any] | None,
    ) -> None:
        if not analyze:
            stats.skipped_analysis += 1
            return
        if article is None:
            return

        has_existing_analysis = AIAnalysis.objects.filter(
            source_type=AIAnalysis.SourceType.NEWS_ARTICLE,
            source_id=article.id,
        ).exists()
        if has_existing_analysis and not content_changed:
            stats.skipped_analysis += 1
            return

        try:
            self.news_analysis_service.analyze_article(
                article,
                save=True,
                config_overrides=config_overrides,
            )
            stats.analyzed += 1
        except Exception as exc:
            stats.failed_analysis += 1
            print(f"Skip analysis: {article.article_url} | {exc}")

    @staticmethod
    def _parse_published_at(value: str) -> datetime:
        raw_value = str(value).strip()
        if not raw_value:
            raise ValueError("published_at is empty")

        try:
            parsed = parsedate_to_datetime(raw_value)
        except (TypeError, ValueError, IndexError):
            iso_value = raw_value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(iso_value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_timezone.utc)
        return parsed.astimezone(dt_timezone.utc)
