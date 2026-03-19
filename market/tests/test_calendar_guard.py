from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from market.services.snapshot.cache_keys import WATCHLIST_QUOTES_MARKET_KEY_PREFIX
from market.services.snapshot.calendar_guard import _CALENDAR_CACHE, market_guard_decision


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "calendar-guard-tests",
        }
    }
)
class CalendarGuardTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        _CALENDAR_CACHE.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.calendar_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()
        _CALENDAR_CACHE.clear()
        cache.clear()

    def _write_calendar(self, market: str, year: int, rows: list[dict]):
        out = self.calendar_dir / f"{market}_{year}.csv"
        headers = [
            "market",
            "trade_date",
            "timezone",
            "is_open",
            "market_open_local",
            "market_close_local",
            "market_open_utc",
            "market_close_utc",
            "is_half_day",
            "session_tag",
            "source",
            "generated_at_utc",
        ]
        with open(out, "w", encoding="utf-8", newline="") as fp:
            fp.write(",".join(headers) + "\n")
            for row in rows:
                fp.write(",".join(str(row.get(h, "")) for h in headers) + "\n")

    def test_non_trading_day_is_blocked(self):
        """验证non trading 天 会被阻止。"""
        self._write_calendar(
            "US",
            2026,
            [
                {
                    "market": "US",
                    "trade_date": "2026-03-01",
                    "timezone": "America/New_York",
                    "is_open": "0",
                    "market_open_local": "2026-03-01T09:30:00-05:00",
                    "market_close_local": "2026-03-01T16:00:00-05:00",
                    "market_open_utc": "2026-03-01T14:30:00+00:00",
                    "market_close_utc": "2026-03-01T21:00:00+00:00",
                    "is_half_day": "0",
                    "session_tag": "",
                    "source": "test",
                    "generated_at_utc": "2026-03-01T00:00:00+00:00",
                }
            ],
        )

        now_utc = datetime(2026, 3, 1, 15, 0, tzinfo=timezone.utc)
        with self.settings(
            MARKET_CALENDAR_DIR=str(self.calendar_dir),
            MARKET_CALENDAR_REQUIRED=True,
            MARKET_PULL_FALLBACK_ON_MISSING_CALENDAR=False,
        ):
            decision = market_guard_decision("US", now_utc=now_utc)

        self.assertFalse(decision.should_pull)
        self.assertEqual(decision.reason, "non_trading_day")

    def test_cn_pre_open_one_shot_only_once(self):
        """验证cn pre open 一个 shot 只会执行一次。"""
        self._write_calendar(
            "CN",
            2026,
            [
                {
                    "market": "CN",
                    "trade_date": "2026-03-02",
                    "timezone": "Asia/Shanghai",
                    "is_open": "1",
                    "market_open_local": "2026-03-02T09:30:00+08:00",
                    "market_close_local": "2026-03-02T15:00:00+08:00",
                    "market_open_utc": "2026-03-02T01:30:00+00:00",
                    "market_close_utc": "2026-03-02T07:00:00+00:00",
                    "is_half_day": "0",
                    "session_tag": "",
                    "source": "test",
                    "generated_at_utc": "2026-03-01T00:00:00+00:00",
                }
            ],
        )
        now_utc = datetime(2026, 3, 2, 1, 25, tzinfo=timezone.utc)  # 09:25 CST

        with self.settings(
            MARKET_CALENDAR_DIR=str(self.calendar_dir),
            MARKET_CALENDAR_REQUIRED=True,
            MARKET_PULL_TASK_INTERVAL_MINUTES=5,
        ):
            first = market_guard_decision("CN", now_utc=now_utc)
            self.assertTrue(first.should_pull)
            self.assertEqual(first.session, "pre")

            cache.set(
                f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}CN",
                {"updated_at": "2026-03-02T09:26:00+08:00", "market": "CN", "stale": False, "data": []},
                timeout=None,
            )
            _CALENDAR_CACHE.clear()
            second = market_guard_decision("CN", now_utc=now_utc)
            self.assertFalse(second.should_pull)

    def test_fx_uses_pulled_at_instead_of_updated_at(self):
        """验证fx 使用 pulled at 而不是 updated at。"""
        now_utc = datetime(2026, 3, 2, 10, 30, tzinfo=timezone.utc)  # Monday
        cache.set(
            f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}FX",
            {
                "updated_at": "2026-03-02T10:29:00+00:00",
                "pulled_at": "2026-03-02T09:40:00+00:00",
                "market": "FX",
                "stale": True,
                "data": [],
            },
            timeout=None,
        )
        with self.settings(
            MARKET_FX_PULL_INTERVAL_MINUTES=30,
        ):
            decision = market_guard_decision("FX", now_utc=now_utc)
        self.assertTrue(decision.should_pull)

    def test_fx_with_null_pulled_at_treats_as_never_pulled(self):
        """验证fx with null pulled at 会视为从未拉取过。"""
        now_utc = datetime(2026, 3, 2, 10, 30, tzinfo=timezone.utc)  # Monday
        cache.set(
            f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}FX",
            {
                "updated_at": "2026-03-02T10:29:00+00:00",
                "pulled_at": None,
                "market": "FX",
                "stale": True,
                "data": [],
            },
            timeout=None,
        )
        with self.settings(
            MARKET_FX_PULL_INTERVAL_MINUTES=30,
        ):
            decision = market_guard_decision("FX", now_utc=now_utc)
        self.assertTrue(decision.should_pull)
