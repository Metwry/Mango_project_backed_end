from __future__ import annotations

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from unittest.mock import patch

from market.services.data.cache import WATCHLIST_QUOTES_KEY, WATCHLIST_QUOTES_MARKET_KEY_PREFIX
from market.services.data.market import pull_market
from market.services.data.pull_guard import GuardDecision


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

    @patch("market.services.data.market._sync_investment_account_balances")
    @patch("market.services.data.market.pull_watchlist_quotes")
    @patch("market.services.data.market.resolve_due_markets")
    @patch("market.services.data.market.global_subscription_meta_by_market")
    def test_due_market_pulls_quotes(
        self,
        mock_sub_meta,
        mock_resolve_due,
        mock_pull_quotes,
        _mock_sync_accounts,
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

        payload = pull_market()

        mock_pull_quotes.assert_called_once_with(force_fetch_all_markets=False, allowed_markets={"US"})
        self.assertEqual(payload["updated_markets"], ["US"])
        market_payload = cache.get(f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}US")
        self.assertEqual(market_payload["pulled_at"], payload["updated_at"])

    @patch("market.services.data.market._sync_investment_account_balances")
    @patch("market.services.data.market.pull_watchlist_quotes")
    @patch("market.services.data.market.resolve_due_markets")
    @patch("market.services.data.market.global_subscription_meta_by_market")
    def test_no_due_and_no_bootstrap_keeps_previous_pulled_at(
        self,
        mock_sub_meta,
        mock_resolve_due,
        mock_pull_quotes,
        _mock_sync_accounts,
    ):
        """验证no due and no bootstrap 在未到期且未 bootstrap 时保留上次 pulled at。"""
        old_pulled_at = "2026-03-04T12:00:00+08:00"
        cache.set(
            WATCHLIST_QUOTES_KEY,
            {
                "updated_at": "2026-03-04T12:00:00+08:00",
                "updated_markets": ["US"],
                "stale_markets": [],
                "data": {"US": [{"short_code": "AAPL", "name": "Apple Inc.", "price": 180}]},
            },
            timeout=None,
        )
        cache.set(
            f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}US",
            {
                "updated_at": "2026-03-04T12:00:00+08:00",
                "pulled_at": old_pulled_at,
                "market": "US",
                "stale": False,
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

        payload = pull_market()

        mock_pull_quotes.assert_not_called()
        self.assertEqual(payload["updated_markets"], [])
        market_payload = cache.get(f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}US")
        self.assertEqual(market_payload["pulled_at"], old_pulled_at)
        self.assertEqual(market_payload["updated_at"], payload["updated_at"])
