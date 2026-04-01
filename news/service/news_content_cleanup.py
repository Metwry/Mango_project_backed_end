from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction

from news.models import NewsArticle, NewsArticleEmbedding
from news.service.filters_word import is_noise_paragraph, is_tail_cutoff
from news.service.hash_utils import calculate_content_md5


BLOCK_SPLIT_RE = re.compile(r"\n\s*\n+")
HEADING_PREFIX_RE = re.compile(r"^#{1,6}\s+")
LIST_PREFIX_RE = re.compile(r"^(?:[-*+]\s+|\d+\.\s+)")
BLOCKQUOTE_PREFIX_RE = re.compile(r"^>\s+")
CAPTION_PREFIX_RE = re.compile(r"^\[caption\]\s*", re.I)


@dataclass(slots=True)
class NewsContentCleanupStats:
    scanned: int = 0
    updated: int = 0
    cleared_embeddings: int = 0


def clean_stored_article_content(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    cleaned_blocks: list[str] = []
    for raw_block in BLOCK_SPLIT_RE.split(normalized):
        block = raw_block.strip()
        if not block:
            continue

        plain_text = _normalize_block_for_matching(block)
        if is_tail_cutoff(plain_text):
            break
        if is_noise_paragraph(plain_text):
            continue

        cleaned_blocks.append(block)

    return "\n\n".join(cleaned_blocks).strip()


class NewsContentCleanupService:
    def clean_articles(self, *, limit: int | None = None) -> NewsContentCleanupStats:
        stats = NewsContentCleanupStats()
        queryset = NewsArticle.objects.order_by("id")
        if limit is not None:
            queryset = queryset[:limit]

        for article in queryset.iterator() if limit is None else queryset:
            stats.scanned += 1
            deleted_embeddings = self._clean_article(article)
            if deleted_embeddings is not None:
                stats.updated += 1
                stats.cleared_embeddings += deleted_embeddings

        return stats

    @staticmethod
    @transaction.atomic
    def _clean_article(article: NewsArticle) -> int | None:
        cleaned_content = clean_stored_article_content(article.content)
        if cleaned_content == article.content:
            return None

        article.content = cleaned_content
        article.content_hash = calculate_content_md5(cleaned_content)
        article.save(update_fields=["content", "content_hash"])
        deleted_count, _ = NewsArticleEmbedding.objects.filter(article=article).delete()
        return deleted_count


def _normalize_block_for_matching(block: str) -> str:
    text = block.strip()
    text = HEADING_PREFIX_RE.sub("", text)
    text = BLOCKQUOTE_PREFIX_RE.sub("", text)
    text = CAPTION_PREFIX_RE.sub("", text)
    text = LIST_PREFIX_RE.sub("", text)
    return " ".join(part.strip() for part in text.splitlines() if part.strip())
