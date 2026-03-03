from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import close_old_connections
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import Accounts, Transaction
from accounts.services.quote_fetcher import _to_billion_amount
from market.services.cache_keys import USD_EXCHANGE_RATES_KEY


class QuoteFetcherUnitTests(SimpleTestCase):
    def test_to_billion_amount_rounds_to_two_decimals(self):
        self.assertEqual(_to_billion_amount(123456789), 1.23)
        self.assertEqual(_to_billion_amount(100000000), 1.0)
        self.assertIsNone(_to_billion_amount(0))


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
        self.assertIn("currency", resp.data)
        self.account.refresh_from_db()
        self.assertEqual(self.account.currency, "CNY")
        self.assertEqual(self.account.balance, Decimal("1000.00"))


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
