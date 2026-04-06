from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Accounts
from market.models import Instrument
from snapshot.models import AccountSnapshot, PositionSnapshot, SnapshotDataStatus, SnapshotLevel
from snapshot.services.query_service import get_account_trend, get_position_trend


class PositionTrendServiceTests(TestCase):

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="trend_user", password="test123456")
        self.account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency="USD",
            balance=Decimal("1000.00"),
            status=Accounts.Status.ACTIVE,
        )
        self.instrument = Instrument.objects.create(
            symbol="BTC.CRYPTO",
            short_code="BTC",
            name="Bitcoin",
            market=Instrument.Market.CRYPTO,
            asset_class=Instrument.AssetClass.CRYPTO,
            base_currency="USD",
            is_active=True,
        )

        base_time = datetime(2026, 3, 1, 0, 0, tzinfo=dt_timezone.utc)
        snapshots = [
            ("2026-03-01", Decimal("1.000000"), Decimal("100.000000"), Decimal("100.000000")),
            ("2026-03-02", Decimal("1.000000"), Decimal("120.000000"), Decimal("120.000000")),
            ("2026-03-03", Decimal("1.000000"), Decimal("90.000000"), Decimal("90.000000")),
        ]
        for idx, (_, quantity, market_price, market_value_usd) in enumerate(snapshots):
            PositionSnapshot.objects.create(
                account=self.account,
                instrument=self.instrument,
                snapshot_time=base_time + timedelta(days=idx),
                snapshot_level=SnapshotLevel.D1,
                quantity=quantity,
                avg_cost=Decimal("80.000000"),
                market_price=market_price,
                market_value=market_value_usd,
                market_value_usd=market_value_usd,
                fx_rate_to_usd=Decimal("1.0000000000"),
                realized_pnl=Decimal("0"),
                currency="USD",
                data_status=SnapshotDataStatus.OK,
            )

    def test_get_position_trend_returns_series_and_summary(self):
        result = get_position_trend(
            user=self.user,
            start="2026-03-01",
            end="2026-03-03",
            symbols=["BTC"],
            fields=["quantity", "market_price", "market_value"],
        )

        self.assertEqual(result["base_currency"], "USD")
        self.assertEqual(result["analysis_period"]["start"], "2026-03-01")
        self.assertEqual(result["analysis_period"]["end"], "2026-03-03")
        self.assertEqual(len(result["items"]), 1)

        item = result["items"][0]
        self.assertEqual(item["symbol"], "BTC")
        self.assertIn("quantity", item["series"])
        self.assertIn("market_price", item["series"])
        self.assertIn("market_value_usd", item["series"])
        self.assertEqual(item["summary"]["max_market_value_usd"], "120.00")
        self.assertEqual(item["summary"]["min_market_value_usd"], "90.00")
        self.assertEqual(item["summary"]["max_market_value_at"], "2026-03-02")
        self.assertEqual(item["max_drawdown"]["start"], "2026-03-02")
        self.assertEqual(item["max_drawdown"]["end"], "2026-03-03")
        self.assertEqual(item["max_single_period_gain"]["start"], "2026-03-01")
        self.assertEqual(item["max_single_period_gain"]["end"], "2026-03-02")

    def test_get_position_trend_returns_empty_items_for_unknown_symbol(self):
        result = get_position_trend(
            user=self.user,
            start="2026-03-01",
            end="2026-03-03",
            symbols=["ETH"],
            fields=["market_value"],
        )

        self.assertEqual(result["items"], [])

    def test_get_account_trend_returns_series_and_summary(self):
        trend_account = Accounts.objects.create(
            user=self.user,
            name="USD Broker",
            type=Accounts.AccountType.BROKER,
            currency="USD",
            balance=Decimal("1100.00"),
            status=Accounts.Status.ACTIVE,
        )
        AccountSnapshot.objects.create(
            account=trend_account,
            snapshot_time=timezone.make_aware(datetime(2026, 3, 1)),
            snapshot_level=SnapshotLevel.D1,
            account_currency="USD",
            balance_native=Decimal("1000.00"),
            balance_usd=Decimal("1000.00"),
            fx_rate_to_usd=Decimal("1.0000000000"),
            data_status=SnapshotDataStatus.OK,
        )
        AccountSnapshot.objects.create(
            account=trend_account,
            snapshot_time=timezone.make_aware(datetime(2026, 3, 2)),
            snapshot_level=SnapshotLevel.D1,
            account_currency="USD",
            balance_native=Decimal("1100.00"),
            balance_usd=Decimal("1100.00"),
            fx_rate_to_usd=Decimal("1.0000000000"),
            data_status=SnapshotDataStatus.OK,
        )

        result = get_account_trend(
            user=self.user,
            start="2026-03-01",
            end="2026-03-02",
        )

        self.assertEqual(result["base_currency"], "USD")
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["account_id"], str(trend_account.id))
        self.assertEqual(item["series"]["balance_usd"][0]["value"], "1000")
        self.assertEqual(item["summary"]["start_balance_usd"], "1000.00")
        self.assertEqual(item["summary"]["end_balance_usd"], "1100.00")

    def test_get_account_trend_returns_empty_items_for_unknown_account(self):
        result = get_account_trend(
            user=self.user,
            account_ids=[999999],
        )

        self.assertEqual(result["items"], [])
