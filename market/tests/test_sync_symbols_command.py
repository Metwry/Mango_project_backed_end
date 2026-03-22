from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from market.management.commands.sync_symbols import InstrumentPayload
from market.models import Instrument


class SyncSymbolsCommandTests(SimpleTestCase):
    @patch("market.management.commands.sync_symbols.Command.upsert_instruments", return_value=(1, 0, 1))
    @patch("market.management.commands.sync_symbols.Command.fetch_cn_stocks")
    def test_sync_symbols_renders_progress_table_for_success(self, mock_fetch_cn, _mock_upsert):
        mock_fetch_cn.return_value = [
            InstrumentPayload(
                symbol="600519.SH",
                short_code="600519",
                name="Kweichow Moutai",
                asset_class=Instrument.AssetClass.STOCK,
                market=Instrument.Market.CN,
                exchange="SH",
                base_currency="CNY",
                is_active=True,
            )
        ]

        out = StringIO()
        call_command("sync_symbols", "--markets", "cn", stdout=out)
        text = out.getvalue()

        self.assertIn("Market sync progress", text)
        self.assertIn("A-shares", text)
        self.assertIn("pending", text)
        self.assertIn("fetching", text)
        self.assertIn("enriching", text)
        self.assertIn("upserting", text)
        self.assertIn("done", text)

    @patch("market.management.commands.sync_symbols.Command.upsert_instruments", return_value=(1, 0, 1))
    @patch("market.management.commands.sync_symbols.Command.fetch_hk_stocks", side_effect=ValueError("hk provider down"))
    @patch("market.management.commands.sync_symbols.Command.fetch_cn_stocks")
    def test_sync_symbols_renders_failed_market_in_progress_table(self, mock_fetch_cn, _mock_fetch_hk, _mock_upsert):
        mock_fetch_cn.return_value = [
            InstrumentPayload(
                symbol="600519.SH",
                short_code="600519",
                name="Kweichow Moutai",
                asset_class=Instrument.AssetClass.STOCK,
                market=Instrument.Market.CN,
                exchange="SH",
                base_currency="CNY",
                is_active=True,
            )
        ]

        out = StringIO()
        call_command("sync_symbols", "--markets", "cn", "hk", stdout=out)
        text = out.getvalue()

        self.assertIn("HK-shares", text)
        self.assertIn("failed", text)
        self.assertIn("hk provider down", text)


class SyncSymbolsInsertOnlyTests(TestCase):
    @patch("market.management.commands.sync_symbols.Command.fetch_cn_stocks")
    def test_sync_symbols_insert_only_keeps_existing_rows_unchanged(self, mock_fetch_cn):
        existing = Instrument.objects.create(
            symbol="600519.SH",
            short_code="600519",
            name="Old Name",
            asset_class=Instrument.AssetClass.STOCK,
            market=Instrument.Market.CN,
            exchange="SH",
            base_currency="CNY",
            is_active=True,
        )
        mock_fetch_cn.return_value = [
            InstrumentPayload(
                symbol="600519.SH",
                short_code="600519",
                name="New Name",
                asset_class=Instrument.AssetClass.STOCK,
                market=Instrument.Market.CN,
                exchange="SH",
                base_currency="CNY",
                is_active=True,
            ),
            InstrumentPayload(
                symbol="000001.SZ",
                short_code="000001",
                name="Ping An Bank",
                asset_class=Instrument.AssetClass.STOCK,
                market=Instrument.Market.CN,
                exchange="SZ",
                base_currency="CNY",
                is_active=True,
            ),
        ]

        out = StringIO()
        call_command("sync_symbols", "--markets", "cn", "--insert-only", stdout=out)
        existing.refresh_from_db()
        created = Instrument.objects.get(symbol="000001.SZ")
        text = out.getvalue()

        self.assertEqual(existing.name, "Old Name")
        self.assertEqual(created.name, "Ping An Bank")
        self.assertIn("Insert-only mode enabled", text)
        self.assertIn("persisted=3, created=3, updated=0, insert_only=True", text)

    @patch("market.management.commands.sync_symbols.Command.fetch_hk_stocks")
    def test_sync_symbols_keeps_logo_metadata_on_existing_rows(self, mock_fetch_hk):
        existing = Instrument.objects.create(
            symbol="00700.HK",
            short_code="00700",
            name="Tencent Holdings",
            asset_class=Instrument.AssetClass.STOCK,
            market=Instrument.Market.HK,
            exchange="HKEX",
            base_currency="HKD",
            logo_url="https://img.logo.dev/ticker/700.HK?token=test&retina=true",
            logo_source="logo.dev:ticker",
            logo_updated_at=timezone.now(),
            is_active=True,
        )
        mock_fetch_hk.return_value = [
            InstrumentPayload(
                symbol="00700.HK",
                short_code="00700",
                name="Tencent",
                asset_class=Instrument.AssetClass.STOCK,
                market=Instrument.Market.HK,
                exchange="HKEX",
                base_currency="HKD",
                is_active=True,
            )
        ]

        call_command("sync_symbols", "--markets", "hk", stdout=StringIO())
        existing.refresh_from_db()

        self.assertIn("/ticker/700.HK", existing.logo_url)
        self.assertEqual(existing.logo_source, "logo.dev:ticker")
        self.assertIsNotNone(existing.logo_updated_at)


class SyncSymbolsIndexSeedTests(TestCase):
    @patch("market.management.commands.sync_symbols.Command.fetch_us_stocks")
    @patch("market.management.commands.sync_symbols.Command.fetch_hk_stocks")
    @patch("market.management.commands.sync_symbols.Command.fetch_cn_stocks")
    def test_sync_symbols_adds_core_market_indices(self, mock_fetch_cn, mock_fetch_hk, mock_fetch_us):
        mock_fetch_cn.return_value = [
            InstrumentPayload(
                symbol="600519.SH",
                short_code="600519",
                name="Kweichow Moutai",
                asset_class=Instrument.AssetClass.STOCK,
                market=Instrument.Market.CN,
                exchange="SH",
                base_currency="CNY",
                is_active=True,
            )
        ]
        mock_fetch_hk.return_value = [
            InstrumentPayload(
                symbol="00700.HK",
                short_code="00700",
                name="Tencent",
                asset_class=Instrument.AssetClass.STOCK,
                market=Instrument.Market.HK,
                exchange="HKEX",
                base_currency="HKD",
                is_active=True,
            )
        ]
        mock_fetch_us.return_value = [
            InstrumentPayload(
                symbol="AAPL.US",
                short_code="AAPL",
                name="Apple Inc.",
                asset_class=Instrument.AssetClass.STOCK,
                market=Instrument.Market.US,
                exchange="NASDAQ",
                base_currency="USD",
                is_active=True,
            )
        ]

        out = StringIO()
        call_command("sync_symbols", "--markets", "cn", "hk", "us", stdout=out)

        symbols = set(
            Instrument.objects
            .filter(asset_class=Instrument.AssetClass.INDEX)
            .values_list("symbol", flat=True)
        )
        self.assertTrue(
            {
                "SPX.US",
                "NDX.US",
                "DJI.US",
                "000001.SH",
                "399001.SZ",
                "HSI.HK",
            }.issubset(symbols)
        )
