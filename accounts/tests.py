from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import StringIO
from threading import Barrier
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import close_old_connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import Accounts, Transaction, Transfer
from accounts.management.commands.sync_symbols import InstrumentPayload
from accounts.services.quote_providers import fetch_crypto_quotes_binance
from investment.models import Position
from market.models import Instrument
from accounts.services.quote_fetcher import _to_billion_amount
from market.services.cache_keys import USD_EXCHANGE_RATES_KEY, WATCHLIST_QUOTES_KEY
from snapshot.models import AccountSnapshot, SnapshotDataStatus, SnapshotLevel


class QuoteFetcherUnitTests(SimpleTestCase):
    def test_to_billion_amount_rounds_to_two_decimals(self):
        self.assertEqual(_to_billion_amount(123456789), 1.23)
        self.assertEqual(_to_billion_amount(100000000), 1.0)
        self.assertIsNone(_to_billion_amount(0))


class SyncSymbolsCommandTests(SimpleTestCase):
    @patch("accounts.management.commands.sync_symbols.Command.upsert_instruments", return_value=(1, 0, 1))
    @patch("accounts.management.commands.sync_symbols.Command.fetch_cn_stocks")
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

    @patch("accounts.management.commands.sync_symbols.Command.upsert_instruments", return_value=(1, 0, 1))
    @patch("accounts.management.commands.sync_symbols.Command.fetch_hk_stocks", side_effect=ValueError("hk provider down"))
    @patch("accounts.management.commands.sync_symbols.Command.fetch_cn_stocks")
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
    @patch("accounts.management.commands.sync_symbols.Command.fetch_cn_stocks")
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

    @patch("accounts.management.commands.sync_symbols.Command.fetch_hk_stocks")
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
    @patch("accounts.management.commands.sync_symbols.Command.fetch_us_stocks")
    @patch("accounts.management.commands.sync_symbols.Command.fetch_hk_stocks")
    @patch("accounts.management.commands.sync_symbols.Command.fetch_cn_stocks")
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


class CryptoQuoteProviderTests(SimpleTestCase):
    @patch("accounts.services.quote_providers._get_binance_supported_symbols", return_value={"BTCUSDT"})
    @patch("accounts.services.quote_providers.requests.get")
    def test_fetch_crypto_quotes_binance_filters_unsupported_symbols(self, mock_get, _mock_supported):
        def _mock_response(url, *args, **kwargs):
            self.assertIn("BTCUSDT", url)
            self.assertNotIn("OKBUSDT", url)
            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = [
                {
                    "symbol": "BTCUSDT",
                    "prevClosePrice": "62000",
                    "lastPrice": "63000",
                    "highPrice": "63500",
                    "lowPrice": "61500",
                    "priceChangePercent": "1.61",
                    "quoteVolume": "250000000",
                }
            ]
            return response

        mock_get.side_effect = _mock_response
        rows = fetch_crypto_quotes_binance(
            [
                ("BTC.CRYPTO", "BTC", "Bitcoin"),
                ("OKB.CRYPTO", "OKB", "OKB"),
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].short_code, "BTC")
        self.assertEqual(rows[0].price, 63000.0)


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "accounts-basic-tests",
        }
    }
)
class AccountsBasicApiTests(APITestCase):
    account_endpoint = "/api/user/accounts/"
    tx_endpoint = "/api/user/transactions/"
    transfer_endpoint = "/api/user/transfers/"

    def setUp(self):
        cache.clear()
        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {
                "base": "USD",
                "rates": {
                    "USD": 1.0,
                    "CNY": 7.0,
                    "JPY": 140.0,
                },
            },
            timeout=None,
        )
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="acc_basic_user", password="test123456")
        self.client.force_authenticate(self.user)
        self.account = Accounts.objects.create(
            user=self.user,
            name="Cash CNY",
            type=Accounts.AccountType.CASH,
            currency="CNY",
            balance=Decimal("1000.00"),
            status=Accounts.Status.ACTIVE,
        )

    def _create_usd_transfer_accounts(self) -> tuple[Accounts, Accounts]:
        from_account = Accounts.objects.create(
            user=self.user,
            name="Transfer USD A",
            type=Accounts.AccountType.CASH,
            currency="USD",
            balance=Decimal("500.00"),
            status=Accounts.Status.ACTIVE,
        )
        to_account = Accounts.objects.create(
            user=self.user,
            name="Transfer USD B",
            type=Accounts.AccountType.BANK,
            currency="USD",
            balance=Decimal("100.00"),
            status=Accounts.Status.ACTIVE,
        )
        return from_account, to_account

    def _create_transfer(self, *, from_account: Accounts, to_account: Accounts, amount: str = "120.00", note: str = ""):
        return self.client.post(
            self.transfer_endpoint,
            {
                "from_account_id": from_account.id,
                "to_account_id": to_account.id,
                "amount": amount,
                "note": note,
            },
            format="json",
        )

    def test_account_list_only_returns_current_user_data(self):
        other_user = get_user_model().objects.create_user(username="acc_other_user", password="test123456")
        Accounts.objects.create(
            user=other_user,
            name="Other Cash",
            type=Accounts.AccountType.CASH,
            currency="CNY",
            balance=Decimal("100.00"),
            status=Accounts.Status.ACTIVE,
        )

        resp = self.client.get(self.account_endpoint)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["name"], "Cash CNY")

    def test_create_investment_account_is_forbidden(self):
        resp = self.client.post(
            self.account_endpoint,
            {
                "name": "投资账户",
                "type": Accounts.AccountType.INVESTMENT,
                "currency": "USD",
                "balance": "0.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data.get("message"), "投资账户由系统自动维护，不能手动创建。")

    def test_transaction_create_and_reverse(self):
        create_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "午餐",
                "amount": "-50.00",
                "category_name": "餐饮",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        tx_id = create_resp.data["id"]

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("950.00"))

        reverse_resp = self.client.post(f"{self.tx_endpoint}{tx_id}/reverse/", {}, format="json")
        self.assertEqual(reverse_resp.status_code, status.HTTP_201_CREATED)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertEqual(Transaction.objects.count(), 2)

    def test_transaction_activity_type_filters_manual_investment_and_reversed(self):
        manual_reversed_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "午餐",
                "amount": "-50.00",
                "category_name": "餐饮",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(manual_reversed_resp.status_code, status.HTTP_201_CREATED)
        manual_reversed_id = manual_reversed_resp.data["id"]

        manual_normal_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "地铁",
                "amount": "-10.00",
                "category_name": "交通",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(manual_normal_resp.status_code, status.HTTP_201_CREATED)
        manual_normal_id = manual_normal_resp.data["id"]

        reverse_resp = self.client.post(f"{self.tx_endpoint}{manual_reversed_id}/reverse/", {}, format="json")
        self.assertEqual(reverse_resp.status_code, status.HTTP_201_CREATED)

        investment_tx = Transaction.objects.create(
            user=self.user,
            account=self.account,
            counterparty="Apple Inc.",
            amount=Decimal("-100.00"),
            category_name="买入",
            source=Transaction.Source.INVESTMENT,
        )

        manual_list_resp = self.client.get(f"{self.tx_endpoint}?activity_type=manual")
        self.assertEqual(manual_list_resp.status_code, status.HTTP_200_OK)
        manual_ids = {item["id"] for item in manual_list_resp.data["results"]}
        self.assertEqual(manual_ids, {manual_normal_id})

        investment_list_resp = self.client.get(f"{self.tx_endpoint}?activity_type=investment")
        self.assertEqual(investment_list_resp.status_code, status.HTTP_200_OK)
        investment_ids = {item["id"] for item in investment_list_resp.data["results"]}
        self.assertEqual(investment_ids, {investment_tx.id})

        reversed_list_resp = self.client.get(f"{self.tx_endpoint}?activity_type=reversed")
        self.assertEqual(reversed_list_resp.status_code, status.HTTP_200_OK)
        reversed_ids = {item["id"] for item in reversed_list_resp.data["results"]}
        self.assertEqual(reversed_ids, {manual_reversed_id})

    def test_transaction_activity_type_validation(self):
        resp = self.client.get(f"{self.tx_endpoint}?activity_type=unknown")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("activity_type", resp.data)

    def test_delete_single_transaction_endpoint(self):
        create_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "午餐",
                "amount": "-50.00",
                "category_name": "餐饮",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        tx_id = create_resp.data["id"]

        delete_resp = self.client.post(
            f"{self.tx_endpoint}delete/",
            {"mode": "single", "transaction_id": tx_id},
            format="json",
        )
        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_resp.data["visible_deleted"], 1)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("950.00"))
        self.assertFalse(Transaction.objects.filter(id=tx_id).exists())

    def test_delete_activity_transactions_endpoint(self):
        manual_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "地铁",
                "amount": "-10.00",
                "category_name": "交通",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(manual_resp.status_code, status.HTTP_201_CREATED)
        manual_id = manual_resp.data["id"]

        reversed_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "午餐",
                "amount": "-50.00",
                "category_name": "餐饮",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(reversed_resp.status_code, status.HTTP_201_CREATED)
        reversed_id = reversed_resp.data["id"]
        reverse_action_resp = self.client.post(f"{self.tx_endpoint}{reversed_id}/reverse/", {}, format="json")
        self.assertEqual(reverse_action_resp.status_code, status.HTTP_201_CREATED)

        investment_tx = Transaction.objects.create(
            user=self.user,
            account=self.account,
            counterparty="Apple Inc.",
            amount=Decimal("-100.00"),
            category_name="买入",
            source=Transaction.Source.INVESTMENT,
        )

        self.account.refresh_from_db()
        balance_before_delete = self.account.balance

        delete_investment_resp = self.client.post(
            f"{self.tx_endpoint}delete/",
            {"mode": "activity", "activity_type": "investment"},
            format="json",
        )
        self.assertEqual(delete_investment_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_investment_resp.data["visible_deleted"], 1)
        self.assertFalse(Transaction.objects.filter(id=investment_tx.id).exists())

        delete_reversed_resp = self.client.post(
            f"{self.tx_endpoint}delete/",
            {"mode": "activity", "activity_type": "reversed"},
            format="json",
        )
        self.assertEqual(delete_reversed_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_reversed_resp.data["visible_deleted"], 1)
        self.assertFalse(Transaction.objects.filter(id=reversed_id).exists())

        delete_manual_resp = self.client.post(
            f"{self.tx_endpoint}delete/",
            {"mode": "activity", "activity_type": "manual"},
            format="json",
        )
        self.assertEqual(delete_manual_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_manual_resp.data["visible_deleted"], 1)
        self.assertFalse(Transaction.objects.filter(id=manual_id).exists())

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, balance_before_delete)

    def test_transaction_create_rejects_investment_account(self):
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="CNY",
            balance=Decimal("999.99"),
            status=Accounts.Status.ACTIVE,
        )

        resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "手工调整",
                "amount": "100.00",
                "category_name": "调整",
                "account": investment_account.id,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Transaction.objects.count(), 0)
        investment_account.refresh_from_db()
        self.assertEqual(investment_account.balance, Decimal("999.99"))

    def test_account_currency_change_converts_balance_by_fx_rate(self):
        resp = self.client.patch(
            f"{self.account_endpoint}{self.account.id}/",
            {"currency": "USD"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.account.refresh_from_db()
        self.assertEqual(self.account.currency, "USD")
        self.assertEqual(self.account.balance, Decimal("142.86"))

    def test_reverse_transaction_after_account_currency_change_converts_amount(self):
        create_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "房租",
                "amount": "-700.00",
                "category_name": "住房",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        tx_id = create_resp.data["id"]

        patch_resp = self.client.patch(
            f"{self.account_endpoint}{self.account.id}/",
            {"currency": "USD"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        reverse_resp = self.client.post(f"{self.tx_endpoint}{tx_id}/reverse/", {}, format="json")
        self.assertEqual(reverse_resp.status_code, status.HTTP_201_CREATED)

        self.account.refresh_from_db()
        reversal_tx = Transaction.objects.get(reversal_of_id=tx_id)
        self.assertEqual(self.account.currency, "USD")
        self.assertEqual(self.account.balance, Decimal("142.86"))
        self.assertEqual(reversal_tx.currency, "USD")
        self.assertEqual(reversal_tx.amount, Decimal("100.00"))

    def test_delete_single_transaction_after_account_currency_change_keeps_current_balance(self):
        create_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "房租",
                "amount": "-700.00",
                "category_name": "住房",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        tx_id = create_resp.data["id"]

        patch_resp = self.client.patch(
            f"{self.account_endpoint}{self.account.id}/",
            {"currency": "USD"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        delete_resp = self.client.post(
            f"{self.tx_endpoint}delete/",
            {"mode": "single", "transaction_id": tx_id},
            format="json",
        )
        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)

        self.account.refresh_from_db()
        self.assertEqual(self.account.currency, "USD")
        self.assertEqual(self.account.balance, Decimal("42.86"))
        self.assertFalse(Transaction.objects.filter(id=tx_id).exists())

    def test_reverse_transaction_after_account_currency_change_fails_when_rate_pair_missing(self):
        create_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "房租",
                "amount": "-700.00",
                "category_name": "住房",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        tx_id = create_resp.data["id"]

        patch_resp = self.client.patch(
            f"{self.account_endpoint}{self.account.id}/",
            {"currency": "USD"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {
                "base": "USD",
                "rates": {
                    "USD": 1.0,
                },
            },
            timeout=None,
        )

        reverse_resp = self.client.post(f"{self.tx_endpoint}{tx_id}/reverse/", {}, format="json")
        self.assertEqual(reverse_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("message", reverse_resp.data)
        self.assertIn("CNY/USD", reverse_resp.data["message"])

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("42.86"))
        self.assertFalse(Transaction.objects.filter(reversal_of_id=tx_id).exists())

    def test_delete_single_transaction_after_account_currency_change_does_not_require_fx_rate(self):
        create_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "房租",
                "amount": "-700.00",
                "category_name": "住房",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        tx_id = create_resp.data["id"]

        patch_resp = self.client.patch(
            f"{self.account_endpoint}{self.account.id}/",
            {"currency": "USD"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {
                "base": "USD",
                "rates": {
                    "USD": 1.0,
                },
            },
            timeout=None,
        )

        delete_resp = self.client.post(
            f"{self.tx_endpoint}delete/",
            {"mode": "single", "transaction_id": tx_id},
            format="json",
        )
        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("42.86"))
        self.assertFalse(Transaction.objects.filter(id=tx_id).exists())

    def test_account_currency_change_fails_when_rate_pair_missing(self):
        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {
                "base": "USD",
                "rates": {
                    "USD": 1.0,
                    "CNY": 7.0,
                },
            },
            timeout=None,
        )
        resp = self.client.patch(
            f"{self.account_endpoint}{self.account.id}/",
            {"currency": "JPY"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("message", resp.data)
        self.assertIn("currency", resp.data)
        self.account.refresh_from_db()
        self.assertEqual(self.account.currency, "CNY")
        self.assertEqual(self.account.balance, Decimal("1000.00"))

    def test_create_transfer_success_writes_two_transactions_and_updates_balances(self):
        from_account, to_account = self._create_usd_transfer_accounts()

        resp = self._create_transfer(
            from_account=from_account,
            to_account=to_account,
            amount="120.00",
            note="账户互转",
        )

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["status"], Transfer.Status.SUCCESS)
        self.assertEqual(resp.data["currency"], "USD")
        self.assertEqual(resp.data["amount"], "120.00")

        from_account.refresh_from_db()
        to_account.refresh_from_db()
        self.assertEqual(from_account.balance, Decimal("380.00"))
        self.assertEqual(to_account.balance, Decimal("220.00"))

        transfer = Transfer.objects.get(pk=resp.data["id"])
        out_tx = Transaction.objects.get(pk=transfer.out_transaction_id)
        in_tx = Transaction.objects.get(pk=transfer.in_transaction_id)

        self.assertEqual(out_tx.source, Transaction.Source.TRANSFER)
        self.assertEqual(out_tx.counterparty, to_account.name)
        self.assertEqual(out_tx.category_name, "转账")
        self.assertEqual(out_tx.remark, "转出")
        self.assertEqual(out_tx.amount, Decimal("-120.00"))
        self.assertEqual(out_tx.balance_after, Decimal("380.00"))

        self.assertEqual(in_tx.source, Transaction.Source.TRANSFER)
        self.assertEqual(in_tx.counterparty, from_account.name)
        self.assertEqual(in_tx.category_name, "转账")
        self.assertEqual(in_tx.remark, "转入")
        self.assertEqual(in_tx.amount, Decimal("120.00"))
        self.assertEqual(in_tx.balance_after, Decimal("220.00"))

    def test_create_transfer_rejects_currency_mismatch(self):
        from_account, _ = self._create_usd_transfer_accounts()

        resp = self._create_transfer(
            from_account=from_account,
            to_account=self.account,
            amount="10.00",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("to_account_id", resp.data)
        self.assertEqual(Transfer.objects.count(), 0)

    def test_create_transfer_rejects_investment_account(self):
        _, to_account = self._create_usd_transfer_accounts()
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="USD",
            balance=Decimal("300.00"),
            status=Accounts.Status.ACTIVE,
        )

        resp = self._create_transfer(
            from_account=investment_account,
            to_account=to_account,
            amount="10.00",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("from_account_id", resp.data)
        self.assertEqual(Transfer.objects.count(), 0)

    def test_reverse_transfer_from_outgoing_transaction_reverses_whole_transfer(self):
        from_account, to_account = self._create_usd_transfer_accounts()
        create_resp = self._create_transfer(from_account=from_account, to_account=to_account, amount="120.00")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        out_tx_id = create_resp.data["out_transaction_id"]
        reverse_resp = self.client.post(f"{self.tx_endpoint}{out_tx_id}/reverse/", {}, format="json")

        self.assertEqual(reverse_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(reverse_resp.data["status"], Transfer.Status.REVERSED)

        from_account.refresh_from_db()
        to_account.refresh_from_db()
        self.assertEqual(from_account.balance, Decimal("500.00"))
        self.assertEqual(to_account.balance, Decimal("100.00"))

        transfer = Transfer.objects.get(pk=create_resp.data["id"])
        self.assertEqual(transfer.status, Transfer.Status.REVERSED)
        self.assertIsNotNone(transfer.reversed_out_transaction_id)
        self.assertIsNotNone(transfer.reversed_in_transaction_id)
        self.assertEqual(Transaction.objects.filter(source=Transaction.Source.REVERSAL).count(), 2)

    def test_reverse_transfer_from_incoming_transaction_reverses_whole_transfer(self):
        from_account, to_account = self._create_usd_transfer_accounts()
        create_resp = self._create_transfer(from_account=from_account, to_account=to_account, amount="80.00")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        in_tx_id = create_resp.data["in_transaction_id"]
        reverse_resp = self.client.post(f"{self.tx_endpoint}{in_tx_id}/reverse/", {}, format="json")

        self.assertEqual(reverse_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(reverse_resp.data["status"], Transfer.Status.REVERSED)

        from_account.refresh_from_db()
        to_account.refresh_from_db()
        self.assertEqual(from_account.balance, Decimal("500.00"))
        self.assertEqual(to_account.balance, Decimal("100.00"))

    def test_reverse_transfer_from_transfer_endpoint(self):
        from_account, to_account = self._create_usd_transfer_accounts()
        create_resp = self._create_transfer(from_account=from_account, to_account=to_account, amount="60.00")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        reverse_resp = self.client.post(f"{self.transfer_endpoint}{create_resp.data['id']}/reverse/", {}, format="json")

        self.assertEqual(reverse_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(reverse_resp.data["status"], Transfer.Status.REVERSED)

        from_account.refresh_from_db()
        to_account.refresh_from_db()
        self.assertEqual(from_account.balance, Decimal("500.00"))
        self.assertEqual(to_account.balance, Decimal("100.00"))

    def test_transaction_activity_type_transfer_returns_transfer_rows(self):
        from_account, to_account = self._create_usd_transfer_accounts()
        create_resp = self._create_transfer(from_account=from_account, to_account=to_account, amount="40.00")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        list_resp = self.client.get(f"{self.tx_endpoint}?activity_type=transfer")

        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        result_ids = {item["id"] for item in list_resp.data["results"]}
        self.assertEqual(result_ids, {create_resp.data["out_transaction_id"], create_resp.data["in_transaction_id"]})

    def test_delete_transfer_transaction_is_blocked(self):
        from_account, to_account = self._create_usd_transfer_accounts()
        create_resp = self._create_transfer(from_account=from_account, to_account=to_account, amount="50.00")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        delete_resp = self.client.delete(f"{self.tx_endpoint}{create_resp.data['out_transaction_id']}/")

        self.assertEqual(delete_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("transaction_id", delete_resp.data)

    def test_investment_account_balance_returns_current_account_balance(self):
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="USD",
            balance=Decimal("77.77"),
            status=Accounts.Status.ACTIVE,
        )
        AccountSnapshot.objects.create(
            account=investment_account,
            snapshot_level=SnapshotLevel.M15,
            snapshot_time="2026-03-04T00:00:00Z",
            account_currency="USD",
            balance_native=Decimal("1234.567891"),
            balance_usd=Decimal("1234.567891"),
            data_status=SnapshotDataStatus.OK,
        )

        resp = self.client.get(self.account_endpoint)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        target = next(item for item in resp.data if item["id"] == investment_account.id)
        self.assertEqual(target["balance"], "77.77")

    def test_investment_account_detail_returns_current_account_balance(self):
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="USD",
            balance=Decimal("66.66"),
            status=Accounts.Status.ACTIVE,
        )
        AccountSnapshot.objects.create(
            account=investment_account,
            snapshot_level=SnapshotLevel.M15,
            snapshot_time="2026-03-04T00:00:00Z",
            account_currency="USD",
            balance_native=Decimal("88.888888"),
            balance_usd=Decimal("88.888888"),
            data_status=SnapshotDataStatus.OK,
        )

        resp = self.client.get(f"{self.account_endpoint}{investment_account.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["balance"], "66.66")

    def test_investment_account_currency_change_revalues_from_live_positions_not_snapshot(self):
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="CNY",
            balance=Decimal("0.00"),
            status=Accounts.Status.ACTIVE,
        )
        instrument = Instrument.objects.create(
            symbol="AAPL.US",
            short_code="AAPL",
            name="Apple Inc.",
            asset_class=Instrument.AssetClass.STOCK,
            market=Instrument.Market.US,
            exchange="NASDAQ",
            base_currency="USD",
            is_active=True,
        )
        cache.set(
            WATCHLIST_QUOTES_KEY,
            {
                "updated_at": "2026-03-04T00:00:00+08:00",
                "updated_markets": ["US"],
                "stale_markets": [],
                "data": {
                    "US": [
                        {
                            "short_code": "AAPL",
                            "name": "Apple Inc.",
                            "price": 12.0,
                        }
                    ]
                },
            },
            timeout=None,
        )
        Position.objects.create(
            user=self.user,
            instrument=instrument,
            quantity=Decimal("2.000000"),
            avg_cost=Decimal("10.000000"),
            cost_total=Decimal("20.000000"),
            realized_pnl_total=Decimal("0"),
        )
        AccountSnapshot.objects.create(
            account=investment_account,
            snapshot_level=SnapshotLevel.M15,
            snapshot_time="2026-03-04T00:00:00Z",
            account_currency="CNY",
            balance_native=Decimal("999.000000"),
            balance_usd=Decimal("142.714286"),
            data_status=SnapshotDataStatus.OK,
        )

        resp = self.client.patch(
            f"{self.account_endpoint}{investment_account.id}/",
            {"currency": "USD"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["currency"], "USD")
        self.assertEqual(resp.data["balance"], "24.00")

        investment_account.refresh_from_db()
        self.assertEqual(investment_account.currency, "USD")
        self.assertEqual(investment_account.balance, Decimal("24.00"))

        detail_resp = self.client.get(f"{self.account_endpoint}{investment_account.id}/")
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_resp.data["balance"], "24.00")

    def test_delete_normal_account_archives_and_keeps_transactions(self):
        tx_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "地铁",
                "amount": "-10.00",
                "category_name": "交通",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(tx_resp.status_code, status.HTTP_201_CREATED)

        delete_resp = self.client.delete(f"{self.account_endpoint}{self.account.id}/")
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

        self.account.refresh_from_db()
        self.assertEqual(self.account.status, Accounts.Status.ARCHIVED)
        self.assertEqual(Transaction.objects.filter(account=self.account).count(), 1)

        list_resp = self.client.get(self.account_endpoint)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_resp.data), 0)

        list_with_archived_resp = self.client.get(f"{self.account_endpoint}?include_archived=1")
        self.assertEqual(list_with_archived_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_with_archived_resp.data), 1)
        self.assertEqual(list_with_archived_resp.data[0]["status"], Accounts.Status.ARCHIVED)

    def test_delete_investment_account_blocked_when_has_positions(self):
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="USD",
            balance=Decimal("123.45"),
            status=Accounts.Status.ACTIVE,
        )
        instrument = Instrument.objects.create(
            symbol="AAPL.US",
            short_code="AAPL",
            name="Apple Inc.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            base_currency="USD",
            is_active=True,
        )
        Position.objects.create(
            user=self.user,
            instrument=instrument,
            quantity=Decimal("1.000000"),
            avg_cost=Decimal("100.000000"),
            cost_total=Decimal("100.000000"),
        )

        delete_resp = self.client.delete(f"{self.account_endpoint}{investment_account.id}/")
        self.assertEqual(delete_resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(delete_resp.data["code"], "investment_account_delete_blocked")

        investment_account.refresh_from_db()
        self.assertEqual(investment_account.status, Accounts.Status.ACTIVE)

    def test_delete_investment_account_without_positions_archives(self):
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="USD",
            balance=Decimal("0.00"),
            status=Accounts.Status.ACTIVE,
        )

        delete_resp = self.client.delete(f"{self.account_endpoint}{investment_account.id}/")
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

        investment_account.refresh_from_db()
        self.assertEqual(investment_account.status, Accounts.Status.ARCHIVED)


class AccountsComplexApiTests(TransactionTestCase):
    tx_endpoint = "/api/user/transactions/"

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="acc_complex_user", password="test123456")
        self.account = Accounts.objects.create(
            user=self.user,
            name="Bank CNY",
            type=Accounts.AccountType.BANK,
            currency="CNY",
            balance=Decimal("1000.00"),
            status=Accounts.Status.ACTIVE,
        )
        self.tx = Transaction.objects.create(
            user=self.user,
            account=self.account,
            counterparty="工资",
            amount=Decimal("100.00"),
            category_name="收入",
        )

    def _reverse_once(self, gate: Barrier) -> int:
        close_old_connections()
        client = APIClient()
        client.force_authenticate(self.user)
        gate.wait(timeout=5)
        resp = client.post(f"{self.tx_endpoint}{self.tx.id}/reverse/", {}, format="json")
        close_old_connections()
        return resp.status_code

    def test_concurrent_reverse_only_one_succeeds(self):
        gate = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self._reverse_once, gate) for _ in range(2)]
            statuses = sorted(f.result(timeout=10) for f in futures)

        self.assertEqual(statuses, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertEqual(Transaction.objects.count(), 2)
