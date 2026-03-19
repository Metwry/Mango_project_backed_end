from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import Accounts, Transaction
from investment.models import InvestmentRecord, Position
from investment.services.account_service import INVESTMENT_ACCOUNT_NAME
from market.models import Instrument, UserInstrumentSubscription
from market.services.snapshot.cache_keys import USD_EXCHANGE_RATES_KEY, WATCHLIST_QUOTES_KEY


def _seed_usd_rates():
    cache.set(
        USD_EXCHANGE_RATES_KEY,
        {
            "base": "USD",
            "updated_at": "2026-03-02T00:00:00+08:00",
            "rates": {
                "USD": 1.0,
                "CNY": 7.0,
                "JPY": 140.0,
                "EUR": 0.9,
            },
        },
        timeout=None,
    )


def _seed_quotes(quotes_by_market: dict):
    cache.set(
        WATCHLIST_QUOTES_KEY,
        {
            "updated_at": "2026-03-02T00:00:00+08:00",
            "updated_markets": sorted(quotes_by_market.keys()),
            "stale_markets": [],
            "data": quotes_by_market,
        },
        timeout=None,
    )


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "investment-basic-tests",
        }
    },
    INVESTMENT_QUOTE_WARMUP_ENABLED=False,
)
class InvestmentBasicApiTests(APITestCase):
    buy_endpoint = "/api/investment/buy/"
    sell_endpoint = "/api/investment/sell/"
    positions_endpoint = "/api/investment/positions/"
    history_endpoint = "/api/investment/history/"
    tx_endpoint = "/api/user/transactions/"

    def setUp(self):
        cache.clear()
        _seed_usd_rates()
        _seed_quotes({})

        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="invest_basic_user", password="test123456")
        self.client.force_authenticate(self.user)

        self.us_instrument = Instrument.objects.create(
            symbol="MSFT.US",
            short_code="MSFT",
            name="Microsoft Corp.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            base_currency="USD",
            is_active=True,
        )
        self.usd_account = Accounts.objects.create(
            user=self.user,
            name="USD Broker",
            type=Accounts.AccountType.BROKER,
            currency="USD",
            balance=Decimal("10000.00"),
            status=Accounts.Status.ACTIVE,
        )

    def test_buy_success_and_position_list_fields(self):
        """验证买入 成功买入并返回持仓列表字段。"""
        buy_resp = self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "3.000000",
                "price": "99.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        self.assertEqual(buy_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(buy_resp.data["position"]["instrument_id"], self.us_instrument.id)

        list_resp = self.client.get(self.positions_endpoint)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            list_resp.data[0],
            {
                "instrument_id": self.us_instrument.id,
                "short_code": "MSFT",
                "name": "Microsoft Corp.",
                "market_type": "US",
                "current_cost_price": "99",
                "current_quantity": "3",
                "current_value": "297",
            },
        )

    def test_buy_revalues_investment_account_using_cost_when_quote_missing(self):
        """验证买入 revalues 投资 账户 在缺少行情时按成本重估。"""
        buy_resp = self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "2.000000",
                "price": "10.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        self.assertEqual(buy_resp.status_code, status.HTTP_201_CREATED)

        investment_account = Accounts.objects.get(
            user=self.user,
            type=Accounts.AccountType.INVESTMENT,
            name=INVESTMENT_ACCOUNT_NAME,
        )
        self.assertEqual(investment_account.currency, "CNY")
        self.assertEqual(investment_account.balance, Decimal("140.00"))

    def test_buy_rejects_index_instrument(self):
        """验证买入 会拒绝指数标的。"""
        index_instrument = Instrument.objects.create(
            symbol="SPX.US",
            short_code="SPX",
            name="S&P500",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.INDEX,
            base_currency="USD",
            is_active=True,
        )

        resp = self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": index_instrument.id,
                "quantity": "1.000000",
                "price": "5000.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("指数暂不支持交易", str(resp.data))

    def test_sell_all_deletes_position_and_keeps_investment_account_active(self):
        """验证卖出 全部 会删除持仓并保持投资账户处于激活状态。"""
        self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "2.000000",
                "price": "10.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        sell_resp = self.client.post(
            self.sell_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "2.000000",
                "price": "11.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        self.assertEqual(sell_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(sell_resp.data["position"]["quantity"], "0")
        self.assertFalse(Position.objects.filter(user=self.user, instrument=self.us_instrument).exists())
        investment_account = Accounts.objects.get(
            user=self.user,
            type=Accounts.AccountType.INVESTMENT,
            name=INVESTMENT_ACCOUNT_NAME,
        )
        self.assertEqual(investment_account.status, Accounts.Status.ACTIVE)
        self.assertEqual(investment_account.balance, Decimal("0.00"))

    def test_buy_after_full_sell_reuses_same_investment_account(self):
        """验证买入 after full 卖出 会复用同一个投资账户。"""
        first_buy_resp = self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "2.000000",
                "price": "10.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        self.assertEqual(first_buy_resp.status_code, status.HTTP_201_CREATED)
        investment_account = Accounts.objects.get(
            user=self.user,
            type=Accounts.AccountType.INVESTMENT,
            name=INVESTMENT_ACCOUNT_NAME,
        )
        original_account_id = investment_account.id

        sell_resp = self.client.post(
            self.sell_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "2.000000",
                "price": "11.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        self.assertEqual(sell_resp.status_code, status.HTTP_201_CREATED)
        investment_account.refresh_from_db()
        self.assertEqual(investment_account.status, Accounts.Status.ACTIVE)
        self.assertEqual(investment_account.balance, Decimal("0.00"))

        second_buy_resp = self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "1.000000",
                "price": "9.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        self.assertEqual(second_buy_resp.status_code, status.HTTP_201_CREATED)

        reactivated = Accounts.objects.get(
            user=self.user,
            type=Accounts.AccountType.INVESTMENT,
            name=INVESTMENT_ACCOUNT_NAME,
        )
        self.assertEqual(reactivated.id, original_account_id)
        self.assertEqual(reactivated.status, Accounts.Status.ACTIVE)

    def test_cannot_reverse_investment_generated_cash_transaction(self):
        """验证cannot 撤销 投资 generated 现金 交易。"""
        buy_resp = self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "1.000000",
                "price": "10.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        self.assertEqual(buy_resp.status_code, status.HTTP_201_CREATED)
        tx_id = buy_resp.data["transaction_id"]

        reverse_resp = self.client.post(f"{self.tx_endpoint}{tx_id}/reverse/", {}, format="json")
        self.assertEqual(reverse_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("不允许撤销", str(reverse_resp.data))

        self.usd_account.refresh_from_db()
        self.assertEqual(self.usd_account.balance, Decimal("9990.00"))
        self.assertEqual(Transaction.objects.filter(account=self.usd_account).count(), 1)

    def test_history_query_returns_read_only_investment_records(self):
        """验证历史 查询 返回只读的投资记录。"""
        buy_resp = self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "2.000000",
                "price": "10.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        self.assertEqual(buy_resp.status_code, status.HTTP_201_CREATED)
        sell_resp = self.client.post(
            self.sell_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "1.000000",
                "price": "11.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        self.assertEqual(sell_resp.status_code, status.HTTP_201_CREATED)

        history_resp = self.client.get(self.history_endpoint, {"limit": 20, "offset": 0})
        self.assertEqual(history_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(history_resp.data["count"], 2)
        self.assertEqual(len(history_resp.data["items"]), 2)

        first = history_resp.data["items"][0]
        self.assertIn("cash_transaction_id", first)
        self.assertIn("cash_flow_amount", first)
        self.assertIn("instrument_symbol", first)
        self.assertIn("cash_account_name", first)

        delete_resp = self.client.delete(self.history_endpoint)
        self.assertEqual(delete_resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "investment-complex-tests",
        }
    },
    INVESTMENT_QUOTE_WARMUP_ENABLED=False,
)
class InvestmentComplexApiTests(APITestCase):
    buy_endpoint = "/api/investment/buy/"

    def setUp(self):
        cache.clear()
        _seed_usd_rates()
        _seed_quotes({})

        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="invest_complex_user", password="test123456")
        self.client.force_authenticate(self.user)

        self.us_instrument = Instrument.objects.create(
            symbol="AAPL.US",
            short_code="AAPL",
            name="Apple Inc.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            base_currency="USD",
            is_active=True,
        )
        self.cn_instrument = Instrument.objects.create(
            symbol="000001.CN",
            short_code="000001",
            name="Ping An Bank",
            market=Instrument.Market.CN,
            asset_class=Instrument.AssetClass.STOCK,
            base_currency="CNY",
            is_active=True,
        )
        self.usd_account = Accounts.objects.create(
            user=self.user,
            name="Complex USD",
            type=Accounts.AccountType.BROKER,
            currency="USD",
            balance=Decimal("10000.00"),
            status=Accounts.Status.ACTIVE,
        )
        self.cny_account = Accounts.objects.create(
            user=self.user,
            name="Complex CNY",
            type=Accounts.AccountType.BROKER,
            currency="CNY",
            balance=Decimal("10000.00"),
            status=Accounts.Status.ACTIVE,
        )

    def test_currency_change_revalues_investment_account(self):
        """验证币种 变更 revalues 投资 账户。"""
        self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "2.000000",
                "price": "10.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        _seed_quotes({"US": [{"short_code": "AAPL", "name": "Apple Inc.", "price": 12.0}]})
        self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.cn_instrument.id,
                "quantity": "1.000000",
                "price": "100.000000",
                "cash_account_id": self.cny_account.id,
            },
            format="json",
        )

        account = Accounts.objects.get(
            user=self.user,
            type=Accounts.AccountType.INVESTMENT,
            name=INVESTMENT_ACCOUNT_NAME,
        )
        self.assertEqual(account.balance, Decimal("268.00"))
        patch_resp = self.client.patch(f"/api/user/accounts/{account.id}/", {"currency": "USD"}, format="json")
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("38.29"))

    def test_investment_account_only_currency_is_editable(self):
        """验证投资 账户 只允许修改币种。"""
        self.client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.us_instrument.id,
                "quantity": "1.000000",
                "price": "10.000000",
                "cash_account_id": self.usd_account.id,
            },
            format="json",
        )
        account = Accounts.objects.get(
            user=self.user,
            type=Accounts.AccountType.INVESTMENT,
            name=INVESTMENT_ACCOUNT_NAME,
        )
        patch_resp = self.client.patch(
            f"/api/user/accounts/{account.id}/",
            {"name": "手动改名", "balance": "99999.99"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", patch_resp.data)
        self.assertIn("balance", patch_resp.data)


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "investment-concurrency-tests",
        }
    },
    INVESTMENT_QUOTE_WARMUP_ENABLED=False,
)
class InvestmentConcurrencyApiTests(TransactionTestCase):
    buy_endpoint = "/api/investment/buy/"
    sell_endpoint = "/api/investment/sell/"

    def setUp(self):
        cache.clear()
        _seed_usd_rates()
        _seed_quotes({})

        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="invest_concurrency_user", password="test123456")
        self.instrument = Instrument.objects.create(
            symbol="TSLA.US",
            short_code="TSLA",
            name="Tesla Inc.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            base_currency="USD",
            is_active=True,
        )
        self.cash_account = Accounts.objects.create(
            user=self.user,
            name="Concurrent USD",
            type=Accounts.AccountType.BROKER,
            currency="USD",
            balance=Decimal("10000.00"),
            status=Accounts.Status.ACTIVE,
        )

    def _buy_once(self, gate: Barrier) -> int:
        close_old_connections()
        client = APIClient()
        client.force_authenticate(self.user)
        gate.wait(timeout=5)
        resp = client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.instrument.id,
                "quantity": "1.000000",
                "price": "10.000000",
                "cash_account_id": self.cash_account.id,
            },
            format="json",
        )
        close_old_connections()
        return resp.status_code

    def _sell_once(self, gate: Barrier) -> int:
        close_old_connections()
        client = APIClient()
        client.force_authenticate(self.user)
        gate.wait(timeout=5)
        resp = client.post(
            self.sell_endpoint,
            {
                "instrument_id": self.instrument.id,
                "quantity": "2.000000",
                "price": "10.000000",
                "cash_account_id": self.cash_account.id,
            },
            format="json",
        )
        close_old_connections()
        return resp.status_code

    def test_concurrent_first_buy_only_one_investment_account(self):
        """验证并发 首次 买入 仅 一个 投资 账户。"""
        gate = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self._buy_once, gate) for _ in range(2)]
            statuses = sorted(f.result(timeout=10) for f in futures)

        self.assertEqual(statuses, [status.HTTP_201_CREATED, status.HTTP_201_CREATED])
        self.assertEqual(
            Accounts.objects.filter(
                user=self.user,
                type=Accounts.AccountType.INVESTMENT,
                name=INVESTMENT_ACCOUNT_NAME,
            ).count(),
            1,
        )

    def test_concurrent_sell_last_position_keeps_state_consistent(self):
        """验证并发 卖出 last 持仓 会保持状态一致。"""
        client = APIClient()
        client.force_authenticate(self.user)
        buy_resp = client.post(
            self.buy_endpoint,
            {
                "instrument_id": self.instrument.id,
                "quantity": "2.000000",
                "price": "10.000000",
                "cash_account_id": self.cash_account.id,
            },
            format="json",
        )
        self.assertEqual(buy_resp.status_code, status.HTTP_201_CREATED)

        gate = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self._sell_once, gate) for _ in range(2)]
            statuses = sorted(f.result(timeout=10) for f in futures)

        self.assertEqual(statuses, [status.HTTP_201_CREATED, status.HTTP_409_CONFLICT])
        self.assertFalse(Position.objects.filter(user=self.user, instrument=self.instrument).exists())
        investment_account = Accounts.objects.get(
            user=self.user,
            type=Accounts.AccountType.INVESTMENT,
            name=INVESTMENT_ACCOUNT_NAME,
        )
        self.assertEqual(investment_account.status, Accounts.Status.ACTIVE)
        self.assertEqual(investment_account.balance, Decimal("0.00"))
        self.assertEqual(InvestmentRecord.objects.filter(side=InvestmentRecord.Side.SELL).count(), 1)
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertFalse(UserInstrumentSubscription.objects.filter(user=self.user, instrument=self.instrument).exists())
