from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Accounts
from market.models import Instrument
from snapshot.models import AccountSnapshot, PositionSnapshot, SnapshotDataStatus, SnapshotLevel


class SnapshotQueryApiFieldTests(APITestCase):
    account_endpoint = "/api/snapshot/accounts/"
    position_endpoint = "/api/snapshot/positions/"

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="snapshot_query_user", password="test123456")
        self.other_user = user_model.objects.create_user(username="snapshot_query_other", password="test123456")
        self.client.force_authenticate(self.user)

        self.account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="USD",
            balance=Decimal("1000.00"),
            status=Accounts.Status.ACTIVE,
        )
        self.other_account = Accounts.objects.create(
            user=self.other_user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="USD",
            balance=Decimal("500.00"),
            status=Accounts.Status.ACTIVE,
        )

        self.instrument = Instrument.objects.create(
            symbol="AAPL.US",
            short_code="AAPL",
            name="Apple Inc.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            base_currency="USD",
            is_active=True,
        )
        self.other_instrument = Instrument.objects.create(
            symbol="MSFT.US",
            short_code="MSFT",
            name="Microsoft Corp.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            base_currency="USD",
            is_active=True,
        )

        self.snapshot_time = datetime(2026, 3, 4, 10, 15, tzinfo=dt_timezone.utc)
        AccountSnapshot.objects.create(
            account=self.account,
            snapshot_time=self.snapshot_time,
            snapshot_level=SnapshotLevel.M15,
            account_currency="USD",
            balance_native=Decimal("1200.000000"),
            balance_usd=Decimal("1200.000000"),
            fx_rate_to_usd=Decimal("1.0000000000"),
            data_status=SnapshotDataStatus.OK,
        )
        PositionSnapshot.objects.create(
            account=self.account,
            instrument=self.instrument,
            snapshot_time=self.snapshot_time,
            snapshot_level=SnapshotLevel.M15,
            quantity=Decimal("5.000000"),
            avg_cost=Decimal("100.000000"),
            market_price=Decimal("120.000000"),
            market_value=Decimal("600.000000"),
            market_value_usd=Decimal("600.000000"),
            fx_rate_to_usd=Decimal("1.0000000000"),
            realized_pnl=Decimal("10.000000"),
            currency="USD",
            data_status=SnapshotDataStatus.OK,
        )

        # Other user data should never appear in current user's query results.
        AccountSnapshot.objects.create(
            account=self.other_account,
            snapshot_time=self.snapshot_time,
            snapshot_level=SnapshotLevel.M15,
            account_currency="USD",
            balance_native=Decimal("999.000000"),
            balance_usd=Decimal("999.000000"),
            fx_rate_to_usd=Decimal("1.0000000000"),
            data_status=SnapshotDataStatus.OK,
        )
        PositionSnapshot.objects.create(
            account=self.other_account,
            instrument=self.other_instrument,
            snapshot_time=self.snapshot_time,
            snapshot_level=SnapshotLevel.M15,
            quantity=Decimal("1.000000"),
            avg_cost=Decimal("1.000000"),
            market_price=Decimal("1.000000"),
            market_value=Decimal("1.000000"),
            market_value_usd=Decimal("1.000000"),
            fx_rate_to_usd=Decimal("1.0000000000"),
            realized_pnl=Decimal("0.000000"),
            currency="USD",
            data_status=SnapshotDataStatus.OK,
        )

    def test_accounts_query_returns_balance_usd_without_balance_native(self):
        params = {
            "level": SnapshotLevel.M15,
            "start_time": self.snapshot_time.isoformat(),
            "end_time": self.snapshot_time.isoformat(),
        }
        response = self.client.get(self.account_endpoint, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["series_count"], 1)

        series = response.data["series"][0]
        self.assertIn("balance_usd", series)
        self.assertNotIn("balance_native", series)
        self.assertNotIn("fx_rate_to_usd", series)
        self.assertEqual(series["balance_usd"][0], "1200")

    def test_positions_query_excludes_unneeded_fields(self):
        params = {
            "level": SnapshotLevel.M15,
            "start_time": self.snapshot_time.isoformat(),
            "end_time": self.snapshot_time.isoformat(),
        }
        response = self.client.get(self.position_endpoint, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["series_count"], 1)

        series = response.data["series"][0]
        self.assertIn("market_price", series)
        self.assertIn("market_value", series)
        self.assertNotIn("market_value_usd", series)
        self.assertNotIn("quantity", series)
        self.assertNotIn("avg_cost", series)
        self.assertNotIn("fx_rate_to_usd", series)
        self.assertNotIn("realized_pnl", series)
        self.assertEqual(series["market_value"][0], "600")
