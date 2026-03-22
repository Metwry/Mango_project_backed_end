from __future__ import annotations

from datetime import datetime, timezone

from django.test import SimpleTestCase, override_settings

from market.services.market_schedule import market_guard_decision, resolve_due_markets


@override_settings(
    MARKET_PULL_INTERVAL_MINUTES=10,
    MARKET_FX_PULL_INTERVAL_MINUTES=240,
    MARKET_CRYPTO_PULL_INTERVAL_MINUTES=10,
)
class CalendarGuardTests(SimpleTestCase):
    def test_us_open_market_on_aligned_tick_is_due(self):
        """验证美股开市且命中 10 分钟 tick 时会触发拉取。"""
        decision = market_guard_decision("US", now_utc=datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc))

        self.assertTrue(decision.should_pull)
        self.assertEqual(decision.reason, "due")

    def test_us_open_market_off_tick_is_not_due(self):
        """验证美股开市但未命中 10 分钟 tick 时不会拉取。"""
        decision = market_guard_decision("US", now_utc=datetime(2026, 3, 2, 15, 5, tzinfo=timezone.utc))

        self.assertFalse(decision.should_pull)
        self.assertEqual(decision.reason, "not_due")

    def test_us_closed_market_is_blocked(self):
        """验证美股休市时不会拉取。"""
        decision = market_guard_decision("US", now_utc=datetime(2026, 3, 2, 1, 0, tzinfo=timezone.utc))

        self.assertFalse(decision.should_pull)
        self.assertEqual(decision.reason, "outside_session")
        self.assertEqual(decision.session, "none")

    def test_fx_uses_four_hour_interval(self):
        """验证 FX 使用 4 小时 tick。"""
        due = market_guard_decision("FX", now_utc=datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc))
        not_due = market_guard_decision("FX", now_utc=datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc))

        self.assertTrue(due.should_pull)
        self.assertFalse(not_due.should_pull)
        self.assertEqual(not_due.reason, "not_due")

    def test_resolve_due_markets_returns_only_due_markets(self):
        """验证批量判断只返回当前到期市场。"""
        due, decisions = resolve_due_markets(
            ["US", "FX"],
            now_utc=datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(due, {"US"})
        self.assertTrue(decisions["US"].should_pull)
        self.assertFalse(decisions["FX"].should_pull)
