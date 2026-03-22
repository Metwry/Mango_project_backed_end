from __future__ import annotations

from datetime import datetime, timezone

from django.test import SimpleTestCase, override_settings

from market.services.market_utils import (
    filter_snapshot_quotes,
    format_latest_quote_item,
    should_pull_market_tick,
    should_fetch_market,
)


@override_settings(
    MARKET_PULL_INTERVAL_MINUTES=10,
    MARKET_FX_PULL_INTERVAL_MINUTES=240,
)
class MarketDataUtilsTests(SimpleTestCase):
    def test_should_fetch_market_uses_shared_open_session_rules(self):
        """验证共享开市判断规则覆盖美股开盘和休市时间。"""
        self.assertTrue(should_fetch_market("US", datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc)))
        self.assertFalse(should_fetch_market("US", datetime(2026, 3, 2, 1, 0, tzinfo=timezone.utc)))

    def test_should_pull_market_tick_uses_interval_alignment(self):
        """验证共享 tick 判断会按分钟间隔对齐。"""
        self.assertTrue(should_pull_market_tick("US", datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc)))
        self.assertFalse(should_pull_market_tick("US", datetime(2026, 3, 2, 15, 5, tzinfo=timezone.utc)))

    def test_should_fetch_market_uses_exchange_calendar_lunch_break(self):
        """验证港股午休时段不会被判定为开市。"""
        self.assertFalse(should_fetch_market("HK", datetime(2026, 3, 2, 4, 30, tzinfo=timezone.utc)))

    def test_should_pull_market_tick_respects_four_hour_fx_interval(self):
        """验证 FX 4 小时间隔按当天累计分钟对齐。"""
        self.assertTrue(should_pull_market_tick("FX", datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)))
        self.assertFalse(should_pull_market_tick("FX", datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)))

    def test_filter_snapshot_quotes_normalizes_logo_fields(self):
        """验证快照过滤会清洗空 logo 字段。"""
        rows = [
            {"short_code": "AAPL", "price": 190, "logo_url": "", "logo_color": ""},
            {"short_code": "MSFT", "price": 380},
        ]

        filtered = filter_snapshot_quotes(rows, {"AAPL"})

        self.assertEqual(filtered, [{"short_code": "AAPL", "price": 190, "logo_url": None, "logo_color": None}])

    def test_format_latest_quote_item_formats_decimal_price(self):
        """验证最新价摘要会格式化价格字符串。"""
        item = format_latest_quote_item(
            market="US",
            short_code="AAPL",
            row={"price": 190.50, "logo_url": "", "logo_color": None},
        )

        self.assertEqual(
            item,
            {
                "market": "US",
                "short_code": "AAPL",
                "latest_price": "190.5",
                "logo_url": None,
                "logo_color": None,
            },
        )
