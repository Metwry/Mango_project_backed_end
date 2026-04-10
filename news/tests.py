import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
from django.test import SimpleTestCase
from django.test import TestCase

from ai.rag.newsSummaryService import NewsSummaryQuery, NewsSummaryService
from ai.models import AIAnalysis, AIAnalysisCountry, AIAnalysisInstrument, AIAnalysisTag
from market.models import Instrument
from news.models import NewsArticle, NewsArticleEmbedding
from news.service.news_embedding import NewsArticleEmbeddingService
from news.service.news_put import NewsPutService
from news.service.yahoo_news import (
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    PreparedNewsArticle,
    TableBlock,
    extract_article_blocks,
    fetch_text,
    parse_published_at,
    prepare_article,
    render_blocks_text,
)
from news.service.news_search import NewsSearchResult, NewsSearchService
from news.utils.cleanup import clean_stored_article_content
from news.utils.hash import calculate_content_md5, normalize_content_for_hash


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

        with patch("news.txt.service.yahoo_news.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            result = asyncio.run(fetch_text(session, "https://finance.yahoo.com/news/rss"))

        self.assertEqual(result, "ok")
        self.assertEqual(session.get.call_count, 2)
        sleep_mock.assert_awaited_once()

    def test_fetch_text_raises_after_retry_exhausted(self) -> None:
        session = Mock()
        session.get.side_effect = aiohttp.ClientPayloadError("partial")

        with patch("news.txt.service.yahoo_news.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(aiohttp.ClientPayloadError):
                asyncio.run(
                    fetch_text(
                        session,
                        "https://finance.yahoo.com/news/rss",
                        retry_attempts=2,
                        retry_base_delay=0,
                    )
                )


class YahooNewsPreparationTests(SimpleTestCase):
    def test_parse_published_at_supports_iso8601(self) -> None:
        parsed = parse_published_at("2026-03-31T15:06:24Z")
        self.assertEqual(parsed.isoformat(), "2026-03-31T15:06:24+00:00")

    def test_prepare_article_cleans_content_and_sets_hash(self) -> None:
        article = prepare_article(
            {
                "title": "Chip stocks rally",
                "link": "https://finance.yahoo.com/news/chip-stocks-rally-1.html",
                "published_at": "Tue, 31 Mar 2026 08:00:00 GMT",
                "source": "Reuters",
            },
            content=(
                "Some offers on this page are from advertisers who pay us. "
                "See our Advertiser Disclosure .\n\nNvidia and AMD rose after strong AI demand signals."
            ),
            blocks=[],
        )

        self.assertEqual(article.provider, "yahoo")
        self.assertEqual(article.article_url, "https://finance.yahoo.com/news/chip-stocks-rally-1.html")
        self.assertNotIn("Advertiser Disclosure", article.content)
        self.assertEqual(article.content_hash, calculate_content_md5(article.content))


class NewsPutServiceTests(TestCase):
    def test_put_creates_article(self) -> None:
        service = NewsPutService()
        article = PreparedNewsArticle(
            provider="yahoo",
            source="Reuters",
            article_url="https://finance.yahoo.com/news/chip-stocks-rally-1.html",
            title="Chip stocks rally",
            content="Nvidia and AMD rose after strong AI demand signals.",
            content_hash=calculate_content_md5("Nvidia and AMD rose after strong AI demand signals."),
            language="en",
            published=datetime.fromisoformat("2026-03-31T08:00:00+00:00"),
            fetched_at=datetime.fromisoformat("2026-03-31T08:30:00+00:00"),
        )

        stats = service.put_articles([article])

        self.assertEqual(stats.received, 1)
        self.assertEqual(stats.created, 1)
        self.assertEqual(NewsArticle.objects.count(), 1)
        saved = NewsArticle.objects.get()
        self.assertEqual(saved.article_url, article.article_url)
        self.assertEqual(saved.content_hash, article.content_hash)

    def test_put_skips_duplicate_content_from_different_url(self) -> None:
        service = NewsPutService()
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
        article = PreparedNewsArticle(
            provider="yahoo",
            source="Yahoo Finance",
            article_url="https://finance.yahoo.com/news/duplicate-article.html",
            title="Duplicate",
            content=content,
            content_hash=calculate_content_md5(content),
            language="en",
            published=datetime.fromisoformat("2026-03-31T08:00:00+00:00"),
            fetched_at=datetime.fromisoformat("2026-03-31T08:30:00+00:00"),
        )

        stats = service.put_articles([article])

        self.assertEqual(stats.duplicate_content, 1)
        self.assertEqual(stats.created, 0)
        self.assertEqual(NewsArticle.objects.count(), 1)

    def test_put_updates_existing_article(self) -> None:
        service = NewsPutService()
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
        article = PreparedNewsArticle(
            provider="yahoo",
            source="Reuters",
            article_url=existing.article_url,
            title="Oil prices updated",
            content="Oil prices rose after fresh OPEC comments.",
            content_hash=calculate_content_md5("Oil prices rose after fresh OPEC comments."),
            language="en",
            published=datetime.fromisoformat("2026-03-31T08:00:00+00:00"),
            fetched_at=datetime.fromisoformat("2026-03-31T08:30:00+00:00"),
        )

        stats = service.put_articles([article])

        self.assertEqual(stats.updated, 1)
        existing.refresh_from_db()
        self.assertEqual(existing.title, "Oil prices updated")
        self.assertEqual(existing.content_hash, article.content_hash)


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
            embedding=[0.8, 0.2] + [0.0] * 1534,
        )

        service = NewsSearchService()
        with patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-v4", vectors=[[1.0] + [0.0] * 1535]),
        ):
            result = service.search(query="bitcoin weakness", top_k=2)

        self.assertEqual(result.query, "bitcoin weakness")
        self.assertEqual(result.hit_count, 2)
        self.assertIn(article_a.article_url, result.context)
        self.assertIn(article_b.article_url, result.context)

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
            embedding=[0.8, 0.2] + [0.0] * 1534,
        )

        service = NewsSearchService()
        with patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-v4", vectors=[[1.0] + [0.0] * 1535]),
        ):
            result = service.search(query="bitcoin decline", top_k=2)

        self.assertEqual(result.hit_count, 2)
        self.assertIn(article.article_url, result.context)
        self.assertIn(other_article.article_url, result.context)

    def test_search_filters_hits_above_default_max_distance(self) -> None:
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
            embedding=[-1.0] + [0.0] * 1535,
        )

        service = NewsSearchService()
        with patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-v4", vectors=[[1.0] + [0.0] * 1535]),
        ):
            result = service.search(query="bitcoin", top_k=5)

        self.assertEqual(result.hit_count, 0)
        self.assertEqual(result.context, "")

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
        ):
            result = service.search(query="bitcoin weakness", top_k=1)

        self.assertEqual(result.hit_count, 1)
        self.assertIn("Bitcoin Weakness", result.context)
        self.assertIn("negative", result.context)
        self.assertIn("United States", result.context)
        self.assertIn("Crypto", result.context)
        self.assertIn("BTCUSDT.CRYPTO", result.context)

    def test_search_uses_explicit_time_filter(self) -> None:
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
        published_from = datetime.fromisoformat("2026-03-25T00:00:00+00:00")
        published_to = datetime.fromisoformat("2026-04-01T23:59:59+00:00")
        with patch.object(
            service.embedding_service,
            "embed",
            return_value=Mock(model_name="text-embedding-v4", vectors=[[1.0] + [0.0] * 1535]),
        ) as embed_mock:
            result = service.search(
                query="最近比特币为什么跌",
                top_k=5,
                published_from=published_from,
                published_to=published_to,
            )

        self.assertEqual(result.hit_count, 1)
        self.assertIn(article_in_range.article_url, result.context)
        embed_mock.assert_called_once_with(
            task_name="news_article_embedding",
            texts=["最近比特币为什么跌"],
        )

class NewsSummaryServiceTests(TestCase):
    def test_rag_summarize_returns_fallback_when_no_hits(self) -> None:
        tool = NewsSummaryService()
        with patch.object(
            tool.search_service,
            "search",
            return_value=Mock(
                query="今天应该吃什么",
                response_mode="overview",
                context="",
                hit_count=0,
            ),
        ):
            result = tool.rag_summarize(
                NewsSummaryQuery(query="今天应该吃什么", response_mode="overview")
            )

        self.assertEqual(result, "未检索到足够相关的财经新闻，暂时无法给出可靠回答。")

    def test_search_result_context_uses_overview_style(self) -> None:
        tool = NewsSummaryService()
        hits = [
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
        ]
        search_result = NewsSearchResult(
            query="bitcoin trend",
            response_mode="overview",
            context=tool.search_service._build_context(hits, "overview"),
            hit_count=1,
        )

        context = search_result.context
        self.assertIn("Bitcoin on the brink", context)
        self.assertIn("比特币延续下跌。", context)
        self.assertIn("reference_url: https://finance.yahoo.com/news/bitcoin-on-the-brink.html", context)
        self.assertNotIn("matched_chunks:", context)
        self.assertNotIn("比特币价格继续走弱，市场风险偏好下降。", context)
        self.assertNotIn("- sentiment: negative", context)

    def test_search_result_context_uses_detail_style(self) -> None:
        tool = NewsSummaryService()
        hits = [
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
        ]
        search_result = NewsSearchResult(
            query="最近比特币为什么跌",
            response_mode="detail",
            context=tool.search_service._build_context(hits, "detail"),
            hit_count=1,
        )

        context = search_result.context
        self.assertIn("matched_chunks:", context)
        self.assertIn("Bitcoin prices fell again as traders reduced exposure.", context)
        self.assertIn("比特币价格继续走弱，市场风险偏好下降。", context)
        self.assertIn("- sentiment: negative", context)

    def test_rag_summarize_returns_answer_text(self) -> None:
        tool = NewsSummaryService()
        search_result = Mock(
            response_mode="overview",
            context="context",
            hit_count=1,
        )
        tool.chain = Mock()
        tool.chain.invoke.return_value = "比特币继续走弱"

        with patch.object(
            tool.search_service,
            "search",
            return_value=search_result,
        ):
            result = tool.rag_summarize(
                NewsSummaryQuery(query="最近比特币走势", response_mode="overview")
            )

        self.assertEqual(result, "比特币继续走弱")
