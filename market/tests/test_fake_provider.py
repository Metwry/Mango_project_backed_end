from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from accounts.services.quote_fetcher import pull_usd_exchange_rates, pull_watchlist_quotes, pull_single_instrument_quote


@override_settings(MARKET_QUOTE_PROVIDER="fake")
class FakeQuoteProviderTests(SimpleTestCase):
    @patch(
        "accounts.services.quote_fetcher.get_unique_instruments_from_subscriptions",
        return_value=[
            ("AAPL.US", "AAPL", "Apple Inc.", "US", None, None),
            ("BTC.CRYPTO", "BTC", "Bitcoin", "CRYPTO", None, None),
            ("USD/CNY.FX", "USD/CNY", "USD/CNY", "FX", None, None),
        ],
    )
    def test_pull_watchlist_quotes_fake_provider_no_external_api(self, _mock_rows):
        """验证pull 自选 quotes 假数据 提供方 不会访问外部 API。"""
        data = pull_watchlist_quotes(
            now_utc=datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
            force_fetch_all_markets=True,
        )
        self.assertIn("US", data)
        self.assertIn("CRYPTO", data)
        self.assertIn("FX", data)
        self.assertIsInstance(data["US"][0]["price"], float)

    def test_pull_usd_exchange_rates_fake_provider(self):
        """验证pull usd exchange rates 假数据 提供方。"""
        rates = pull_usd_exchange_rates()
        self.assertEqual(rates["USD"], 1.0)
        self.assertIn("CNY", rates)
        self.assertIn("EUR", rates)

    def test_pull_single_instrument_quote_fake_provider(self):
        """验证pull 单条 instrument 行情 假数据 提供方。"""
        row = pull_single_instrument_quote("AAPL.US", "AAPL", "Apple Inc.", "US")
        self.assertIsNotNone(row)
        self.assertIsInstance(row["price"], float)
        self.assertEqual(row["short_code"], "AAPL")

