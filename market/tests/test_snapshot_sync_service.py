from __future__ import annotations

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from unittest.mock import patch

from market.services.cache_keys import WATCHLIST_QUOTES_KEY, WATCHLIST_QUOTES_MARKET_KEY_PREFIX
from market.services.calendar_guard_service import GuardDecision
from market.services.snapshot_sync_service import sync_watchlist_snapshot


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

    @patch("market.services.snapshot_sync_service._need_refresh_fx_rates", return_value=False)
    @patch("market.services.snapshot_sync_service.pull_watchlist_quotes")
    @patch("market.services.snapshot_sync_service.resolve_due_markets")
    @patch("market.services.snapshot_sync_service.global_subscription_meta_by_market")
    def test_force_init_pull_when_bootstrap_but_not_due(
        self,
        mock_sub_meta,
        mock_resolve_due,
        mock_pull_quotes,
        _mock_need_fx_refresh,
    ):
        """验证force init pull 在 bootstrap 但未到期时执行强制初始化拉取。"""
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
            {"US": GuardDecision(market="US", should_pull=False, reason="outside_session", session="none")},
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

        payload = sync_watchlist_snapshot()

        mock_pull_quotes.assert_called_once_with(force_fetch_all_markets=True, allowed_markets={"US"})
        self.assertEqual(payload["updated_markets"], ["US"])
        market_payload = cache.get(f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}US")
        self.assertEqual(market_payload["pulled_at"], payload["updated_at"])

    @patch("market.services.snapshot_sync_service._need_refresh_fx_rates", return_value=False)
    @patch("market.services.snapshot_sync_service.pull_watchlist_quotes")
    @patch("market.services.snapshot_sync_service.resolve_due_markets")
    @patch("market.services.snapshot_sync_service.global_subscription_meta_by_market")
    def test_no_due_and_no_bootstrap_keeps_previous_pulled_at(
        self,
        mock_sub_meta,
        mock_resolve_due,
        mock_pull_quotes,
        _mock_need_fx_refresh,
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

        payload = sync_watchlist_snapshot()

        mock_pull_quotes.assert_not_called()
        self.assertEqual(payload["updated_markets"], [])
        market_payload = cache.get(f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}US")
        self.assertEqual(market_payload["pulled_at"], old_pulled_at)
        self.assertEqual(market_payload["updated_at"], payload["updated_at"])
