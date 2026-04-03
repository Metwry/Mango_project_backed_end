from __future__ import annotations

from dataclasses import asdict, dataclass

from django.db import transaction

from news.models import NewsArticle
from news.service.yahoo_news import PreparedNewsArticle


@dataclass(slots=True)
class NewsPutStats:
    received: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicate_content: int = 0
    failed_put: int = 0
    affected_article_ids: list[int] | None = None

    def __post_init__(self) -> None:
        if self.affected_article_ids is None:
            self.affected_article_ids = []

    def to_dict(self) -> dict[str, int]:
        payload = asdict(self)
        payload.pop("affected_article_ids", None)
        return payload


class NewsPutService:
    def put_articles(self, articles: list[PreparedNewsArticle]) -> NewsPutStats:
        stats = NewsPutStats(received=len(articles))
        for article in articles:
            try:
                self.put_article(article, stats=stats)
            except Exception as exc:
                stats.failed_put += 1
                print(f"Skip put: {article.article_url} | {exc}")
        return stats

    def put_article(
        self,
        article: PreparedNewsArticle,
        *,
        stats: NewsPutStats | None = None,
    ) -> NewsArticle | None:
        with transaction.atomic():
            existing = (
                NewsArticle.objects.select_for_update()
                .filter(article_url=article.article_url)
                .first()
            )
            if existing is not None:
                changed_fields = self._update_existing_article(existing, article=article)
                if changed_fields:
                    existing.save(update_fields=changed_fields)
                    if stats is not None:
                        stats.updated += 1
                        stats.affected_article_ids.append(existing.id)
                elif stats is not None:
                    stats.unchanged += 1
                return existing

            duplicate = NewsArticle.objects.filter(content_hash=article.content_hash).first()
            if duplicate is not None:
                if stats is not None:
                    stats.duplicate_content += 1
                return None

            created = NewsArticle.objects.create(
                provider=article.provider,
                source=article.source,
                article_url=article.article_url,
                title=article.title,
                content=article.content,
                content_hash=article.content_hash,
                language=article.language,
                published=article.published,
                fetched_at=article.fetched_at,
            )
            if stats is not None:
                stats.created += 1
                stats.affected_article_ids.append(created.id)
            return created

    @staticmethod
    def _update_existing_article(
        existing: NewsArticle,
        *,
        article: PreparedNewsArticle,
    ) -> list[str]:
        changed_fields: list[str] = []
        field_updates = {
            "provider": article.provider,
            "source": article.source,
            "title": article.title,
            "content": article.content,
            "content_hash": article.content_hash,
            "language": article.language,
            "published": article.published,
            "fetched_at": article.fetched_at,
        }
        for field_name, new_value in field_updates.items():
            if getattr(existing, field_name) != new_value:
                setattr(existing, field_name, new_value)
                changed_fields.append(field_name)
        return changed_fields
