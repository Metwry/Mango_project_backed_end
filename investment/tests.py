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
from investment.services import INVESTMENT_ACCOUNT_NAME
from market.models import Instrument, UserInstrumentSubscription
from market.services.cache_keys import USD_EXCHANGE_RATES_KEY, WATCHLIST_QUOTES_KEY


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

    def test_sell_all_deletes_position_and_investment_account(self):
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
        self.assertFalse(
            Accounts.objects.filter(
                user=self.user,
                type=Accounts.AccountType.INVESTMENT,
                name=INVESTMENT_ACCOUNT_NAME,
            ).exists()
        )


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
        self.assertFalse(
            Accounts.objects.filter(
                user=self.user,
                type=Accounts.AccountType.INVESTMENT,
                name=INVESTMENT_ACCOUNT_NAME,
            ).exists()
        )
        self.assertEqual(InvestmentRecord.objects.filter(side=InvestmentRecord.Side.SELL).count(), 1)
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertFalse(UserInstrumentSubscription.objects.filter(user=self.user, instrument=self.instrument).exists())
