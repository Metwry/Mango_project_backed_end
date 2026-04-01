from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import perf_counter

from pgvector.django import CosineDistance

from ai.models import AIAnalysis
from ai.services import EmbeddingService
from ai.services.ai_log import ai_log_scope
from news.models import NewsArticleEmbedding
from news.service.query_understanding import NewsQueryPlan, QueryUnderstandingService


@dataclass(slots=True)
class NewsMatchedChunk:
    chunk_index: int
    chunk_text: str
    score: float


@dataclass(slots=True)
class NewsSearchAnalysis:
    topic: str
    summary_short: str
    summary_long: str
    sentiment: str
    impact_level: str
    countries: list[str]
    tags: list[str]
    instruments: list[str]
    model_name: str
    prompt_name: str
    analyzed_at: datetime


@dataclass(slots=True)
class NewsSearchHit:
    article_id: int
    title: str
    source: str
    published: datetime
    article_url: str
    chunk_index: int
    chunk_text: str
    score: float
    matched_chunks: list[NewsMatchedChunk]
    analysis: NewsSearchAnalysis | None


@dataclass(slots=True)
class NewsSearchResult:
    query: str
    semantic_query: str
    published_from: datetime | None
    published_to: datetime | None
    response_mode: str
    hits: list[NewsSearchHit]


class NewsSearchService:
    MAX_CANDIDATE_LIMIT = 50
    CANDIDATE_MULTIPLIER = 10
    MAX_MATCHED_CHUNKS_PER_ARTICLE = 3

    def __init__(self) -> None:
        self.embedding_service = EmbeddingService()
        self.query_understanding_service = QueryUnderstandingService()

    def search(
        self,
        *,
        query: str,
        top_k: int = 5,
        max_distance: float | None = 0.7,
        task_name: str = "news_article_embedding",
        config_overrides: dict | None = None,
        query_understanding_overrides: dict | None = None,
        timezone_name: str | None = None,
        skip_query_understanding: bool = False,
    ) -> NewsSearchResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query 不能为空")
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        if max_distance is not None and max_distance < 0:
            raise ValueError("max_distance 不能小于 0")
        with ai_log_scope(event="news_search", query=normalized_query) as scope:
            step_started_at = perf_counter()
            if skip_query_understanding:
                query_plan = NewsQueryPlan(
                    raw_query=normalized_query,
                    semantic_query=normalized_query,
                    published_from=None,
                    published_to=None,
                    response_mode="overview",
                )
            else:
                query_plan = self.query_understanding_service.understand(
                    query=normalized_query,
                    timezone_name=timezone_name,
                    config_overrides=query_understanding_overrides,
                )
            query_understanding_ms = (perf_counter() - step_started_at) * 1000
            response_mode = str(getattr(query_plan, "response_mode", "overview")).strip().lower()
            if response_mode not in {"overview", "detail"}:
                response_mode = "overview"
            scope.set(
                semantic_query=query_plan.semantic_query,
                published_from=query_plan.published_from,
                published_to=query_plan.published_to,
                response_mode=response_mode,
                skip_query_understanding=skip_query_understanding,
                query_understanding_ms=round(query_understanding_ms, 2),
            )

            step_started_at = perf_counter()
            embedding_result = self.embedding_service.embed(
                task_name=task_name,
                texts=[query_plan.semantic_query],
                config_overrides=config_overrides,
            )
            embedding_ms = (perf_counter() - step_started_at) * 1000
            scope.set(embedding_ms=round(embedding_ms, 2))
            if not embedding_result.vectors:
                result = NewsSearchResult(
                    query=normalized_query,
                    semantic_query=query_plan.semantic_query,
                    published_from=query_plan.published_from,
                    published_to=query_plan.published_to,
                    response_mode=response_mode,
                    hits=[],
                )
                scope.set(hit_count=0)
                return result

            query_vector = embedding_result.vectors[0]
            candidate_limit = min(
                max(top_k * self.CANDIDATE_MULTIPLIER, top_k),
                self.MAX_CANDIDATE_LIMIT,
            )
            step_started_at = perf_counter()
            candidates_queryset = NewsArticleEmbedding.objects.select_related("article")
            if query_plan.published_from is not None:
                candidates_queryset = candidates_queryset.filter(published__gte=query_plan.published_from)
            if query_plan.published_to is not None:
                candidates_queryset = candidates_queryset.filter(published__lte=query_plan.published_to)
            candidates = (
                candidates_queryset
                .annotate(score=CosineDistance("embedding", query_vector))
                .order_by("score", "article_id", "chunk_index")[:candidate_limit]
            )

            best_hits_by_article: dict[int, NewsSearchHit] = {}
            for candidate in candidates:
                article_id = candidate.article_id
                matched_chunk = NewsMatchedChunk(
                    chunk_index=candidate.chunk_index,
                    chunk_text=candidate.chunk_text,
                    score=float(candidate.score),
                )
                if article_id in best_hits_by_article:
                    hit = best_hits_by_article[article_id]
                    if len(hit.matched_chunks) < self.MAX_MATCHED_CHUNKS_PER_ARTICLE:
                        hit.matched_chunks.append(matched_chunk)
                    continue
                best_hits_by_article[article_id] = NewsSearchHit(
                    article_id=article_id,
                    title=candidate.title,
                    source=candidate.source,
                    published=candidate.published,
                    article_url=candidate.article.article_url,
                    chunk_index=candidate.chunk_index,
                    chunk_text=candidate.chunk_text,
                    score=matched_chunk.score,
                    matched_chunks=[matched_chunk],
                    analysis=None,
                )

            hits = sorted(best_hits_by_article.values(), key=lambda item: (item.score, item.article_id))
            if max_distance is not None:
                hits = [hit for hit in hits if hit.score <= max_distance]
            hits = hits[:top_k]
            vector_search_ms = (perf_counter() - step_started_at) * 1000
            scope.set(
                candidate_limit=candidate_limit,
                candidate_count=len(candidates),
                vector_search_ms=round(vector_search_ms, 2),
            )

            step_started_at = perf_counter()
            self._attach_analysis(hits)
            analysis_attach_ms = (perf_counter() - step_started_at) * 1000
            result = NewsSearchResult(
                query=normalized_query,
                semantic_query=query_plan.semantic_query,
                published_from=query_plan.published_from,
                published_to=query_plan.published_to,
                response_mode=response_mode,
                hits=hits,
            )
            scope.set(
                hit_count=len(hits),
                analysis_attach_ms=round(analysis_attach_ms, 2),
            )
            return result

    @staticmethod
    def _attach_analysis(hits: list[NewsSearchHit]) -> None:
        if not hits:
            return

        article_ids = [hit.article_id for hit in hits]
        analyses = (
            AIAnalysis.objects.filter(
                source_type=AIAnalysis.SourceType.NEWS_ARTICLE,
                source_id__in=article_ids,
            )
            .prefetch_related(
                "country_links",
                "tag_links",
                "instrument_links__instrument",
            )
            .order_by("source_id", "-analyzed_at", "-id")
        )

        latest_by_article: dict[int, AIAnalysis] = {}
        for analysis in analyses:
            source_id = int(analysis.source_id)
            if source_id not in latest_by_article:
                latest_by_article[source_id] = analysis

        for hit in hits:
            analysis = latest_by_article.get(hit.article_id)
            if analysis is None:
                continue
            hit.analysis = NewsSearchAnalysis(
                topic=analysis.topic,
                summary_short=analysis.summary_short,
                summary_long=analysis.summary_long,
                sentiment=analysis.sentiment,
                impact_level=analysis.impact_level,
                countries=[link.country_name for link in analysis.country_links.all()],
                tags=[link.tag_name for link in analysis.tag_links.all()],
                instruments=[
                    link.instrument.symbol for link in analysis.instrument_links.all()
                ],
                model_name=analysis.model_name,
                prompt_name=analysis.prompt_name,
                analyzed_at=analysis.analyzed_at,
            )
