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

from accounts.models import Accounts, Transaction
from accounts.management.commands.sync_symbols import InstrumentPayload
from accounts.services.quote_providers import fetch_crypto_quotes_binance
from investment.models import Position
from market.models import Instrument
from accounts.services.quote_providers import _to_billion_amount
from market.services.cache_keys import USD_EXCHANGE_RATES_KEY, WATCHLIST_QUOTES_KEY
from snapshot.models import AccountSnapshot, SnapshotDataStatus, SnapshotLevel


class QuoteFetcherUnitTests(SimpleTestCase):
    def test_to_billion_amount_rounds_to_two_decimals(self):
        """验证to billion amount 会将结果四舍五入到两位小数。"""
        self.assertEqual(_to_billion_amount(123456789), 1.23)
        self.assertEqual(_to_billion_amount(100000000), 1.0)
        self.assertIsNone(_to_billion_amount(0))


class SyncSymbolsCommandTests(SimpleTestCase):
    @patch("accounts.management.commands.sync_symbols.Command.upsert_instruments", return_value=(1, 0, 1))
    @patch("accounts.management.commands.sync_symbols.Command.fetch_cn_stocks")
    def test_sync_symbols_renders_progress_table_for_success(self, mock_fetch_cn, _mock_upsert):
        """验证同步 符号 在成功时渲染进度表。"""
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
        """验证同步 符号 在市场失败时渲染进度表。"""
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
        """验证同步 符号 在 insert-only 模式下保持已有记录不变。"""
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
        """验证同步 符号 保留已有记录的 图标 元数据。"""
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
        """验证同步 符号 补充核心市场指数。"""
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
        """验证fetch crypto quotes binance 会过滤不支持的符号。"""
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
    tx_delete_endpoint = "/api/user/transactions/delete/"

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
            self.tx_endpoint,
            {
                "account": from_account.id,
                "transfer_account": to_account.id,
                "amount": amount,
                "remark": note,
            },
            format="json",
        )

    def test_account_list_only_returns_current_user_data(self):
        """验证账户 列表 仅返回当前用户的数据。"""
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
        """验证创建 投资 账户 会被禁止。"""
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

    def test_create_account_allows_same_name_and_currency_when_type_differs(self):
        """验证创建 账户 在类型不同的情况下允许同名同币种账户。"""
        resp = self.client.post(
            self.account_endpoint,
            {
                "name": "Cash CNY",
                "type": Accounts.AccountType.BANK,
                "currency": "CNY",
                "balance": "50.00",
                "status": Accounts.Status.ACTIVE,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Accounts.objects.filter(user=self.user, name="Cash CNY", currency="CNY").count(),
            2,
        )

    def test_create_account_rejects_duplicate_name_type_and_currency(self):
        """验证创建 账户 会拒绝重复的名称、类型和币种组合。"""
        resp = self.client.post(
            self.account_endpoint,
            {
                "name": "Cash CNY",
                "type": Accounts.AccountType.CASH,
                "currency": "CNY",
                "balance": "50.00",
                "status": Accounts.Status.ACTIVE,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            resp.data["non_field_errors"][0],
            "您已存在同类型同币种的同名账户",
        )

    def test_update_account_rejects_duplicate_name_type_and_currency(self):
        """验证update 账户 会拒绝重复的名称、类型和币种组合。"""
        bank_account = Accounts.objects.create(
            user=self.user,
            name="Cash CNY",
            type=Accounts.AccountType.BANK,
            currency="CNY",
            balance=Decimal("100.00"),
            status=Accounts.Status.ACTIVE,
        )

        resp = self.client.patch(
            f"{self.account_endpoint}{bank_account.id}/",
            {"type": Accounts.AccountType.CASH},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            resp.data["non_field_errors"][0],
            "您已存在同类型同币种的同名账户",
        )

    def test_non_system_investment_type_account_allows_manual_transaction(self):
        """验证non system 投资 type 账户 允许手工交易。"""
        create_resp = self.client.post(
            self.account_endpoint,
            {
                "name": "自定义投资",
                "type": Accounts.AccountType.INVESTMENT,
                "currency": "USD",
                "balance": "100.00",
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        tx_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "测试记账",
                "amount": "-10.00",
                "category_name": "测试",
                "account": create_resp.data["id"],
            },
            format="json",
        )
        self.assertEqual(tx_resp.status_code, status.HTTP_201_CREATED)

    def test_transaction_create_and_reverse(self):
        """验证交易 创建后可以撤销。"""
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

    def test_transaction_update_is_blocked(self):
        """验证交易 不允许更新。"""
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

        patch_resp = self.client.patch(
            f"{self.tx_endpoint}{create_resp.data['id']}/",
            {"remark": "新备注"},
            format="json",
        )

        self.assertEqual(patch_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(patch_resp.data["message"], "交易记录不允许更改。")

    def test_transaction_list_filters_by_source_and_reversed_at(self):
        """验证交易 列表 支持按来源和撤销状态过滤。"""
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
        reversal_id = reverse_resp.data["id"]

        investment_tx = Transaction.objects.create(
            user=self.user,
            account=self.account,
            counterparty="Apple Inc.",
            amount=Decimal("-100.00"),
            category_name="买入",
            source=Transaction.Source.INVESTMENT,
        )

        all_list_resp = self.client.get(self.tx_endpoint)
        self.assertEqual(all_list_resp.status_code, status.HTTP_200_OK)
        all_ids = {item["id"] for item in all_list_resp.data["results"]}
        self.assertEqual(all_ids, {manual_reversed_id, manual_normal_id, reversal_id, investment_tx.id})

        manual_list_resp = self.client.get(f"{self.tx_endpoint}?source=manual")
        self.assertEqual(manual_list_resp.status_code, status.HTTP_200_OK)
        manual_ids = {item["id"] for item in manual_list_resp.data["results"]}
        self.assertEqual(manual_ids, {manual_reversed_id, manual_normal_id})

        investment_list_resp = self.client.get(f"{self.tx_endpoint}?source=investment")
        self.assertEqual(investment_list_resp.status_code, status.HTTP_200_OK)
        investment_ids = {item["id"] for item in investment_list_resp.data["results"]}
        self.assertEqual(investment_ids, {investment_tx.id})

        reversed_list_resp = self.client.get(f"{self.tx_endpoint}?reversed_at__isnull=false")
        self.assertEqual(reversed_list_resp.status_code, status.HTTP_200_OK)
        reversed_ids = {item["id"] for item in reversed_list_resp.data["results"]}
        self.assertEqual(reversed_ids, {manual_reversed_id})

    def test_delete_single_transaction_by_query_id(self):
        """验证删除 单条 交易 支持按查询参数中的 id 删除单条记录。"""
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

        delete_resp = self.client.delete(f"{self.tx_delete_endpoint}?id={tx_id}")
        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_resp.data["id"], tx_id)
        self.assertEqual(delete_resp.data["deleted_count"], 1)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("950.00"))
        self.assertFalse(Transaction.objects.filter(id=tx_id).exists())

    def test_delete_reversed_manual_transaction_removes_original_and_reversal_rows(self):
        """验证删除 reversed 手工 交易 会同时删除原始记录和冲正记录。"""
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
        reversal_id = reverse_action_resp.data["id"]

        self.account.refresh_from_db()
        balance_before_delete = self.account.balance

        delete_resp = self.client.delete(f"{self.tx_delete_endpoint}?id={reversed_id}")
        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_resp.data["deleted_count"], 1)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, balance_before_delete)
        self.assertFalse(Transaction.objects.filter(id=reversed_id).exists())
        self.assertFalse(Transaction.objects.filter(id=reversal_id).exists())

    def test_delete_investment_transaction_is_allowed(self):
        """验证删除 投资 交易 允许执行。"""
        investment_tx = Transaction.objects.create(
            user=self.user,
            account=self.account,
            counterparty="Apple Inc.",
            amount=Decimal("-100.00"),
            category_name="买入",
            source=Transaction.Source.INVESTMENT,
        )

        delete_resp = self.client.delete(f"{self.tx_delete_endpoint}?id={investment_tx.id}")

        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(Transaction.objects.filter(id=investment_tx.id).exists())

    def test_delete_reversal_transaction_directly_is_allowed(self):
        """验证删除 冲正 交易 directly 允许执行。"""
        create_resp = self.client.post(
            self.tx_endpoint,
            {
                "counterparty": "晚餐",
                "amount": "-30.00",
                "category_name": "餐饮",
                "account": self.account.id,
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        reverse_resp = self.client.post(f"{self.tx_endpoint}{create_resp.data['id']}/reverse/", {}, format="json")
        self.assertEqual(reverse_resp.status_code, status.HTTP_201_CREATED)

        delete_resp = self.client.delete(f"{self.tx_delete_endpoint}?id={reverse_resp.data['id']}")

        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(Transaction.objects.filter(id=reverse_resp.data["id"]).exists())
        self.assertTrue(Transaction.objects.filter(id=create_resp.data["id"]).exists())

    def test_transaction_create_rejects_investment_account(self):
        """验证交易 创建 会拒绝投资账户。"""
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
        """验证账户 币种 变更 会按汇率转换余额。"""
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
        """验证撤销 交易 after 账户 币种 变更 会转换金额。"""
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
        """验证删除 单条 交易 after 账户 币种 变更 会保持当前余额不变。"""
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

        delete_resp = self.client.delete(f"{self.tx_delete_endpoint}?id={tx_id}")
        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)

        self.account.refresh_from_db()
        self.assertEqual(self.account.currency, "USD")
        self.assertEqual(self.account.balance, Decimal("42.86"))
        self.assertFalse(Transaction.objects.filter(id=tx_id).exists())

    def test_reverse_transaction_after_account_currency_change_fails_when_rate_pair_missing(self):
        """验证撤销 交易 after 账户 币种 变更 在缺少汇率对时会失败。"""
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
        """验证删除 单条 交易 after 账户 币种 变更 不依赖汇率即可完成。"""
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

        delete_resp = self.client.delete(f"{self.tx_delete_endpoint}?id={tx_id}")
        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("42.86"))
        self.assertFalse(Transaction.objects.filter(id=tx_id).exists())

    def test_account_currency_change_fails_when_rate_pair_missing(self):
        """验证账户 币种 变更 在缺少汇率对时会失败。"""
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

    def test_create_transfer_transaction_updates_balances_and_returns_single_record(self):
        """验证创建 转账 交易 会更新余额并返回单条记录。"""
        from_account, to_account = self._create_usd_transfer_accounts()

        resp = self._create_transfer(
            from_account=from_account,
            to_account=to_account,
            amount="120.00",
            note="账户互转",
        )

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["source"], Transaction.Source.TRANSFER)
        self.assertEqual(resp.data["currency"], "USD")
        self.assertEqual(resp.data["amount"], "120.00")
        self.assertEqual(resp.data["account"], from_account.id)
        self.assertEqual(resp.data["transfer_account"], to_account.id)
        self.assertEqual(resp.data["account_name"], from_account.name)
        self.assertEqual(resp.data["transfer_account_name"], to_account.name)
        self.assertEqual(resp.data["counterparty"], to_account.name)
        self.assertEqual(resp.data["category_name"], "转账")
        self.assertEqual(resp.data["remark"], "账户互转")

        from_account.refresh_from_db()
        to_account.refresh_from_db()
        self.assertEqual(from_account.balance, Decimal("380.00"))
        self.assertEqual(to_account.balance, Decimal("220.00"))

        tx = Transaction.objects.get(pk=resp.data["id"])
        self.assertEqual(tx.source, Transaction.Source.TRANSFER)
        self.assertEqual(tx.account_id, from_account.id)
        self.assertEqual(tx.transfer_account_id, to_account.id)
        self.assertEqual(tx.amount, Decimal("120.00"))
        self.assertEqual(tx.balance_after, Decimal("380.00"))

    def test_create_transfer_rejects_currency_mismatch(self):
        """验证创建 转账 会拒绝币种不匹配的情况。"""
        from_account, _ = self._create_usd_transfer_accounts()

        resp = self._create_transfer(
            from_account=from_account,
            to_account=self.account,
            amount="10.00",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("transfer_account", resp.data)
        self.assertEqual(Transaction.objects.filter(source=Transaction.Source.TRANSFER).count(), 0)

    def test_create_transfer_rejects_investment_account(self):
        """验证创建 转账 会拒绝投资账户。"""
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
        self.assertIn("account", resp.data)
        self.assertEqual(Transaction.objects.filter(source=Transaction.Source.TRANSFER).count(), 0)

    def test_reverse_transfer_record_is_blocked(self):
        """验证撤销 转账 会被阻止。"""
        from_account, to_account = self._create_usd_transfer_accounts()
        create_resp = self._create_transfer(from_account=from_account, to_account=to_account, amount="120.00")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        reverse_resp = self.client.post(f"{self.tx_endpoint}{create_resp.data['id']}/reverse/", {}, format="json")

        self.assertEqual(reverse_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(reverse_resp.data["message"], "转账记录不支持撤销，请直接删除记录。")

        from_account.refresh_from_db()
        to_account.refresh_from_db()
        self.assertEqual(from_account.balance, Decimal("380.00"))
        self.assertEqual(to_account.balance, Decimal("220.00"))
        self.assertEqual(Transaction.objects.filter(source=Transaction.Source.REVERSAL).count(), 0)

    def test_transaction_list_source_transfer_returns_transfer_rows(self):
        """验证交易 列表 来源 转账 会返回转账记录。"""
        from_account, to_account = self._create_usd_transfer_accounts()
        create_resp = self._create_transfer(from_account=from_account, to_account=to_account, amount="40.00")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        list_resp = self.client.get(f"{self.tx_endpoint}?source=transfer")

        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        result_ids = {item["id"] for item in list_resp.data["results"]}
        self.assertEqual(result_ids, {create_resp.data["id"]})
        self.assertEqual(list_resp.data["results"][0]["transfer_account_name"], to_account.name)

    def test_delete_transfer_record_only_removes_record(self):
        """验证删除 转账 记录 只删除记录本身。"""
        from_account, to_account = self._create_usd_transfer_accounts()
        create_resp = self._create_transfer(from_account=from_account, to_account=to_account, amount="50.00")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        delete_resp = self.client.delete(f"{self.tx_delete_endpoint}?id={create_resp.data['id']}")

        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)
        from_account.refresh_from_db()
        to_account.refresh_from_db()
        self.assertEqual(from_account.balance, Decimal("450.00"))
        self.assertEqual(to_account.balance, Decimal("150.00"))
        self.assertFalse(Transaction.objects.filter(id=create_resp.data["id"]).exists())

    def test_batch_delete_by_source_removes_transfer_rows(self):
        """验证批量 删除 by 来源 会删除转账记录。"""
        from_account, to_account = self._create_usd_transfer_accounts()
        first_resp = self._create_transfer(from_account=from_account, to_account=to_account, amount="20.00")
        second_resp = self._create_transfer(from_account=from_account, to_account=to_account, amount="30.00")
        self.assertEqual(first_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_resp.status_code, status.HTTP_201_CREATED)

        delete_resp = self.client.delete(f"{self.tx_delete_endpoint}?source={Transaction.Source.TRANSFER}")

        self.assertEqual(delete_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_resp.data["source"], Transaction.Source.TRANSFER)
        self.assertEqual(delete_resp.data["deleted_count"], 2)
        self.assertEqual(Transaction.objects.filter(source=Transaction.Source.TRANSFER).count(), 0)
        from_account.refresh_from_db()
        to_account.refresh_from_db()
        self.assertEqual(from_account.balance, Decimal("450.00"))
        self.assertEqual(to_account.balance, Decimal("150.00"))

    def test_batch_delete_by_source_rejects_invalid_query_param(self):
        """验证批量 删除 by 来源 会拒绝非法查询参数。"""
        delete_resp = self.client.delete(f"{self.tx_delete_endpoint}?source=unknown")

        self.assertEqual(delete_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(delete_resp.data["message"], "source 参数无效。")

    def test_delete_transactions_rejects_missing_delete_selector(self):
        """验证删除 交易记录 会拒绝缺少删除条件的请求。"""
        delete_resp = self.client.delete(self.tx_delete_endpoint)

        self.assertEqual(delete_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(delete_resp.data["message"], "请且仅请提供 id 或 source 其中一个参数。")

    def test_delete_transactions_rejects_both_id_and_source(self):
        """验证删除 交易记录 会拒绝同时传入 id 和 来源 的请求。"""
        delete_resp = self.client.delete(f"{self.tx_delete_endpoint}?id=1&source=manual")

        self.assertEqual(delete_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(delete_resp.data["message"], "请且仅请提供 id 或 source 其中一个参数。")

    def test_delete_transaction_detail_route_is_blocked(self):
        """验证删除 交易 会阻止详情路由删除。"""
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

        delete_resp = self.client.delete(f"{self.tx_endpoint}{create_resp.data['id']}/")

        self.assertEqual(delete_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            delete_resp.data["message"],
            "请使用 DELETE /api/user/transactions/delete/?id=<交易ID> 或 ?source=<类型>。",
        )

    def test_investment_account_balance_returns_current_account_balance(self):
        """验证投资 账户 余额 返回当前账户余额。"""
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
        """验证投资 账户 详情 返回当前账户余额。"""
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
        """验证投资 账户 币种 变更 会根据实时持仓而不是快照重估。"""
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
        """验证删除 normal 账户 会归档账户并保留交易记录。"""
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

    def test_delete_investment_account_is_always_blocked(self):
        """验证删除 投资 账户 始终会被阻止。"""
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
        self.assertEqual(delete_resp.data["message"], "系统投资账户由系统维护，不能删除。")

        investment_account.refresh_from_db()
        self.assertEqual(investment_account.status, Accounts.Status.ACTIVE)

    def test_delete_investment_account_without_positions_is_blocked(self):
        """验证删除 投资 账户 在无持仓时也会被阻止。"""
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="USD",
            balance=Decimal("0.00"),
            status=Accounts.Status.ACTIVE,
        )

        delete_resp = self.client.delete(f"{self.account_endpoint}{investment_account.id}/")
        self.assertEqual(delete_resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(delete_resp.data["code"], "investment_account_delete_blocked")
        self.assertEqual(delete_resp.data["message"], "系统投资账户由系统维护，不能删除。")

        investment_account.refresh_from_db()
        self.assertEqual(investment_account.status, Accounts.Status.ACTIVE)

    def test_investment_account_currency_change_without_positions_keeps_zero_balance(self):
        """验证投资 账户 币种 变更 在无持仓时保持零余额。"""
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="CNY",
            balance=Decimal("0.00"),
            status=Accounts.Status.ACTIVE,
        )

        resp = self.client.patch(
            f"{self.account_endpoint}{investment_account.id}/",
            {"currency": "USD"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["currency"], "USD")
        self.assertEqual(resp.data["balance"], "0.00")

        investment_account.refresh_from_db()
        self.assertEqual(investment_account.status, Accounts.Status.ACTIVE)
        self.assertEqual(investment_account.currency, "USD")
        self.assertEqual(investment_account.balance, Decimal("0.00"))


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
        """验证并发 撤销 并发下只有一个请求会成功。"""
        gate = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self._reverse_once, gate) for _ in range(2)]
            statuses = sorted(f.result(timeout=10) for f in futures)

        self.assertEqual(statuses, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertEqual(Transaction.objects.count(), 2)
