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
from investment.models import Position
from market.models import Instrument
from accounts.services.quote_fetcher import _to_billion_amount
from market.services.cache_keys import USD_EXCHANGE_RATES_KEY
from snapshot.models import AccountSnapshot, SnapshotDataStatus, SnapshotLevel


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
        self.assertEqual(self.account.balance, Decimal("1000.00"))
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
        self.assertEqual(self.account.balance, Decimal("1000.00"))

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
        self.assertIn("message", resp.data)
        self.assertIn("currency", resp.data)
        self.account.refresh_from_db()
        self.assertEqual(self.account.currency, "CNY")
        self.assertEqual(self.account.balance, Decimal("1000.00"))

    def test_investment_account_balance_prefers_latest_snapshot(self):
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="USD",
            balance=Decimal("9999.99"),
            status=Accounts.Status.ACTIVE,
        )
        AccountSnapshot.objects.create(
            account=investment_account,
            snapshot_level=SnapshotLevel.M15,
            snapshot_time="2026-03-04T00:00:00Z",
            account_currency="USD",
            balance_native=Decimal("1234.56"),
            balance_usd=Decimal("1234.56"),
            data_status=SnapshotDataStatus.OK,
        )

        resp = self.client.get(self.account_endpoint)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        target = next(item for item in resp.data if item["id"] == investment_account.id)
        self.assertEqual(target["balance"], "1234.560000")

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
