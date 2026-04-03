from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from ai.models import AIAnalysis, AIAnalysisCountry, AIAnalysisInstrument, AIAnalysisTag
from ai.services.content_analysis import AnalysisResult, AnalysisService
from market.models import Instrument
from news.models import NewsArticle


@dataclass(slots=True)
class NewsAnalysisPayload:
    topic: str
    summary_short: str
    summary_long: str
    sentiment: str
    impact_level: str
    countries: list[str]
    tags: list[str]
    instrument_candidates: list[str]


class NewsAnalysisService:
    TASK_NAME = "news_analysis"
    ALLOWED_SENTIMENTS = {"positive", "neutral", "negative"}
    ALLOWED_IMPACT_LEVELS = {"low", "medium", "high"}

    def __init__(self) -> None:
        self.analysis_service = AnalysisService()

    def analyze_article(
        self,
        article: NewsArticle,
        *,
        save: bool = True,
        config_overrides: dict[str, Any] | None = None,
    ) -> AnalysisResult | AIAnalysis:
        result = self.analysis_service.analyze(
            task_name=self.TASK_NAME,
            variables={
                "provider": article.provider,
                "source": article.source,
                "title": article.title,
                "content": article.content,
                "language": article.language,
                "published": article.published.isoformat() if article.published else "",
            },
            config_overrides=config_overrides,
        )
        payload = self._parse_payload(result.data)
        if not save:
            return result
        return self._save_analysis(article, payload, result)

    @staticmethod
    def _parse_payload(data: dict[str, Any]) -> NewsAnalysisPayload:
        sentiment = str(data["sentiment"]).strip().lower()
        impact_level = str(data["impact_level"]).strip().lower()
        if sentiment not in NewsAnalysisService.ALLOWED_SENTIMENTS:
            raise ValueError(f"sentiment 值不合法: {sentiment}")
        if impact_level not in NewsAnalysisService.ALLOWED_IMPACT_LEVELS:
            raise ValueError(f"impact_level 值不合法: {impact_level}")

        return NewsAnalysisPayload(
            topic=str(data["topic"]).strip(),
            summary_short=str(data["summary_short"]).strip(),
            summary_long=str(data["summary_long"]).strip(),
            sentiment=sentiment,
            impact_level=impact_level,
            countries=NewsAnalysisService._clean_string_list(data.get("countries", [])),
            tags=NewsAnalysisService._clean_string_list(data.get("tags", [])),
            instrument_candidates=NewsAnalysisService._clean_string_list(
                data.get("instrument_candidates", [])
            ),
        )

    @staticmethod
    def _clean_string_list(items: Any) -> list[str]:
        if not isinstance(items, list):
            raise ValueError("分析结果字段必须是字符串数组")
        cleaned: list[str] = []
        for item in items:
            value = str(item).strip()
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned

    @transaction.atomic
    def _save_analysis(
        self,
        article: NewsArticle,
        payload: NewsAnalysisPayload,
        result: AnalysisResult,
    ) -> AIAnalysis:
        analysis, _ = AIAnalysis.objects.update_or_create(
            source_type=AIAnalysis.SourceType.NEWS_ARTICLE,
            source_id=article.id,
            defaults={
                "topic": payload.topic,
                "summary_short": payload.summary_short,
                "summary_long": payload.summary_long,
                "sentiment": payload.sentiment,
                "impact_level": payload.impact_level,
                "model_name": result.model_name,
                "prompt_name": result.prompt_name,
                "analyzed_at": timezone.now(),
            },
        )

        AIAnalysisCountry.objects.filter(ai_analysis=analysis).delete()
        AIAnalysisTag.objects.filter(ai_analysis=analysis).delete()
        AIAnalysisInstrument.objects.filter(ai_analysis=analysis).delete()

        AIAnalysisCountry.objects.bulk_create(
            [
                AIAnalysisCountry(ai_analysis=analysis, country_name=country)
                for country in payload.countries
            ]
        )
        AIAnalysisTag.objects.bulk_create(
            [
                AIAnalysisTag(ai_analysis=analysis, tag_name=tag)
                for tag in payload.tags
            ]
        )

        instruments = self._resolve_instruments(payload.instrument_candidates)
        AIAnalysisInstrument.objects.bulk_create(
            [
                AIAnalysisInstrument(ai_analysis=analysis, instrument=instrument)
                for instrument in instruments
            ]
        )
        return analysis

    @staticmethod
    def _resolve_instruments(symbols: list[str]) -> list[Instrument]:
        if not symbols:
            return []

        normalized_symbols = [symbol.upper() for symbol in symbols]
        exact_symbol_map = {
            instrument.symbol.upper(): instrument
            for instrument in Instrument.objects.filter(symbol__in=normalized_symbols)
        }
        missing = [symbol for symbol in normalized_symbols if symbol not in exact_symbol_map]
        short_code_map = {
            instrument.short_code.upper(): instrument
            for instrument in Instrument.objects.filter(short_code__in=missing)
        }

        resolved: list[Instrument] = []
        seen_ids: set[int] = set()
        for symbol in normalized_symbols:
            instrument = exact_symbol_map.get(symbol) or short_code_map.get(symbol)
            if instrument and instrument.id not in seen_ids:
                resolved.append(instrument)
                seen_ids.add(instrument.id)
        return resolved
