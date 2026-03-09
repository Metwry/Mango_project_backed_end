from unittest.mock import patch
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Instrument, UserInstrumentSubscription
from market.services.cache_keys import USD_EXCHANGE_RATES_KEY, WATCHLIST_QUOTES_KEY
from market.services.index_quote_service import build_market_indices_snapshot
from market.services.quote_snapshot_service import orphan_quote_cache_key


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "market-basic-tests",
        }
    }
)
class MarketBasicApiTests(APITestCase):
    watchlist_endpoint = "/api/user/markets/watchlist/"

    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="market_basic_user", password="test123456")
        self.client.force_authenticate(self.user)
        self.instrument = Instrument.objects.create(
            symbol="AAPL.US",
            short_code="AAPL",
            name="Apple Inc.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            is_active=True,
        )

    @patch("market.services.quote_snapshot_service.pull_single_instrument_quote")
    def test_watchlist_add_and_snapshot_query(self, mock_pull):
        mock_pull.return_value = {
            "short_code": "AAPL",
            "name": "Apple Inc.",
            "price": 200.0,
            "prev_close": 199.0,
            "day_high": 201.0,
            "day_low": 198.0,
            "pct": 0.5,
            "volume": 10.0,
        }
        add_resp = self.client.post(self.watchlist_endpoint, {"symbol": "AAPL.US"}, format="json")
        self.assertEqual(add_resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(add_resp.data["quote_ready"])
        self.assertEqual(add_resp.data["quote_source"], "api")

        sub = UserInstrumentSubscription.objects.get(user=self.user, instrument=self.instrument)
        self.assertTrue(sub.from_watchlist)
        self.assertFalse(sub.from_position)

        snapshot_resp = self.client.get("/api/user/markets/")
        self.assertEqual(snapshot_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(snapshot_resp.data["markets"]), 1)
        self.assertEqual(snapshot_resp.data["markets"][0]["market"], "US")
        self.assertEqual(snapshot_resp.data["markets"][0]["quotes"][0]["logo_url"], None)
        self.assertEqual(snapshot_resp.data["markets"][0]["quotes"][0]["logo_color"], None)

    def test_watchlist_add_rejects_index_instrument(self):
        Instrument.objects.create(
            symbol="SPX.US",
            short_code="SPX",
            name="S&P 500",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.INDEX,
            is_active=True,
        )

        resp = self.client.post(self.watchlist_endpoint, {"symbol": "SPX.US"}, format="json")

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("message", resp.data)
        self.assertIn("指数暂不支持加入自选", resp.data["message"])

    @patch(
        "market.views.build_market_indices_snapshot",
        return_value={
            "updated_at": "2026-03-07T09:30:00+08:00",
            "items": [
                {
                    "instrument_id": 101,
                    "name": "S&P500",
                    "prev_close": "5100",
                    "day_high": "5150",
                    "day_low": "5080",
                    "pct": "0.8",
                }
            ],
        },
    )
    def test_market_indices_endpoint_returns_payload(self, _mock_snapshot):
        resp = self.client.get("/api/user/markets/indices/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["updated_at"], "2026-03-07T09:30:00+08:00")
        self.assertEqual(resp.data["items"][0]["name"], "S&P500")
        self.assertEqual(resp.data["items"][0]["pct"], "0.8")

    @override_settings(MARKET_QUOTE_PROVIDER="fake", MARKET_INDEX_PROVIDER="fake")
    def test_build_market_indices_snapshot_with_fake_provider(self):
        Instrument.objects.create(
            symbol="SPX.US",
            short_code="SPX",
            name="S&P500",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.INDEX,
            is_active=True,
        )
        Instrument.objects.create(
            symbol="HSI.HK",
            short_code="HSI",
            name="恒生指数",
            market=Instrument.Market.HK,
            asset_class=Instrument.AssetClass.INDEX,
            is_active=True,
        )

        payload = build_market_indices_snapshot()

        self.assertIn("updated_at", payload)
        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual(payload["items"][0]["name"], "S&P500")
        self.assertIsNotNone(payload["items"][0]["prev_close"])

    def test_latest_quotes_batch_reads_from_redis(self):
        cache.set(
            WATCHLIST_QUOTES_KEY,
            {
                "data": {
                    "US": [{"short_code": "MSFT", "price": 392.74}],
                    "CN": [{"short_code": "600519", "price": 1520.00}],
                }
            },
            timeout=None,
        )
        resp = self.client.post(
            "/api/user/markets/quotes/latest/",
            {
                "items": [
                    {"market": "US", "short_code": "MSFT"},
                    {"market": "CN", "short_code": "600519"},
                    {"market": "US", "short_code": "AAPL"},
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp.data["quotes"],
            [
                {"market": "US", "short_code": "MSFT", "latest_price": "392.74", "logo_url": None, "logo_color": None},
                {"market": "CN", "short_code": "600519", "latest_price": "1520", "logo_url": None, "logo_color": None},
                {"market": "US", "short_code": "AAPL", "latest_price": None, "logo_url": None, "logo_color": None},
            ],
        )

    def test_market_search_returns_instrument_id(self):
        resp = self.client.get("/api/user/markets/search/?q=AAPL")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("results", resp.data)
        self.assertGreaterEqual(len(resp.data["results"]), 1)
        self.assertIn("instrument_id", resp.data["results"][0])


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "market-complex-tests",
        }
    }
)
class MarketComplexApiTests(APITestCase):
    watchlist_endpoint = "/api/user/markets/watchlist/"

    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="market_complex_user", password="test123456")
        self.client.force_authenticate(self.user)
        self.instrument = Instrument.objects.create(
            symbol="AAPL.US",
            short_code="AAPL",
            name="Apple Inc.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            is_active=True,
        )

    def test_watchlist_delete_keeps_subscription_when_position_source_exists(self):
        UserInstrumentSubscription.objects.create(
            user=self.user,
            instrument=self.instrument,
            from_position=True,
            from_watchlist=True,
        )
        resp = self.client.delete(self.watchlist_endpoint, {"symbol": "AAPL.US"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        sub = UserInstrumentSubscription.objects.get(user=self.user, instrument=self.instrument)
        self.assertTrue(sub.from_position)
        self.assertFalse(sub.from_watchlist)

    @patch("market.services.quote_snapshot_service.pull_single_instrument_quote")
    def test_delete_to_orphan_then_add_uses_orphan_quote(self, mock_pull):
        mock_pull.return_value = {
            "short_code": "AAPL",
            "name": "Apple Inc.",
            "price": 200.0,
        }
        add_resp = self.client.post(self.watchlist_endpoint, {"symbol": "AAPL.US"}, format="json")
        self.assertEqual(add_resp.status_code, status.HTTP_201_CREATED)

        del_resp = self.client.delete(self.watchlist_endpoint, {"symbol": "AAPL.US"}, format="json")
        self.assertEqual(del_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(UserInstrumentSubscription.objects.filter(user=self.user, instrument=self.instrument).exists())

        orphan_key = orphan_quote_cache_key("US", "AAPL")
        self.assertIsNotNone(cache.get(orphan_key))

        mock_pull.reset_mock()
        readd_resp = self.client.post(self.watchlist_endpoint, {"symbol": "AAPL.US"}, format="json")
        self.assertEqual(readd_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(readd_resp.data["quote_source"], "redis_orphan")
        mock_pull.assert_not_called()

    def test_fx_rates_base_conversion(self):
        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {
                "base": "USD",
                "updated_at": "2026-03-02T00:00:00+08:00",
                "rates": {"USD": 1.0, "CNY": 7.0},
            },
            timeout=None,
        )
        resp = self.client.get("/api/user/markets/fx-rates/?base=CNY")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["base"], "CNY")
        self.assertAlmostEqual(resp.data["rates"]["USD"], 1.0 / 7.0, places=6)


@override_settings(
    LOGO_DEV_IMAGE_BASE_URL="https://img.logo.dev",
    LOGO_DEV_PUBLISHABLE_KEY="pk_test_logo_token",
)
class MarketLogoSyncCommandTests(TestCase):
    @patch("market.management.commands.sync_logo_data.extract_logo_theme_color", return_value="#112233")
    def test_sync_logo_data_updates_us_hk_and_crypto_by_default(self, _mock_extract):
        us = Instrument.objects.create(
            symbol="AAPL.US",
            short_code="AAPL",
            name="Apple Inc.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            is_active=True,
        )
        hk = Instrument.objects.create(
            symbol="01810.HK",
            short_code="01810",
            name="Xiaomi",
            market=Instrument.Market.HK,
            asset_class=Instrument.AssetClass.STOCK,
            is_active=True,
        )
        crypto = Instrument.objects.create(
            symbol="BTC.CRYPTO",
            short_code="BTC",
            name="Bitcoin",
            market=Instrument.Market.CRYPTO,
            asset_class=Instrument.AssetClass.CRYPTO,
            is_active=True,
        )
        cn = Instrument.objects.create(
            symbol="000001.CN",
            short_code="000001",
            name="Ping An Bank",
            market=Instrument.Market.CN,
            asset_class=Instrument.AssetClass.STOCK,
            is_active=True,
        )

        call_command("sync_logo_data", stdout=StringIO())

        us.refresh_from_db()
        hk.refresh_from_db()
        crypto.refresh_from_db()
        cn.refresh_from_db()

        self.assertIn("/ticker/AAPL", us.logo_url)
        self.assertIn("token=pk_test_logo_token", us.logo_url)
        self.assertEqual(us.logo_color, "#112233")
        self.assertEqual(us.logo_source, "logo.dev:ticker")
        self.assertIsNotNone(us.logo_updated_at)

        self.assertIn("/crypto/btc", crypto.logo_url)
        self.assertIn("token=pk_test_logo_token", crypto.logo_url)
        self.assertEqual(crypto.logo_color, "#112233")
        self.assertEqual(crypto.logo_source, "logo.dev:crypto")
        self.assertIsNotNone(crypto.logo_updated_at)

        self.assertIn("/ticker/1810.HK", hk.logo_url)
        self.assertIn("token=pk_test_logo_token", hk.logo_url)
        self.assertEqual(hk.logo_color, "#112233")
        self.assertEqual(hk.logo_source, "logo.dev:ticker")
        self.assertIsNotNone(hk.logo_updated_at)

        self.assertIsNone(cn.logo_url)
        self.assertIsNone(cn.logo_color)
        self.assertIsNone(cn.logo_source)
        self.assertIsNone(cn.logo_updated_at)

    def test_sync_logo_data_without_force_keeps_existing_logo(self):
        fixed_time = timezone.now()
        inst = Instrument.objects.create(
            symbol="MSFT.US",
            short_code="MSFT",
            name="Microsoft",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            logo_url="https://example.com/static/msft.png",
            logo_color="#AABBCC",
            logo_source="manual",
            logo_updated_at=fixed_time,
            is_active=True,
        )

        call_command("sync_logo_data", stdout=StringIO())
        inst.refresh_from_db()

        self.assertEqual(inst.logo_url, "https://example.com/static/msft.png")
        self.assertEqual(inst.logo_color, "#AABBCC")
        self.assertEqual(inst.logo_source, "manual")
        self.assertEqual(inst.logo_updated_at, fixed_time)

    @patch("market.management.commands.sync_logo_data.extract_logo_theme_color", return_value=None)
    def test_sync_logo_data_sets_logo_color_null_when_extract_failed(self, _mock_extract):
        inst = Instrument.objects.create(
            symbol="SHOP.US",
            short_code="SHOP",
            name="Shopify",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            is_active=True,
        )

        call_command("sync_logo_data", stdout=StringIO())
        inst.refresh_from_db()

        self.assertIn("/ticker/SHOP", inst.logo_url)
        self.assertIsNone(inst.logo_color)

    @patch("market.management.commands.sync_logo_data.extract_logo_theme_color", return_value="#112233")
    def test_sync_logo_data_cn_uses_exchange_suffix(self, _mock_extract):
        sh = Instrument.objects.create(
            symbol="600519.CN",
            short_code="600519",
            name="Kweichow Moutai",
            market=Instrument.Market.CN,
            asset_class=Instrument.AssetClass.STOCK,
            is_active=True,
        )
        sz = Instrument.objects.create(
            symbol="000001.CN",
            short_code="000001",
            name="Ping An Bank",
            market=Instrument.Market.CN,
            asset_class=Instrument.AssetClass.STOCK,
            is_active=True,
        )

        call_command("sync_logo_data", "--markets", "cn", stdout=StringIO())

        sh.refresh_from_db()
        sz.refresh_from_db()

        self.assertIn("/ticker/600519.SS", sh.logo_url)
        self.assertIn("/ticker/000001.SZ", sz.logo_url)
        self.assertEqual(sh.logo_source, "logo.dev:ticker")
        self.assertEqual(sz.logo_source, "logo.dev:ticker")


class MarketCoreIndexSyncCommandTests(TestCase):
    def test_sync_core_indices_creates_selected_market_indices(self):
        call_command("sync_core_indices", "--markets", "us", "hk", stdout=StringIO())

        symbols = set(
            Instrument.objects
            .filter(asset_class=Instrument.AssetClass.INDEX)
            .values_list("symbol", flat=True)
        )

        self.assertIn("SPX.US", symbols)
        self.assertIn("NDX.US", symbols)
        self.assertIn("DJI.US", symbols)
        self.assertIn("HSI.HK", symbols)
        self.assertNotIn("000001.SH", symbols)
        self.assertNotIn("399001.SZ", symbols)
