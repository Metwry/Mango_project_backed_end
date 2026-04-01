from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Iterator

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ai.config import get_analysis_task_config, get_prompt_path
from ai.llmmodels import LLMModelFactory
from ai.services.ai_log import ai_log_scope
from news.service.news_search import NewsSearchResult, NewsSearchService


@dataclass(slots=True)
class _PreparedAnswer:
    search_result: NewsSearchResult
    context: str
    chat_model: object
    rendered_prompt: str
    search_ms: float
    context_build_ms: float


class NewsAnswerService:
    OVERVIEW_HIT_LIMIT = 8
    DETAIL_HIT_LIMIT = 3

    def __init__(self) -> None:
        self.search_service = NewsSearchService()

    def answer(
        self,
        *,
        query: str,
        top_k: int = 5,
        max_distance: float | None = 0.7,
        timezone_name: str | None = None,
        search_config_overrides: dict | None = None,
        query_understanding_overrides: dict | None = None,
        answer_config_overrides: dict | None = None,
        skip_query_understanding: bool = False,
    ) -> Iterator[str]:
        with ai_log_scope(event="news_answer", query=query) as scope:
            prepared = self._prepare_answer(
                query=query,
                top_k=top_k,
                max_distance=max_distance,
                timezone_name=timezone_name,
                search_config_overrides=search_config_overrides,
                query_understanding_overrides=query_understanding_overrides,
                answer_config_overrides=answer_config_overrides,
                skip_query_understanding=skip_query_understanding,
            )
            scope.set(
                search_ms=round(prepared.search_ms, 2),
                context_build_ms=round(prepared.context_build_ms, 2),
                skip_query_understanding=skip_query_understanding,
            )
            if not prepared.search_result.hits:
                result = "未检索到足够相关的财经新闻，暂时无法给出可靠回答。"
                scope.set(
                    semantic_query=prepared.search_result.semantic_query,
                    response_mode=prepared.search_result.response_mode,
                    hit_count=0,
                    answer_length=len(result),
                )
                yield result
                return

            step_started_at = perf_counter()
            answer_chunks: list[str] = []
            prompt = ChatPromptTemplate.from_messages([("user", prepared.rendered_prompt)])
            chain = prompt | prepared.chat_model.llm | StrOutputParser()
            for chunk in chain.stream({}):
                if not chunk:
                    continue
                answer_chunks.append(chunk)
                yield chunk
            answer_generation_ms = (perf_counter() - step_started_at) * 1000
            answer_text = "".join(answer_chunks).strip()
            scope.set(
                semantic_query=prepared.search_result.semantic_query,
                response_mode=prepared.search_result.response_mode,
                hit_count=len(prepared.search_result.hits),
                context_hit_count=min(
                    len(prepared.search_result.hits),
                    self.DETAIL_HIT_LIMIT if prepared.search_result.response_mode == "detail" else self.OVERVIEW_HIT_LIMIT,
                ),
                context_length=len(prepared.context),
                answer_generation_ms=round(answer_generation_ms, 2),
                answer_length=len(answer_text),
            )

    def _prepare_answer(
        self,
        *,
        query: str,
        top_k: int,
        max_distance: float | None,
        timezone_name: str | None,
        search_config_overrides: dict | None,
        query_understanding_overrides: dict | None,
        answer_config_overrides: dict | None,
        skip_query_understanding: bool,
    ) -> _PreparedAnswer:
        step_started_at = perf_counter()
        search_result = self.search_service.search(
            query=query,
            top_k=top_k,
            max_distance=max_distance,
            config_overrides=search_config_overrides,
            query_understanding_overrides=query_understanding_overrides,
            timezone_name=timezone_name,
            skip_query_understanding=skip_query_understanding,
        )
        search_ms = (perf_counter() - step_started_at) * 1000

        if not search_result.hits:
            return _PreparedAnswer(
                search_result=search_result,
                context="",
                chat_model=object(),
                rendered_prompt="",
                search_ms=search_ms,
                context_build_ms=0.0,
            )

        step_started_at = perf_counter()
        context = self._build_context(query, search_result)
        context_build_ms = (perf_counter() - step_started_at) * 1000

        task_config = get_analysis_task_config("news_answer")
        if answer_config_overrides:
            task_config.update(answer_config_overrides)

        provider_name = str(task_config["provider"]).strip()
        model_name = str(task_config["model"]).strip()
        prompt_path = get_prompt_path(task_config["prompt_file"])
        prompt_text = prompt_path.read_text(encoding="utf-8")
        rendered_prompt = prompt_text.format(
            **self._build_answer_variables(
                query=query,
                search_result=search_result,
                context=context,
            )
        )
        chat_model = LLMModelFactory.create_chat_model(
            provider_name=provider_name,
            model_name=model_name,
            task_config=task_config,
        )
        return _PreparedAnswer(
            search_result=search_result,
            context=context,
            chat_model=chat_model,
            rendered_prompt=rendered_prompt,
            search_ms=search_ms,
            context_build_ms=context_build_ms,
        )

    @staticmethod
    def _build_answer_variables(
        *,
        query: str,
        search_result: NewsSearchResult,
        context: str,
    ) -> dict[str, str]:
        return {
            "query": query,
            "semantic_query": search_result.semantic_query,
            "response_mode": search_result.response_mode,
            "published_from": (
                search_result.published_from.isoformat()
                if search_result.published_from is not None
                else ""
            ),
            "published_to": (
                search_result.published_to.isoformat()
                if search_result.published_to is not None
                else ""
            ),
            "context": context,
        }

    @staticmethod
    def _build_context(query: str, search_result: NewsSearchResult) -> str:
        response_mode = search_result.response_mode
        hit_limit = (
            NewsAnswerService.DETAIL_HIT_LIMIT
            if response_mode == "detail"
            else NewsAnswerService.OVERVIEW_HIT_LIMIT
        )
        lines: list[str] = []
        for index, hit in enumerate(search_result.hits[:hit_limit], start=1):
            lines.append(f"[{index}] title: {hit.title}")
            lines.append(f"source: {hit.source}")
            lines.append(f"published: {hit.published.isoformat()}")
            lines.append(f"reference_url: {hit.article_url}")
            lines.append(f"distance: {hit.score:.4f}")
            if hit.analysis is not None:
                lines.append("analysis:")
                lines.append(f"- topic: {hit.analysis.topic}")
                lines.append(f"- summary_short: {hit.analysis.summary_short}")
                if response_mode == "detail":
                    lines.append(f"- summary_long: {hit.analysis.summary_long}")
                    lines.append(f"- sentiment: {hit.analysis.sentiment}")
                    lines.append(f"- impact_level: {hit.analysis.impact_level}")
                    lines.append(f"- countries: {', '.join(hit.analysis.countries)}")
                    lines.append(f"- tags: {', '.join(hit.analysis.tags)}")
                    lines.append(f"- instruments: {', '.join(hit.analysis.instruments)}")
            if response_mode == "detail" or hit.analysis is None:
                lines.append("matched_chunks:")
                for chunk in hit.matched_chunks:
                    lines.append(
                        f"- chunk_index={chunk.chunk_index}, distance={chunk.score:.4f}, text={chunk.chunk_text}"
                    )
            lines.append("")
        return "\n".join(lines).strip()
