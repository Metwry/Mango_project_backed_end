from unittest.mock import Mock, patch

import requests
from django.test import TestCase

from ai.llmmodels.model_factory import LLMModelFactory
from ai.llmmodels.model_factory import build_chat_model
from ai.services.content_analysis import AnalysisService
from ai.services.content_embedding import EmbeddingService
from ai.services.content_embedding import EmbeddingResult
from ai.tasks import analyze_pending_news_articles
from ai.models import AIAnalysis
from news.models import NewsArticle


class AnalyzePendingNewsArticlesTests(TestCase):
    def test_only_analyzes_articles_without_existing_analysis(self) -> None:
        analyzed_article = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/already-analyzed.html",
            title="Already analyzed",
            content="Content A",
            content_hash="a" * 32,
            language="en",
            published="2026-03-31T08:00:00Z",
        )
        pending_article = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/pending.html",
            title="Pending",
            content="Content B",
            content_hash="b" * 32,
            language="en",
            published="2026-03-31T09:00:00Z",
        )
        AIAnalysis.objects.create(
            source_type=AIAnalysis.SourceType.NEWS_ARTICLE,
            source_id=analyzed_article.id,
            topic="Topic",
            summary_short="短摘要",
            summary_long="长摘要",
            sentiment="neutral",
            impact_level="low",
            model_name="test-model",
            prompt_name="test-prompt",
            analyzed_at="2026-03-31T08:30:00Z",
        )

        mock_service = Mock()
        with patch("ai.tasks.NewsAnalysisService", return_value=mock_service):
            stats = analyze_pending_news_articles(limit=10)

        self.assertEqual(stats["pending_found"], 1)
        self.assertEqual(stats["analyzed"], 1)
        mock_service.analyze_article.assert_called_once_with(
            pending_article,
            save=True,
            config_overrides=None,
        )


class ChatModelConfigTests(TestCase):
    def test_build_chat_model_passes_openai_reasoning_config(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True), patch(
            "ai.llmmodels.model_factory.ChatOpenAI"
        ) as chat_cls:
            entity = build_chat_model(
                {
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "api_key_env": "OPENAI_API_KEY",
                    "temperature": 0,
                    "timeout": 60,
                    "max_retries": 2,
                    "reasoning_effort": "low",
                    "verbosity": "low",
                    "max_tokens": 600,
                }
            )

        kwargs = chat_cls.call_args.kwargs
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["verbosity"], "low")
        self.assertEqual(kwargs["max_tokens"], 600)
        self.assertIs(entity, chat_cls.return_value)

    def test_build_chat_model_passes_openai_api_key(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True), patch(
            "ai.llmmodels.model_factory.ChatOpenAI"
        ) as chat_cls:
            build_chat_model(
                {
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "api_key_env": "OPENAI_API_KEY",
                    "temperature": 0,
                    "timeout": 60,
                    "max_retries": 2,
                    "reasoning_effort": "none",
                    "verbosity": "low",
                    "max_tokens": 600,
                }
            )

        kwargs = chat_cls.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "test-key")

    def test_build_chat_model_passes_aliyun_thinking_config(self) -> None:
        with patch.dict("os.environ", {"ALI_API_KEY": "test-key"}, clear=True), patch(
            "ai.llmmodels.model_factory.ChatTongyi"
        ) as chat_cls:
            entity = build_chat_model(
                {
                    "provider": "aliyun",
                    "model": "qwen-plus",
                    "api_key_env": "ALI_API_KEY",
                    "temperature": 0,
                    "timeout": 60,
                    "max_retries": 2,
                    "enable_thinking": False,
                    "thinking_budget": 256,
                    "max_tokens": 600,
                }
            )

        kwargs = chat_cls.call_args.kwargs
        self.assertEqual(
            kwargs["model_kwargs"],
            {
                "enable_thinking": False,
                "thinking_budget": 256,
                "max_tokens": 600,
            },
        )
        self.assertIs(entity, chat_cls.return_value)


class AnalysisRuntimeTests(TestCase):
    def test_analysis_service_retries_aliyun_retryable_error(self) -> None:
        chat_client = Mock()
        chat_client.invoke.side_effect = [
            requests.exceptions.SSLError("ssl eof"),
            Mock(
                content='{"semantic_query":"hello","published_from":null,"published_to":null,"response_mode":"overview"}'
            ),
        ]

        service = AnalysisService()

        with patch("ai.utils.llm_runtime.time.sleep") as sleep_mock, patch(
            "ai.services.content_analysis.LLMModelFactory.create_chat_model",
            return_value=chat_client,
        ):
            result = service.analyze(
                task_name="news_analysis",
                variables={
                    "provider": "yahoo",
                    "source": "Reuters",
                    "title": "hello",
                    "content": "hello",
                    "language": "en",
                    "published": "2026-04-02T00:00:00+08:00",
                },
                config_overrides={"provider": "aliyun", "model": "qwen-plus"},
            )

        self.assertEqual(result.data["topic"], "AI")
        self.assertEqual(chat_client.invoke.call_count, 2)
        sleep_mock.assert_called_once()

    def test_analysis_service_does_not_retry_non_retryable_error(self) -> None:
        chat_client = Mock()
        chat_client.invoke.side_effect = ValueError("bad request")
        service = AnalysisService()

        with patch(
            "ai.services.content_analysis.LLMModelFactory.create_chat_model",
            return_value=chat_client,
        ), self.assertRaises(ValueError):
            service.analyze(
                task_name="news_analysis",
                variables={
                    "provider": "yahoo",
                    "source": "Reuters",
                    "title": "hello",
                    "content": "hello",
                    "language": "en",
                    "published": "2026-04-02T00:00:00+08:00",
                },
                config_overrides={"provider": "aliyun", "model": "qwen-plus"},
            )


class AnalysisServiceFactoryTests(TestCase):
    def test_analysis_service_uses_factory_rendered_prompt(self) -> None:
        service = AnalysisService()
        mock_chat_model = Mock()
        mock_chat_model.invoke.return_value = Mock(
            content='{"topic":"AI","summary_short":"短","summary_long":"长","sentiment":"neutral","impact_level":"low","countries":[],"tags":[],"instrument_candidates":[]}'
        )

        with patch(
            "ai.services.content_analysis.LLMModelFactory.create_chat_model",
            return_value=mock_chat_model,
        ):
            result = service.analyze(
                task_name="news_analysis",
                variables={
                    "provider": "yahoo",
                    "source": "Reuters",
                    "title": "Test title",
                    "content": "Test content",
                    "language": "en",
                    "published": "2026-04-01T00:00:00+00:00",
                },
                config_overrides=None,
            )

        self.assertEqual(result.data["topic"], "AI")
        self.assertEqual(mock_chat_model.invoke.call_count, 1)
        prompt_text = mock_chat_model.invoke.call_args.args[0]
        self.assertIn("Test title", prompt_text)
        self.assertIn("Test content", prompt_text)


class LLMModelFactoryTests(TestCase):
    def test_create_chat_model_returns_client(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True):
            model = LLMModelFactory.create_chat_model(
                task_name="news_agent",
            )

        self.assertIsNotNone(model)

    def test_create_embedding_model_returns_client(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True):
            model = LLMModelFactory.create_embedding_model(
                task_name="news_article_embedding",
            )

        self.assertIsNotNone(model)


class EmbeddingServiceTests(TestCase):
    def test_embedding_service_uses_factory_and_returns_vectors(self) -> None:
        service = EmbeddingService()
        mock_embedding_model = Mock()
        mock_embedding_model.embeddings.create.return_value = Mock(
            data=[Mock(embedding=[0.1, 0.2])]
        )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True), patch(
            "ai.services.content_embedding.LLMModelFactory.create_embedding_model",
            return_value=mock_embedding_model,
        ):
            result = service.embed(
                task_name="news_article_embedding",
                texts=["Title: Test\n\nContent:\nTest content"],
                config_overrides={
                    "provider": "openai",
                    "models": {
                        "aliyun": "text-embedding-v4",
                        "openai": "text-embedding-3-small",
                    },
                },
            )

        self.assertEqual(result.model_name, "text-embedding-3-small")
        self.assertEqual(result.vectors, [[0.1, 0.2]])
        mock_embedding_model.embeddings.create.assert_called_once()

    def test_embedding_service_batches_requests(self) -> None:
        service = EmbeddingService()
        mock_embedding_model = Mock()
        mock_embedding_model.embeddings.create.side_effect = [
            Mock(data=[Mock(embedding=[0.1]), Mock(embedding=[0.2])]),
            Mock(data=[Mock(embedding=[0.3])]),
        ]

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True), patch(
            "ai.services.content_embedding.LLMModelFactory.create_embedding_model",
            return_value=mock_embedding_model,
        ):
            result = service.embed(
                task_name="news_article_embedding",
                texts=["a", "b", "c"],
                config_overrides={
                    "batch_size": 2,
                    "provider": "openai",
                    "models": {
                        "aliyun": "text-embedding-v4",
                        "openai": "text-embedding-v4",
                    },
                },
            )

        self.assertEqual(result.model_name, "text-embedding-v4")
        self.assertEqual(result.vectors, [[0.1], [0.2], [0.3]])
        self.assertEqual(mock_embedding_model.embeddings.create.call_count, 2)
