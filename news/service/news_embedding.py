from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from ai.config import get_embedding_task_config
from ai.services import EmbeddingService
from news.models import NewsArticle, NewsArticleEmbedding
from news.service.hash_utils import calculate_content_md5


@dataclass(slots=True)
class NewsEmbeddingChunk:
    index: int
    text: str


@dataclass(slots=True)
class NewsEmbeddingStats:
    article_id: int
    chunk_count: int
    embedding_model: str


class NewsArticleEmbeddingService:
    PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
    NATURAL_BOUNDARY_RE = re.compile(r"\n\s*\n|(?<=[.!?])\s+|\s+")

    def __init__(self) -> None:
        self.embedding_service = EmbeddingService()

    def embed_article(
        self,
        article: NewsArticle,
        *,
        task_name: str = "news_article_embedding",
        config_overrides: dict[str, Any] | None = None,
    ) -> NewsEmbeddingStats:
        task_config = get_embedding_task_config(task_name)
        if config_overrides:
            task_config.update(config_overrides)

        chunks = self._build_chunks(
            content=article.content,
            max_chars=int(task_config["chunk"]["max_chars"]),
            overlap_chars=int(task_config["chunk"]["overlap_chars"]),
        )
        texts = [
            self._build_embedding_text(
                title=article.title,
                chunk_text=chunk.text,
                include_title=bool(task_config["chunk"]["include_title"]),
            )
            for chunk in chunks
        ]
        embedding_result = self.embedding_service.embed(
            task_name=task_name,
            texts=texts,
            config_overrides=config_overrides,
        )

        self._rebuild_embeddings(
            article=article,
            chunks=chunks,
            vectors=embedding_result.vectors,
            embedding_model=embedding_result.model_name,
        )
        return NewsEmbeddingStats(
            article_id=article.id,
            chunk_count=len(chunks),
            embedding_model=embedding_result.model_name,
        )

    @classmethod
    def _build_chunks(
        cls,
        *,
        content: str,
        max_chars: int,
        overlap_chars: int,
    ) -> list[NewsEmbeddingChunk]:
        normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return []

        paragraphs = [part.strip() for part in cls.PARAGRAPH_SPLIT_RE.split(normalized) if part.strip()]
        if not paragraphs:
            paragraphs = [normalized]

        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = paragraph if not current else f"{current}\n\n{paragraph}"
            if len(candidate) <= max_chars:
                current = candidate
                continue

            if current:
                chunks.append(current)
                current = cls._tail_overlap(current, overlap_chars)

            if len(paragraph) <= max_chars:
                current = paragraph if not current else f"{current}\n\n{paragraph}"
                continue

            long_parts = cls._split_long_text(
                text=paragraph,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            )
            chunks.extend(long_parts[:-1])
            current = long_parts[-1]

        if current:
            chunks.append(current)

        return [NewsEmbeddingChunk(index=index, text=text) for index, text in enumerate(chunks)]

    @staticmethod
    def _split_long_text(*, text: str, max_chars: int, overlap_chars: int) -> list[str]:
        parts: list[str] = []
        start = 0
        step = max(max_chars - overlap_chars, 1)
        while start < len(text):
            end = min(start + max_chars, len(text))
            parts.append(text[start:end].strip())
            if end >= len(text):
                break
            start += step
        return [part for part in parts if part]

    @staticmethod
    def _tail_overlap(text: str, overlap_chars: int) -> str:
        if overlap_chars <= 0:
            return ""
        stripped = text.strip()
        if len(stripped) <= overlap_chars:
            return stripped

        target_start = max(0, len(stripped) - overlap_chars)
        next_boundary = NewsArticleEmbeddingService._find_boundary_forward(stripped, target_start)
        if next_boundary is not None:
            candidate = stripped[next_boundary:].strip()
            if candidate:
                return candidate

        previous_boundary = NewsArticleEmbeddingService._find_boundary_backward(stripped, target_start)
        if previous_boundary is not None:
            candidate = stripped[previous_boundary:].strip()
            if candidate:
                return candidate

        return stripped[-overlap_chars:].strip()

    @classmethod
    def _find_boundary_forward(cls, text: str, start: int) -> int | None:
        match = cls.NATURAL_BOUNDARY_RE.search(text, pos=start)
        if match is None:
            return None
        return match.end()

    @classmethod
    def _find_boundary_backward(cls, text: str, start: int) -> int | None:
        boundary: int | None = None
        for match in cls.NATURAL_BOUNDARY_RE.finditer(text, endpos=start):
            boundary = match.end()
        return boundary

    @staticmethod
    def _build_embedding_text(*, title: str, chunk_text: str, include_title: bool) -> str:
        if include_title:
            return f"Title: {title}\n\nContent:\n{chunk_text}"
        return chunk_text

    @staticmethod
    @transaction.atomic
    def _rebuild_embeddings(
        *,
        article: NewsArticle,
        chunks: list[NewsEmbeddingChunk],
        vectors: list[list[float]],
        embedding_model: str,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunk 数量与 embedding 向量数量不一致")

        NewsArticleEmbedding.objects.filter(article=article).delete()
        NewsArticleEmbedding.objects.bulk_create(
            [
                NewsArticleEmbedding(
                    article=article,
                    chunk_index=chunk.index,
                    chunk_text=chunk.text,
                    chunk_hash=calculate_content_md5(chunk.text),
                    title=article.title,
                    source=article.source,
                    published=article.published,
                    embedding_model=embedding_model,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
        )
