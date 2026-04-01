from django.test import TestCase
from unittest.mock import Mock, patch

import requests

from ai.llmmodels import LLMModelFactory
from ai.llmmodels.aliyun_chat import AliyunChatModel
from ai.llmmodels.base_model import EmbeddingResult
from ai.models import AIAnalysis
from ai.services import AnalysisService, EmbeddingService
from ai.tasks import analyze_pending_news_articles
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


class AliyunChatModelRetryTests(TestCase):
    def test_invoke_with_retries_succeeds_after_retryable_error(self) -> None:
        model = AliyunChatModel(
            model_name="qwen-plus",
            api_key="test-key",
            task_config={"network_retry_attempts": 3, "network_retry_base_delay": 0.1},
        )
        chain = Mock()
        chain.invoke.side_effect = [
            requests.exceptions.SSLError("ssl eof"),
            "ok",
        ]

        with patch.object(model, "llm", Mock()), patch("ai.llmmodels.aliyun_chat.time.sleep") as sleep_mock:
            result = model._invoke_with_retries(chain=chain)

        self.assertEqual(result, "ok")
        self.assertEqual(chain.invoke.call_count, 2)
        sleep_mock.assert_called_once()

    def test_invoke_with_retries_does_not_retry_non_retryable_error(self) -> None:
        model = AliyunChatModel(
            model_name="qwen-plus",
            api_key="test-key",
            task_config={"network_retry_attempts": 3, "network_retry_base_delay": 0.1},
        )
        chain = Mock()
        chain.invoke.side_effect = ValueError("bad request")

        with self.assertRaises(ValueError):
            model._invoke_with_retries(chain=chain)


class ChatModelConfigTests(TestCase):
    def test_openai_chat_model_passes_reasoning_config(self) -> None:
        with patch("ai.llmmodels.openai_chat.ChatOpenAI") as chat_cls:
            from ai.llmmodels.openai_chat import OpenAIChatModel

            OpenAIChatModel(
                model_name="gpt-5.4-mini",
                api_key="test-key",
                task_config={
                    "reasoning_effort": "low",
                    "verbosity": "low",
                    "max_tokens": 600,
                },
            )

        kwargs = chat_cls.call_args.kwargs
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["verbosity"], "low")
        self.assertEqual(kwargs["max_tokens"], 600)

    def test_openai_chat_model_passes_base_url_when_provided(self) -> None:
        with patch("ai.llmmodels.openai_chat.ChatOpenAI") as chat_cls:
            from ai.llmmodels.openai_chat import OpenAIChatModel

            OpenAIChatModel(
                model_name="qwen3:14b",
                api_key="",
                base_url="http://127.0.0.1:11434/v1",
                task_config={},
            )

        kwargs = chat_cls.call_args.kwargs
        self.assertEqual(kwargs["base_url"], "http://127.0.0.1:11434/v1")
        self.assertNotIn("api_key", kwargs)

    def test_aliyun_chat_model_passes_thinking_config(self) -> None:
        with patch("ai.llmmodels.aliyun_chat.ChatTongyi") as chat_cls:
            AliyunChatModel(
                model_name="qwen-plus",
                api_key="test-key",
                task_config={
                    "enable_thinking": False,
                    "thinking_budget": 256,
                    "max_tokens": 600,
                },
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


class AnalysisServiceFactoryTests(TestCase):
    def test_analysis_service_uses_factory_rendered_prompt(self) -> None:
        service = AnalysisService()
        mock_chat_model = Mock()
        mock_chat_model.generate.return_value.raw_text = '{"topic":"AI","summary_short":"短","summary_long":"长","sentiment":"neutral","impact_level":"low","countries":[],"tags":[],"instrument_candidates":[]}'

        with patch("ai.services.analysis.LLMModelFactory.create_chat_model", return_value=mock_chat_model):
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
                config_overrides={"provider": "openai"},
            )

        self.assertEqual(result.data["topic"], "AI")
        prompt_text = mock_chat_model.generate.call_args.kwargs["prompt_text"]
        self.assertIn("Test title", prompt_text)
        self.assertIn("Test content", prompt_text)


class LLMModelFactoryTests(TestCase):
    def test_resolve_api_key_raises_when_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                LLMModelFactory.resolve_api_key(provider_name="openai")

    def test_resolve_api_key_returns_empty_when_provider_does_not_need_it(self) -> None:
        with patch.dict("os.environ", {"OLLAMA_BASE_URL": "http://127.0.0.1:11434/v1"}, clear=True):
            api_key = LLMModelFactory.resolve_api_key(provider_name="ollama")

        self.assertEqual(api_key, "")

    def test_create_chat_model_returns_openai_chat_model_for_ollama(self) -> None:
        with patch.dict("os.environ", {"OLLAMA_BASE_URL": "http://127.0.0.1:11434/v1"}, clear=True):
            model = LLMModelFactory.create_chat_model(
                provider_name="ollama",
                model_name="qwen3:14b",
                task_config={},
            )

        self.assertEqual(model.__class__.__name__, "OpenAIChatModel")

    def test_create_embedding_model_returns_openai_model(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True):
            model = LLMModelFactory.create_embedding_model(
                provider_name="openai",
                model_name="text-embedding-3-small",
                task_config={},
            )

        self.assertEqual(model.__class__.__name__, "OpenAIEmbeddingModel")


class EmbeddingServiceTests(TestCase):
    def test_embedding_service_uses_factory_and_returns_vectors(self) -> None:
        service = EmbeddingService()
        mock_embedding_model = Mock()
        mock_embedding_model.embed.return_value = EmbeddingResult(
            model_name="text-embedding-3-small",
            vectors=[[0.1, 0.2]],
        )

        with patch(
            "ai.services.embedding.LLMModelFactory.create_embedding_model",
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
        mock_embedding_model.embed.assert_called_once_with(
            texts=["Title: Test\n\nContent:\nTest content"]
        )

    def test_embedding_service_batches_requests(self) -> None:
        service = EmbeddingService()
        mock_embedding_model = Mock()
        mock_embedding_model.embed.side_effect = [
            EmbeddingResult(model_name="text-embedding-v4", vectors=[[0.1], [0.2]]),
            EmbeddingResult(model_name="text-embedding-v4", vectors=[[0.3]]),
        ]

        with patch(
            "ai.services.embedding.LLMModelFactory.create_embedding_model",
            return_value=mock_embedding_model,
        ):
            result = service.embed(
                task_name="news_article_embedding",
                texts=["a", "b", "c"],
                config_overrides={
                    "batch_size": 2,
                    "provider": "aliyun",
                    "models": {
                        "aliyun": "text-embedding-v4",
                        "openai": "text-embedding-3-small",
                    },
                },
            )

        self.assertEqual(result.model_name, "text-embedding-v4")
        self.assertEqual(result.vectors, [[0.1], [0.2], [0.3]])
        self.assertEqual(mock_embedding_model.embed.call_count, 2)
        self.assertEqual(
            mock_embedding_model.embed.call_args_list[0].kwargs,
            {"texts": ["a", "b"]},
        )
        self.assertEqual(
            mock_embedding_model.embed.call_args_list[1].kwargs,
            {"texts": ["c"]},
        )
