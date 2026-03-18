from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from django.core.management import call_command
from django.test import SimpleTestCase


class _FakeCalendar:
    def schedule(self, start_date, end_date):
        idx = pd.DatetimeIndex([pd.Timestamp("2026-01-02T00:00:00Z")], tz="UTC")
        return pd.DataFrame(
            {
                "market_open": [pd.Timestamp("2026-01-02T14:30:00Z")],
                "market_close": [pd.Timestamp("2026-01-02T21:00:00Z")],
            },
            index=idx,
        )


class _FakeMcal:
    @staticmethod
    def get_calendar(name):
        if name in {"NYSE", "NASDAQ"}:
            return _FakeCalendar()
        raise ValueError(f"unknown calendar: {name}")


class BuildMarketCalendarCsvCommandTests(SimpleTestCase):
    @patch("market.management.commands.build_market_calendar_csv.mcal", new=_FakeMcal())
    def test_build_market_calendar_csv_writes_expected_file(self):
        """验证build 市场 日历 csv 会写出预期文件。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            call_command(
                "build_market_calendar_csv",
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-10",
                "--markets",
                "US",
                "--out-dir",
                tmp_dir,
            )

            out = Path(tmp_dir) / "US_2026.csv"
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("market,trade_date,timezone,is_open", content)
            self.assertIn("US,2026-01-02,America/New_York,1", content)

