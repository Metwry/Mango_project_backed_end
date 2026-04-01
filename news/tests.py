import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiohttp
from django.test import SimpleTestCase
from django.test import TestCase
from django.utils import timezone

from ai.models import AIAnalysis, AIAnalysisCountry, AIAnalysisInstrument, AIAnalysisTag
from market.models import Instrument
from news.models import NewsArticle, NewsArticleEmbedding
from news.service.hash_utils import calculate_content_md5, normalize_content_for_hash
from news.service.news_content_cleanup import NewsContentCleanupService, clean_stored_article_content
from news.service.news_answer import NewsAnswerService
from news.service.news_embedding import NewsArticleEmbeddingService
from news.service.news_ingest_service import YahooNewsIngestService
from news.service.query_understanding import QueryUnderstandingService
from news.service.news_search import NewsSearchService
from news.service.yahoo_news import (
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    YahooNewsArticle,
    extract_article_blocks,
    fetch_text,
    render_blocks_text,
)


class YahooNewsParsingTests(SimpleTestCase):
    def test_extract_article_blocks_preserves_structured_content(self) -> None:
        page_html = """
        <html>
          <body>
            <article>
              <h1>Sample Title</h1>
              <p>Intro paragraph.</p>
              <h2>Highlights</h2>
              <ul>
                <li>First point</li>
                <li>Second point</li>
              </ul>
              <table>
                <tr>
                  <th>Lender</th>
                  <th>Maximum amount</th>
                </tr>
                <tr>
                  <td>Best Egg</td>
                  <td>$50,000</td>
                </tr>
              </table>
              <p>This article was originally published by Example.</p>
            </article>
          </body>
        </html>
        """

        blocks = extract_article_blocks(page_html, article_title="Sample Title")

        self.assertIsInstance(blocks[0], ParagraphBlock)
        self.assertIsInstance(blocks[1], HeadingBlock)
        self.assertIsInstance(blocks[2], ListBlock)
        self.assertIsInstance(blocks[3], TableBlock)

        content = render_blocks_text(blocks)
        self.assertIn("Intro paragraph.", content)
        self.assertIn("## Highlights", content)
        self.assertIn("- First point", content)
        self.assertIn("| Lender | Maximum amount |", content)
        self.assertIn("| Best Egg | $50,000 |", content)
        self.assertNotIn("originally published", content.lower())


class YahooNewsHashUtilsTests(SimpleTestCase):
    def test_normalize_content_for_hash_cleans_whitespace(self) -> None:
        content = "Line 1  \r\n\r\n   Line 2\t\tword  "
        self.assertEqual(normalize_content_for_hash(content), "Line 1\nLine 2 word")

    def test_calculate_content_md5_is_stable_for_spacing_differences(self) -> None:
        left = "Alpha  \n\nBeta"
        right = "Alpha\nBeta   "
        self.assertEqual(calculate_content_md5(left), calculate_content_md5(right))


class YahooNewsFetchRetryTests(SimpleTestCase):
    def test_fetch_text_retries_after_payload_error(self) -> None:
        response = AsyncMock()
        response.__aenter__.return_value = response
        response.raise_for_status = Mock()
        response.text = AsyncMock(return_value="ok")

        session = Mock()
        session.get.side_effect = [
            aiohttp.ClientPayloadError("partial"),
            response,
        ]

        with patch("news.service.yahoo_news.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            result = asyncio.run(fetch_text(session, "https://finance.yahoo.com/news/rss"))

        self.assertEqual(result, "ok")
        self.assertEqual(session.get.call_count, 2)
        sleep_mock.assert_awaited_once()

    def test_fetch_text_raises_after_retry_exhausted(self) -> None:
        session = Mock()
        session.get.side_effect = aiohttp.ClientPayloadError("partial")

        with patch("news.service.yahoo_news.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(aiohttp.ClientPayloadError):
                asyncio.run(
                    fetch_text(
                        session,
                        "https://finance.yahoo.com/news/rss",
                        retry_attempts=2,
                        retry_base_delay=0,
                    )
                )


class YahooNewsIngestServiceTests(TestCase):
    def test_ingest_keeps_article_when_analysis_fails(self) -> None:
        analysis_service = Mock()
        analysis_service.analyze_article.side_effect = ValueError("prompt error")
        service = YahooNewsIngestService(news_analysis_service=analysis_service)
        article = YahooNewsArticle(
            title="BTC slips",
            link="https://finance.yahoo.com/news/btc-slips.html",
            published_at="2026-03-31T15:06:24Z",
            source="Yahoo Finance",
            content="Bitcoin edged lower after a broad risk-off move.",
        )

        with patch(
            "news.service.news_ingest_service.fetch_yahoo_finance_articles_sync",
            return_value=[article],
        ):
            stats = service.ingest_latest(limit=1)

        self.assertEqual(stats.created, 1)
        self.assertEqual(stats.failed_analysis, 1)
        self.assertEqual(NewsArticle.objects.count(), 1)

    def test_parse_published_at_supports_iso8601(self) -> None:
        parsed = YahooNewsIngestService._parse_published_at("2026-03-31T15:06:24Z")
        self.assertEqual(parsed.isoformat(), "2026-03-31T15:06:24+00:00")

    def test_ingest_creates_article_and_runs_analysis(self) -> None:
        analysis_service = Mock()
        service = YahooNewsIngestService(news_analysis_service=analysis_service)
        article = YahooNewsArticle(
            title="Chip stocks rally",
            link="https://finance.yahoo.com/news/chip-stocks-rally-1.html",
            published_at="Tue, 31 Mar 2026 08:00:00 GMT",
            source="Reuters",
            content="Nvidia and AMD rose after strong AI demand signals.",
        )

        with patch(
            "news.service.news_ingest_service.fetch_yahoo_finance_articles_sync",
            return_value=[article],
        ):
            stats = service.ingest_latest(limit=1)

        self.assertEqual(stats.fetched, 1)
        self.assertEqual(stats.created, 1)
        self.assertEqual(stats.analyzed, 1)
        self.assertEqual(NewsArticle.objects.count(), 1)
        saved = NewsArticle.objects.get()
        self.assertEqual(saved.article_url, article.link)
        self.assertEqual(saved.content_hash, calculate_content_md5(article.content))
        analysis_service.analyze_article.assert_called_once_with(
            saved,
            save=True,
            config_overrides=None,
        )

    def test_ingest_skips_duplicate_content_from_different_url(self) -> None:
        analysis_service = Mock()
        service = YahooNewsIngestService(news_analysis_service=analysis_service)
        content = "Treasury yields were steady as investors awaited inflation data."
        NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/original-article.html",
            title="Original",
            content=content,
            content_hash=calculate_content_md5(content),
            language="en",
            published="2026-03-31T08:00:00Z",
        )
        article = YahooNewsArticle(
            title="Duplicate",
            link="https://finance.yahoo.com/news/duplicate-article.html",
            published_at="Tue, 31 Mar 2026 08:00:00 GMT",
            source="Yahoo Finance",
            content=content,
        )

        with patch(
            "news.service.news_ingest_service.fetch_yahoo_finance_articles_sync",
            return_value=[article],
        ):
            stats = service.ingest_latest(limit=1)

        self.assertEqual(stats.duplicate_content, 1)
        self.assertEqual(stats.created, 0)
        self.assertEqual(NewsArticle.objects.count(), 1)
        analysis_service.analyze_article.assert_not_called()

    def test_ingest_existing_article_skips_analysis_when_unchanged(self) -> None:
        analysis_service = Mock()
        service = YahooNewsIngestService(news_analysis_service=analysis_service)
        content = "Oil prices held steady after OPEC comments."
        existing = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/oil-prices.html",
            title="Oil prices",
            content=content,
            content_hash=calculate_content_md5(content),
            language="en",
            published="2026-03-31T08:00:00Z",
        )
        AIAnalysis.objects.create(
            source_type=AIAnalysis.SourceType.NEWS_ARTICLE,
            source_id=existing.id,
            topic="Energy",
            summary_short="短摘要",
            summary_long="长摘要",
            sentiment="neutral",
            impact_level="low",
            model_name="test-model",
            prompt_name="test-prompt",
            analyzed_at="2026-03-31T08:30:00Z",
        )
        article = YahooNewsArticle(
            title="Oil prices",
            link=existing.article_url,
            published_at="Tue, 31 Mar 2026 08:00:00 GMT",
            source="Reuters",
            content=content,
        )

        with patch(
            "news.service.news_ingest_service.fetch_yahoo_finance_articles_sync",
            return_value=[article],
        ):
            stats = service.ingest_latest(limit=1)

        self.assertEqual(stats.updated, 1)
        self.assertEqual(stats.skipped_analysis, 1)
        analysis_service.analyze_article.assert_not_called()


class NewsArticleEmbeddingServiceTests(TestCase):
    def test_build_chunks_splits_by_paragraphs(self) -> None:
        content = "Para1.\n\nPara2 is a bit longer.\n\nPara3 ends here."

        chunks = NewsArticleEmbeddingService._build_chunks(
            content=content,
            max_chars=25,
            overlap_chars=5,
        )

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].index, 0)
        self.assertTrue(all(chunk.text for chunk in chunks))

    def test_tail_overlap_prefers_natural_boundary(self) -> None:
        overlap = NewsArticleEmbeddingService._tail_overlap(
            "Let's review the uses, risks, growth drivers, and investment purposes so you know what to expect before you buy.",
            overlap_chars=30,
        )

        self.assertFalse(overlap.startswith("o "))
        self.assertFalse(overlap.startswith("uy"))
        self.assertTrue(overlap.startswith("to ") or overlap.startswith("you") or overlap.startswith("what"))

    def test_embed_article_rebuilds_embeddings(self) -> None:
        article = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/embed-test.html",
            title="Embed test",
            content="First paragraph.\n\nSecond paragraph.",
            content_hash=calculate_content_md5("First paragraph.\n\nSecond paragraph."),
            language="en",
            published="2026-04-01T08:00:00Z",
        )
        service = NewsArticleEmbeddingService()
        vector = [0.1] * 1536

        with patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-3-small", vectors=[vector]),
        ):
            stats = service.embed_article(
                article,
                config_overrides={
                    "provider": "openai",
                    "models": {
                        "aliyun": "text-embedding-v4",
                        "openai": "text-embedding-3-small",
                    },
                    "chunk": {
                        "max_chars": 500,
                        "overlap_chars": 50,
                        "include_title": True,
                    },
                },
            )

        self.assertEqual(stats.article_id, article.id)
        self.assertEqual(stats.chunk_count, 1)
        self.assertEqual(NewsArticleEmbedding.objects.count(), 1)
        saved = NewsArticleEmbedding.objects.get()
        self.assertEqual(saved.article_id, article.id)
        self.assertEqual(saved.chunk_index, 0)
        self.assertEqual(saved.embedding_model, "text-embedding-3-small")


class NewsContentCleanupServiceTests(TestCase):
    def test_clean_stored_article_content_removes_advertiser_disclosure(self) -> None:
        content = (
            "Some offers on this page are from advertisers who pay us, which may affect which "
            "products we write about, but not our recommendations. See our Advertiser Disclosure .\n\n"
            "Precious metals are in high demand."
        )

        cleaned = clean_stored_article_content(content)

        self.assertEqual(cleaned, "Precious metals are in high demand.")

    def test_clean_articles_updates_content_hash_and_clears_embeddings(self) -> None:
        original_content = (
            "Some offers on this page are from advertisers who pay us, which may affect which "
            "products we write about, but not our recommendations. See our Advertiser Disclosure .\n\n"
            "Useful paragraph."
        )
        article = NewsArticle.objects.create(
            provider="yahoo",
            source="Yahoo Personal Finance",
            article_url="https://finance.yahoo.com/news/cleanup-test.html",
            title="Cleanup test",
            content=original_content,
            content_hash=calculate_content_md5(original_content),
            language="en",
            published="2026-04-01T08:00:00Z",
        )
        NewsArticleEmbedding.objects.create(
            article=article,
            chunk_index=0,
            chunk_text="stale",
            chunk_hash=calculate_content_md5("stale"),
            title=article.title,
            source=article.source,
            published=article.published,
            embedding_model="text-embedding-3-small",
            embedding=[0.1] * 1536,
        )

        stats = NewsContentCleanupService().clean_articles()

        article.refresh_from_db()
        self.assertEqual(stats.updated, 1)
        self.assertEqual(stats.cleared_embeddings, 1)
        self.assertEqual(article.content, "Useful paragraph.")
        self.assertEqual(article.content_hash, calculate_content_md5("Useful paragraph."))
        self.assertEqual(NewsArticleEmbedding.objects.filter(article=article).count(), 0)


class QueryUnderstandingServiceTests(TestCase):
    def test_understand_parses_semantic_query_and_time_range(self) -> None:
        service = QueryUnderstandingService()
        with patch.object(
            service.analysis_service,
            "analyze",
            return_value=Mock(
                data={
                    "semantic_query": "bitcoin price weakness",
                    "published_from": "2026-03-25T00:00:00+08:00",
                    "published_to": "2026-04-01T23:59:59+08:00",
                    "response_mode": "detail",
                }
            ),
        ):
            plan = service.understand(
                query="最近比特币为什么跌",
                timezone_name="Asia/Shanghai",
                now=datetime.fromisoformat("2026-04-01T12:00:00+08:00"),
            )

        self.assertEqual(plan.raw_query, "最近比特币为什么跌")
        self.assertEqual(plan.semantic_query, "bitcoin price weakness")
        self.assertEqual(plan.published_from.isoformat(), "2026-03-25T00:00:00+08:00")
        self.assertEqual(plan.published_to.isoformat(), "2026-04-01T23:59:59+08:00")
        self.assertEqual(plan.response_mode, "detail")

    def test_understand_falls_back_when_analysis_fails(self) -> None:
        service = QueryUnderstandingService()
        with patch.object(service.analysis_service, "analyze", side_effect=ValueError("bad prompt")):
            plan = service.understand(query="bitcoin weakness")

        self.assertEqual(plan.raw_query, "bitcoin weakness")
        self.assertEqual(plan.semantic_query, "bitcoin weakness")
        self.assertIsNone(plan.published_from)
        self.assertIsNone(plan.published_to)
        self.assertEqual(plan.response_mode, "overview")


class NewsSearchServiceTests(TestCase):
    def test_search_returns_best_matching_articles(self) -> None:
        article_a = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/bitcoin-search-a.html",
            title="Bitcoin selloff deepens",
            content="Bitcoin slid as risk appetite faded.",
            content_hash=calculate_content_md5("Bitcoin slid as risk appetite faded."),
            language="en",
            published="2026-04-01T08:00:00Z",
        )
        article_b = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/gold-search-b.html",
            title="Gold steadies",
            content="Gold held firm while traders watched inflation.",
            content_hash=calculate_content_md5("Gold held firm while traders watched inflation."),
            language="en",
            published="2026-04-01T09:00:00Z",
        )
        NewsArticleEmbedding.objects.create(
            article=article_a,
            chunk_index=0,
            chunk_text="Bitcoin slid as risk appetite faded.",
            chunk_hash=calculate_content_md5("Bitcoin slid as risk appetite faded."),
            title=article_a.title,
            source=article_a.source,
            published=article_a.published,
            embedding_model="text-embedding-v4",
            embedding=[1.0] + [0.0] * 1535,
        )
        NewsArticleEmbedding.objects.create(
            article=article_b,
            chunk_index=0,
            chunk_text="Gold held firm while traders watched inflation.",
            chunk_hash=calculate_content_md5("Gold held firm while traders watched inflation."),
            title=article_b.title,
            source=article_b.source,
            published=article_b.published,
            embedding_model="text-embedding-v4",
            embedding=[0.0, 1.0] + [0.0] * 1534,
        )

        service = NewsSearchService()
        with patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-v4", vectors=[[1.0] + [0.0] * 1535]),
        ), patch.object(
            service.query_understanding_service,
            "understand",
            return_value=Mock(
                semantic_query="bitcoin weakness",
                published_from=None,
                published_to=None,
            ),
        ):
            result = service.search(query="bitcoin weakness", top_k=2, max_distance=None)

        self.assertEqual(result.query, "bitcoin weakness")
        self.assertEqual(result.semantic_query, "bitcoin weakness")
        self.assertEqual(len(result.hits), 2)
        self.assertEqual(result.response_mode, "overview")
        self.assertEqual(result.hits[0].article_id, article_a.id)
        self.assertEqual(result.hits[0].article_url, article_a.article_url)
        self.assertLess(result.hits[0].score, result.hits[1].score)
        self.assertEqual(len(result.hits[0].matched_chunks), 1)
        self.assertIsNone(result.hits[0].analysis)

    def test_search_deduplicates_multiple_hits_from_same_article(self) -> None:
        article = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/bitcoin-search-c.html",
            title="Bitcoin pressure persists",
            content="Bitcoin fell and risk sentiment weakened.",
            content_hash=calculate_content_md5("Bitcoin fell and risk sentiment weakened."),
            language="en",
            published="2026-04-01T10:00:00Z",
        )
        other_article = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/other-search-d.html",
            title="Oil jumps",
            content="Oil rose as conflict spread.",
            content_hash=calculate_content_md5("Oil rose as conflict spread."),
            language="en",
            published="2026-04-01T11:00:00Z",
        )
        NewsArticleEmbedding.objects.create(
            article=article,
            chunk_index=0,
            chunk_text="Bitcoin fell sharply.",
            chunk_hash=calculate_content_md5("Bitcoin fell sharply."),
            title=article.title,
            source=article.source,
            published=article.published,
            embedding_model="text-embedding-v4",
            embedding=[1.0] + [0.0] * 1535,
        )
        NewsArticleEmbedding.objects.create(
            article=article,
            chunk_index=1,
            chunk_text="Risk sentiment worsened.",
            chunk_hash=calculate_content_md5("Risk sentiment worsened."),
            title=article.title,
            source=article.source,
            published=article.published,
            embedding_model="text-embedding-v4",
            embedding=[0.9] + [0.0] * 1535,
        )
        NewsArticleEmbedding.objects.create(
            article=other_article,
            chunk_index=0,
            chunk_text="Oil rose as conflict spread.",
            chunk_hash=calculate_content_md5("Oil rose as conflict spread."),
            title=other_article.title,
            source=other_article.source,
            published=other_article.published,
            embedding_model="text-embedding-v4",
            embedding=[0.0, 1.0] + [0.0] * 1534,
        )

        service = NewsSearchService()
        with patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-v4", vectors=[[1.0] + [0.0] * 1535]),
        ), patch.object(
            service.query_understanding_service,
            "understand",
            return_value=Mock(
                semantic_query="bitcoin decline",
                published_from=None,
                published_to=None,
            ),
        ):
            result = service.search(query="bitcoin decline", top_k=2, max_distance=None)

        self.assertEqual(len(result.hits), 2)
        self.assertEqual(result.hits[0].article_id, article.id)
        self.assertEqual(result.hits[0].chunk_index, 0)
        self.assertEqual(len(result.hits[0].matched_chunks), 2)
        self.assertEqual(result.hits[0].matched_chunks[0].chunk_index, 0)
        self.assertEqual(result.hits[0].matched_chunks[1].chunk_index, 1)
        self.assertEqual(result.hits[1].article_id, other_article.id)
        self.assertIsNone(result.hits[0].analysis)

    def test_search_filters_hits_above_max_distance(self) -> None:
        article = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/filter-search-e.html",
            title="Distant result",
            content="A weakly related article.",
            content_hash=calculate_content_md5("A weakly related article."),
            language="en",
            published="2026-04-01T12:00:00Z",
        )
        NewsArticleEmbedding.objects.create(
            article=article,
            chunk_index=0,
            chunk_text="A weakly related article.",
            chunk_hash=calculate_content_md5("A weakly related article."),
            title=article.title,
            source=article.source,
            published=article.published,
            embedding_model="text-embedding-v4",
            embedding=[0.0, 1.0] + [0.0] * 1534,
        )

        service = NewsSearchService()
        with patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-v4", vectors=[[1.0] + [0.0] * 1535]),
        ), patch.object(
            service.query_understanding_service,
            "understand",
            return_value=Mock(
                semantic_query="bitcoin",
                published_from=None,
                published_to=None,
            ),
        ):
            result = service.search(query="bitcoin", top_k=5, max_distance=0.7)

        self.assertEqual(result.hits, [])

    def test_search_attaches_latest_ai_analysis(self) -> None:
        article = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/analysis-search-f.html",
            title="Bitcoin analysis article",
            content="Bitcoin weakened as traders reduced risk.",
            content_hash=calculate_content_md5("Bitcoin weakened as traders reduced risk."),
            language="en",
            published="2026-04-01T13:00:00Z",
        )
        instrument = Instrument.objects.create(
            symbol="BTCUSDT.CRYPTO",
            short_code="BTCUSDT",
            name="Bitcoin",
            asset_class=Instrument.AssetClass.CRYPTO,
            market=Instrument.Market.CRYPTO,
        )
        NewsArticleEmbedding.objects.create(
            article=article,
            chunk_index=0,
            chunk_text="Bitcoin weakened as traders reduced risk.",
            chunk_hash=calculate_content_md5("Bitcoin weakened as traders reduced risk."),
            title=article.title,
            source=article.source,
            published=article.published,
            embedding_model="text-embedding-v4",
            embedding=[1.0] + [0.0] * 1535,
        )
        old_analysis = AIAnalysis.objects.create(
            source_type=AIAnalysis.SourceType.NEWS_ARTICLE,
            source_id=article.id,
            topic="Old Topic",
            summary_short="Old short",
            summary_long="Old long",
            sentiment="neutral",
            impact_level="low",
            model_name="old-model",
            prompt_name="old-prompt",
            analyzed_at="2026-04-01T12:00:00Z",
        )
        new_analysis = AIAnalysis.objects.create(
            source_type=AIAnalysis.SourceType.NEWS_ARTICLE,
            source_id=article.id,
            topic="Bitcoin Weakness",
            summary_short="Bitcoin weakened on risk-off sentiment.",
            summary_long="Bitcoin prices softened as traders reduced exposure and crypto sentiment weakened.",
            sentiment="negative",
            impact_level="medium",
            model_name="new-model",
            prompt_name="news_analysis",
            analyzed_at="2026-04-01T14:00:00Z",
        )
        AIAnalysisCountry.objects.create(ai_analysis=new_analysis, country_name="United States")
        AIAnalysisTag.objects.create(ai_analysis=new_analysis, tag_name="Crypto")
        AIAnalysisInstrument.objects.create(ai_analysis=new_analysis, instrument=instrument)
        AIAnalysisTag.objects.create(ai_analysis=old_analysis, tag_name="Stale")

        service = NewsSearchService()
        with patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-v4", vectors=[[1.0] + [0.0] * 1535]),
        ), patch.object(
            service.query_understanding_service,
            "understand",
            return_value=Mock(
                semantic_query="bitcoin weakness",
                published_from=None,
                published_to=None,
            ),
        ):
            result = service.search(query="bitcoin weakness", top_k=1, max_distance=None)

        self.assertEqual(len(result.hits), 1)
        self.assertIsNotNone(result.hits[0].analysis)
        self.assertEqual(result.hits[0].analysis.topic, "Bitcoin Weakness")
        self.assertEqual(result.hits[0].analysis.sentiment, "negative")
        self.assertEqual(result.hits[0].analysis.countries, ["United States"])
        self.assertEqual(result.hits[0].analysis.tags, ["Crypto"])
        self.assertEqual(result.hits[0].analysis.instruments, ["BTCUSDT.CRYPTO"])

    def test_search_uses_query_plan_for_embedding_and_time_filter(self) -> None:
        article_in_range = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/time-search-g.html",
            title="Bitcoin recent article",
            content="Bitcoin weakness continued.",
            content_hash=calculate_content_md5("Bitcoin weakness continued."),
            language="en",
            published="2026-03-30T12:00:00Z",
        )
        article_out_of_range = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/time-search-h.html",
            title="Bitcoin old article",
            content="Older bitcoin weakness article.",
            content_hash=calculate_content_md5("Older bitcoin weakness article."),
            language="en",
            published="2026-02-01T12:00:00Z",
        )
        NewsArticleEmbedding.objects.create(
            article=article_in_range,
            chunk_index=0,
            chunk_text="Bitcoin weakness continued.",
            chunk_hash=calculate_content_md5("Bitcoin weakness continued."),
            title=article_in_range.title,
            source=article_in_range.source,
            published=article_in_range.published,
            embedding_model="text-embedding-v4",
            embedding=[1.0] + [0.0] * 1535,
        )
        NewsArticleEmbedding.objects.create(
            article=article_out_of_range,
            chunk_index=0,
            chunk_text="Older bitcoin weakness article.",
            chunk_hash=calculate_content_md5("Older bitcoin weakness article."),
            title=article_out_of_range.title,
            source=article_out_of_range.source,
            published=article_out_of_range.published,
            embedding_model="text-embedding-v4",
            embedding=[1.0] + [0.0] * 1535,
        )

        service = NewsSearchService()
        with patch.object(
            service.query_understanding_service,
            "understand",
            return_value=Mock(
                semantic_query="bitcoin price weakness",
                published_from=datetime.fromisoformat("2026-03-25T00:00:00+00:00"),
                published_to=datetime.fromisoformat("2026-04-01T23:59:59+00:00"),
            ),
        ), patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-v4", vectors=[[1.0] + [0.0] * 1535]),
        ) as embed_mock:
            result = service.search(query="最近比特币为什么跌", top_k=5, max_distance=None)

        self.assertEqual(result.semantic_query, "bitcoin price weakness")
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0].article_id, article_in_range.id)
        embed_mock.assert_called_once_with(
            task_name="news_article_embedding",
            texts=["bitcoin price weakness"],
            config_overrides=None,
        )

    def test_search_can_skip_query_understanding(self) -> None:
        article = NewsArticle.objects.create(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/skip-query-understanding.html",
            title="Recent market news",
            content="Recent market news overview.",
            content_hash=calculate_content_md5("Recent market news overview."),
            language="en",
            published="2026-04-01T12:00:00Z",
        )
        NewsArticleEmbedding.objects.create(
            article=article,
            chunk_index=0,
            chunk_text="Recent market news overview.",
            chunk_hash=calculate_content_md5("Recent market news overview."),
            title=article.title,
            source=article.source,
            published=article.published,
            embedding_model="text-embedding-v4",
            embedding=[1.0] + [0.0] * 1535,
        )

        service = NewsSearchService()
        with patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-v4", vectors=[[1.0] + [0.0] * 1535]),
        ) as embed_mock, patch.object(
            service.query_understanding_service,
            "understand",
        ) as understand_mock:
            result = service.search(
                query="最近有什么财经新闻",
                top_k=1,
                max_distance=None,
                skip_query_understanding=True,
            )

        understand_mock.assert_not_called()
        embed_mock.assert_called_once_with(
            task_name="news_article_embedding",
            texts=["最近有什么财经新闻"],
            config_overrides=None,
        )
        self.assertEqual(result.semantic_query, "最近有什么财经新闻")
        self.assertIsNone(result.published_from)
        self.assertIsNone(result.published_to)
        self.assertEqual(result.response_mode, "overview")
        self.assertEqual(len(result.hits), 1)


class NewsAnswerServiceTests(TestCase):
    def test_answer_returns_fallback_when_no_hits(self) -> None:
        service = NewsAnswerService()
        with patch.object(
            service.search_service,
            "search",
            return_value=Mock(
                query="今天应该吃什么",
                semantic_query="今天应该吃什么",
                published_from=None,
                published_to=None,
                response_mode="overview",
                hits=[],
            ),
        ):
            chunks = list(service.answer(query="今天应该吃什么"))

        self.assertEqual(chunks, ["未检索到足够相关的财经新闻，暂时无法给出可靠回答。"])

    def test_prepare_answer_uses_search_result_context(self) -> None:
        service = NewsAnswerService()
        search_result = Mock(
            query="bitcoin trend",
            semantic_query="bitcoin price weakness",
            published_from=None,
            published_to=None,
            response_mode="overview",
            hits=[
                Mock(
                    article_id=10,
                    title="Bitcoin on the brink of its longest losing streak on record",
                    source="Yahoo Finance",
                    published=datetime.fromisoformat("2026-04-01T12:00:00+00:00"),
                    article_url="https://finance.yahoo.com/news/bitcoin-on-the-brink.html",
                    score=0.53,
                    matched_chunks=[
                        Mock(
                            chunk_index=0,
                            score=0.53,
                            chunk_text="Bitcoin prices fell again as traders reduced exposure.",
                        )
                    ],
                    analysis=Mock(
                        topic="Crypto",
                        summary_short="比特币延续下跌。",
                        summary_long="比特币价格继续走弱，市场风险偏好下降。",
                        sentiment="negative",
                        impact_level="medium",
                        countries=["United States"],
                        tags=["Crypto"],
                        instruments=["BTCUSDT.CRYPTO"],
                    ),
                )
            ],
        )
        mock_chat_model = Mock(llm=object())

        with patch.object(service.search_service, "search", return_value=search_result), patch(
            "news.service.news_answer.LLMModelFactory.create_chat_model",
            return_value=mock_chat_model,
        ):
            prepared = service._prepare_answer(query="最近比特币走势", top_k=5, max_distance=0.7, timezone_name=None, search_config_overrides=None, query_understanding_overrides=None, answer_config_overrides=None)

        context = prepared.context
        self.assertIn("Bitcoin on the brink", context)
        self.assertIn("比特币延续下跌。", context)
        self.assertIn("reference_url: https://finance.yahoo.com/news/bitcoin-on-the-brink.html", context)
        self.assertNotIn("matched_chunks:", context)
        self.assertNotIn("比特币价格继续走弱，市场风险偏好下降。", context)
        self.assertNotIn("- sentiment:", context)
        self.assertIs(prepared.chat_model, mock_chat_model)

    def test_prepare_answer_includes_matched_chunks_for_detail_query(self) -> None:
        service = NewsAnswerService()
        search_result = Mock(
            query="最近比特币为什么跌",
            semantic_query="bitcoin price weakness",
            published_from=None,
            published_to=None,
            response_mode="detail",
            hits=[
                Mock(
                    article_id=10,
                    title="Bitcoin on the brink of its longest losing streak on record",
                    source="Yahoo Finance",
                    published=datetime.fromisoformat("2026-04-01T12:00:00+00:00"),
                    article_url="https://finance.yahoo.com/news/bitcoin-on-the-brink.html",
                    score=0.53,
                    matched_chunks=[
                        Mock(
                            chunk_index=0,
                            score=0.53,
                            chunk_text="Bitcoin prices fell again as traders reduced exposure.",
                        )
                    ],
                    analysis=Mock(
                        topic="Crypto",
                        summary_short="比特币延续下跌。",
                        summary_long="比特币价格继续走弱，市场风险偏好下降。",
                        sentiment="negative",
                        impact_level="medium",
                        countries=["United States"],
                        tags=["Crypto"],
                        instruments=["BTCUSDT.CRYPTO"],
                    ),
                )
            ],
        )
        mock_chat_model = Mock(llm=object())

        with patch.object(service.search_service, "search", return_value=search_result), patch(
            "news.service.news_answer.LLMModelFactory.create_chat_model",
            return_value=mock_chat_model,
        ):
            prepared = service._prepare_answer(query="最近比特币为什么跌", top_k=5, max_distance=0.7, timezone_name=None, search_config_overrides=None, query_understanding_overrides=None, answer_config_overrides=None)

        context = prepared.context
        self.assertIn("matched_chunks:", context)
        self.assertIn("Bitcoin prices fell again as traders reduced exposure.", context)
        self.assertIn("比特币价格继续走弱，市场风险偏好下降。", context)
        self.assertIn("- sentiment: negative", context)

    def test_answer_yields_chunks(self) -> None:
        service = NewsAnswerService()
        prepared = Mock(
            search_result=Mock(hits=[Mock()]),
            rendered_prompt="rendered prompt",
            chat_model=Mock(llm=object()),
        )

        with patch.object(
            service,
            "_prepare_answer",
            return_value=prepared,
        ), patch(
            "news.service.news_answer.ChatPromptTemplate.from_messages",
            return_value=MagicMock(),
        ) as prompt_mock, patch(
            "news.service.news_answer.StrOutputParser",
        ) as parser_cls:
            chain = Mock()
            chain.stream.return_value = ["比特币", "继续走弱"]
            mid = MagicMock()
            prompt_mock.return_value.__or__.return_value = mid
            mid.__or__.return_value = chain
            parser_cls.return_value = Mock()

            chunks = list(service.answer(query="最近比特币走势"))

        self.assertEqual(chunks, ["比特币", "继续走弱"])
