from __future__ import annotations

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from unittest.mock import patch

from market.services.pricing.cache import WATCHLIST_QUOTES_KEY, WATCHLIST_QUOTES_MARKET_KEY_PREFIX
from market.services.pricing.schedule import GuardDecision
from market.services.refresh.watchlist import refresh_watchlist


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "snapshot-sync-tests",
        }
    }
)
class SnapshotSyncServiceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("market.services.refresh.watchlist.pull_watchlist_quotes")
    @patch("market.services.refresh.watchlist.resolve_due_markets")
    @patch("market.services.refresh.watchlist.global_subscription_meta_by_market")
    def test_due_market_pulls_quotes(
        self,
        mock_sub_meta,
        mock_resolve_due,
        mock_pull_quotes,
    ):
        """验证到期市场会拉取行情。"""
        mock_sub_meta.return_value = {
            "US": {
                "AAPL": {
                    "short_code": "AAPL",
                    "name": "Apple Inc.",
                    "symbol": "AAPL.US",
                    "logo_url": None,
                    "logo_color": None,
                }
            }
        }
        mock_resolve_due.return_value = (
            {"US"},
            {"US": GuardDecision(market="US", should_pull=True, reason="due", session="regular")},
        )
        mock_pull_quotes.return_value = {
            "US": [
                {
                    "short_code": "AAPL",
                    "name": "Apple Inc.",
                    "price": 190.5,
                }
            ]
        }

        payload = refresh_watchlist()

        mock_pull_quotes.assert_called_once_with(allowed_markets={"US"})
        self.assertEqual(payload["data"]["US"][0]["price"], 190.5)
        market_payload = cache.get(f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}US")
        self.assertEqual(market_payload["updated_at"], payload["updated_at"])
        self.assertEqual(market_payload["data"][0]["price"], 190.5)

    @patch("market.services.refresh.watchlist.pull_single_instrument_quote")
    @patch("market.services.refresh.watchlist.pull_watchlist_quotes")
    @patch("market.services.refresh.watchlist.resolve_due_markets")
    @patch("market.services.refresh.watchlist.global_subscription_meta_by_market")
    def test_force_full_fetch_bootstrap_backfills_missing_quotes(
        self,
        mock_sub_meta,
        mock_resolve_due,
        mock_pull_quotes,
        mock_pull_single,
    ):
        """验证首次强制初始化会绕过守卫并补齐缺失行情。"""
        mock_sub_meta.return_value = {
            "US": {
                "AAPL": {
                    "short_code": "AAPL",
                    "name": "Apple Inc.",
                    "symbol": "AAPL.US",
                    "logo_url": None,
                    "logo_color": None,
                }
            }
        }
        mock_pull_quotes.return_value = {"US": []}
        mock_pull_single.return_value = {
            "short_code": "AAPL",
            "name": "Apple Inc.",
            "price": 190.5,
        }

        payload = refresh_watchlist(force_full_fetch=True)

        mock_resolve_due.assert_not_called()
        mock_pull_quotes.assert_called_once_with(allowed_markets={"US"})
        mock_pull_single.assert_called_once_with(
            symbol="AAPL.US",
            short_code="AAPL",
            name="Apple Inc.",
            market="US",
        )
        self.assertEqual(payload["data"]["US"][0]["price"], 190.5)

    @patch("market.services.refresh.watchlist.pull_watchlist_quotes")
    @patch("market.services.refresh.watchlist.resolve_due_markets")
    @patch("market.services.refresh.watchlist.global_subscription_meta_by_market")
    def test_no_due_and_no_bootstrap_keeps_previous_market_payload(
        self,
        mock_sub_meta,
        mock_resolve_due,
        mock_pull_quotes,
    ):
        """验证 no due and no bootstrap 在未到期时保留上次市场行情。"""
        cache.set(
            WATCHLIST_QUOTES_KEY,
            {
                "updated_at": "2026-03-04T12:00:00+08:00",
                "data": {"US": [{"short_code": "AAPL", "name": "Apple Inc.", "price": 180}]},
            },
            timeout=None,
        )
        cache.set(
            f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}US",
            {
                "updated_at": "2026-03-04T12:00:00+08:00",
                "market": "US",
                "data": [{"short_code": "AAPL", "name": "Apple Inc.", "price": 180}],
            },
            timeout=None,
        )

        mock_sub_meta.return_value = {
            "US": {
                "AAPL": {
                    "short_code": "AAPL",
                    "name": "Apple Inc.",
                    "symbol": "AAPL.US",
                    "logo_url": None,
                    "logo_color": None,
                }
            }
        }
        mock_resolve_due.return_value = (
            set(),
            {"US": GuardDecision(market="US", should_pull=False, reason="not_due", session="regular")},
        )

        payload = refresh_watchlist()

        mock_pull_quotes.assert_not_called()
        self.assertEqual(payload["data"]["US"][0]["price"], 180)
        market_payload = cache.get(f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}US")
        self.assertEqual(market_payload["updated_at"], payload["updated_at"])
        self.assertEqual(market_payload["data"][0]["price"], 180)
