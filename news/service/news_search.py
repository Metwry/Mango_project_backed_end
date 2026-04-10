from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pgvector.django import CosineDistance

from ai.models import AIAnalysis
from ai.services.content_embedding import EmbeddingService
from news.models import NewsArticleEmbedding


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
    response_mode: str
    context: str
    hit_count: int


class NewsSearchService:
    MAX_CANDIDATE_LIMIT = 50
    CANDIDATE_MULTIPLIER = 10
    MAX_MATCHED_CHUNKS_PER_ARTICLE = 3
    DEFAULT_TOP_K = 8
    DEFAULT_MAX_DISTANCE = 1.5
    EMBEDDING_TASK_NAME = "news_article_embedding"

    def __init__(self) -> None:
        self.embedding_service = EmbeddingService()

    def search(
        self,
        *,
        query: str,
        response_mode: str = "overview",
        top_k: int | None = None,
        published_from: datetime | None = None,
        published_to: datetime | None = None,
    ) -> NewsSearchResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query 不能为空")
        resolved_top_k = top_k or self.DEFAULT_TOP_K
        if resolved_top_k <= 0:
            raise ValueError("top_k 必须大于 0")

        max_distance = self.DEFAULT_MAX_DISTANCE
        resolved_published_from = published_from
        resolved_published_to = published_to

        embedding_result = self.embedding_service.embed(
            task_name=self.EMBEDDING_TASK_NAME,
            texts=[normalized_query],
        )
        if not embedding_result.vectors:
            result = NewsSearchResult(
                query=normalized_query,
                response_mode=response_mode,
                context="",
                hit_count=0,
            )
            return result

        query_vector = embedding_result.vectors[0]
        candidate_limit = min(
            max(resolved_top_k * self.CANDIDATE_MULTIPLIER, resolved_top_k),
            self.MAX_CANDIDATE_LIMIT,
        )
        candidates_queryset = NewsArticleEmbedding.objects.select_related("article")
        if resolved_published_from is not None:
            candidates_queryset = candidates_queryset.filter(published__gte=resolved_published_from)
        if resolved_published_to is not None:
            candidates_queryset = candidates_queryset.filter(published__lte=resolved_published_to)
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
        hits = hits[:resolved_top_k]

        self._attach_analysis(hits)
        result = NewsSearchResult(
            query=normalized_query,
            response_mode=response_mode,
            context="",
            hit_count=len(hits),
        )
        result.context = self._build_context(hits, response_mode)
        return result

    @staticmethod
    def _build_context(hits: list[NewsSearchHit], response_mode: str) -> str:
        if response_mode == "detail":
            return NewsSearchService._build_detail_context(hits)
        return NewsSearchService._build_overview_context(hits)

    @staticmethod
    def _build_overview_context(hits: list[NewsSearchHit]) -> str:
        lines: list[str] = []
        for index, hit in enumerate(hits[:5], start=1):
            lines.append(f"[{index}] title: {hit.title}")
            lines.append(f"source: {hit.source}")
            lines.append(f"published: {hit.published.isoformat()}")
            lines.append(f"reference_url: {hit.article_url}")
            lines.append(f"distance: {hit.score:.4f}")
            if hit.analysis is not None:
                lines.append("analysis:")
                lines.append(f"- topic: {hit.analysis.topic}")
                lines.append(f"- summary_short: {hit.analysis.summary_short}")
            else:
                lines.append(f"summary_short: {hit.chunk_text}")
            lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def _build_detail_context(hits: list[NewsSearchHit]) -> str:
        lines: list[str] = []
        for index, hit in enumerate(hits[:8], start=1):
            lines.append(f"[{index}] title: {hit.title}")
            lines.append(f"source: {hit.source}")
            lines.append(f"published: {hit.published.isoformat()}")
            lines.append(f"reference_url: {hit.article_url}")
            lines.append(f"distance: {hit.score:.4f}")
            if hit.analysis is not None:
                lines.append("analysis:")
                lines.append(f"- topic: {hit.analysis.topic}")
                lines.append(f"- summary_short: {hit.analysis.summary_short}")
                lines.append(f"- summary_long: {hit.analysis.summary_long}")
                lines.append(f"- sentiment: {hit.analysis.sentiment}")
                lines.append(f"- impact_level: {hit.analysis.impact_level}")
                lines.append(f"- countries: {', '.join(hit.analysis.countries)}")
                lines.append(f"- tags: {', '.join(hit.analysis.tags)}")
                lines.append(f"- instruments: {', '.join(hit.analysis.instruments)}")
            lines.append("matched_chunks:")
            for chunk in hit.matched_chunks:
                lines.append(
                    f"- chunk_index={chunk.chunk_index}, distance={chunk.score:.4f}, text={chunk.chunk_text}"
                )
            lines.append("")

        return "\n".join(lines).strip()

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
