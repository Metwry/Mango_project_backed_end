from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from accounts.models import Accounts, Currency
from investment.models import Position
from market.models import Instrument, UserInstrumentSubscription
from market.services.data.market_refresh import pull_data
from market.services.quote_cache import USD_EXCHANGE_RATES_KEY, WATCHLIST_QUOTES_KEY
from market.services.data.watchlist_snapshot import pull_market
from market.services.market_schedule import GuardDecision
from snapshot.models import AccountSnapshot, PositionSnapshot, SnapshotDataStatus, SnapshotLevel
from snapshot.services.snapshot_service import capture_snapshots


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "market-snapshot-integration-tests",
        }
    }
)
class MarketSnapshotIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="market_snap_user", password="test123456")
        self.instrument = Instrument.objects.create(
            symbol="AAPL.US",
            short_code="AAPL",
            name="Apple Inc.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            base_currency="USD",
            is_active=True,
        )

    @patch("market.services.data.watchlist_snapshot.pull_watchlist_quotes")
    @patch("market.services.data.watchlist_snapshot.resolve_due_markets")
    def test_sync_watchlist_snapshot_revalues_investment_account_balance(
        self,
        mock_resolve_due,
        mock_pull_quotes,
    ):
        """验证sync watchlist snapshot 会重估投资账户余额。"""
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency=Currency.USD,
            status=Accounts.Status.ACTIVE,
            balance=Decimal("0"),
        )
        Position.objects.create(
            user=self.user,
            instrument=self.instrument,
            quantity=Decimal("2"),
            avg_cost=Decimal("90"),
            cost_total=Decimal("180"),
            realized_pnl_total=Decimal("0"),
        )
        UserInstrumentSubscription.objects.create(
            user=self.user,
            instrument=self.instrument,
            from_position=True,
            from_watchlist=False,
        )
        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {
                "base": "USD",
                "updated_at": "2026-03-04T00:00:00+00:00",
                "rates": {"USD": 1.0, "CNY": 7.0},
            },
            timeout=None,
        )

        mock_resolve_due.return_value = (
            {"US"},
            {"US": GuardDecision(market="US", should_pull=True, reason="due", session="regular")},
        )
        mock_pull_quotes.return_value = {
            "US": [
                {
                    "short_code": "AAPL",
                    "name": "Apple Inc.",
                    "price": 100.0,
                    "prev_close": 99.0,
                    "day_high": 101.0,
                    "day_low": 98.0,
                    "pct": 1.0,
                    "volume": 1.23,
                }
            ]
        }

        pull_data()

        investment_account.refresh_from_db()
        self.assertEqual(investment_account.balance, Decimal("200.00"))

    @patch("market.services.data.watchlist_snapshot.pull_watchlist_quotes")
    @patch("market.services.data.watchlist_snapshot.resolve_due_markets")
    def test_sync_then_capture_m15_writes_position_and_account_snapshots(
        self,
        mock_resolve_due,
        mock_pull_quotes,
    ):
        """验证sync then capture m15 会写入持仓和账户快照。"""
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency=Currency.USD,
            status=Accounts.Status.ACTIVE,
            balance=Decimal("0"),
        )
        Position.objects.create(
            user=self.user,
            instrument=self.instrument,
            quantity=Decimal("2"),
            avg_cost=Decimal("90"),
            cost_total=Decimal("180"),
            realized_pnl_total=Decimal("0"),
        )
        UserInstrumentSubscription.objects.create(
            user=self.user,
            instrument=self.instrument,
            from_position=True,
            from_watchlist=False,
        )

        mock_resolve_due.return_value = (
            {"US"},
            {"US": GuardDecision(market="US", should_pull=True, reason="due", session="regular")},
        )
        mock_pull_quotes.return_value = {
            "US": [
                {
                    "short_code": "AAPL",
                    "name": "Apple Inc.",
                    "price": 100.0,
                    "prev_close": 99.0,
                    "day_high": 101.0,
                    "day_low": 98.0,
                    "pct": 1.0,
                    "volume": 1.23,
                }
            ]
        }
        pull_market()

        # Avoid fx service fallback network call inside capture_snapshots.
        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {
                "base": "USD",
                "updated_at": "2026-03-04T00:00:00+00:00",
                "rates": {"USD": 1.0, "CNY": 7.0},
            },
            timeout=None,
        )
        result = capture_snapshots(level=SnapshotLevel.M15)

        self.assertEqual(result["position_snapshot_written"], 1)
        self.assertEqual(result["account_snapshot_written"], 1)

        pos = PositionSnapshot.objects.get(account=investment_account, instrument=self.instrument, snapshot_level=SnapshotLevel.M15)
        acc = AccountSnapshot.objects.get(account=investment_account, snapshot_level=SnapshotLevel.M15)

        self.assertEqual(pos.data_status, SnapshotDataStatus.OK)
        self.assertEqual(pos.market_price, Decimal("100.000000"))
        self.assertEqual(pos.market_value, Decimal("200.000000"))
        self.assertEqual(pos.market_value_usd, Decimal("200.000000"))
        self.assertEqual(pos.fx_rate_to_usd, Decimal("1.0000000000"))

        self.assertEqual(acc.data_status, SnapshotDataStatus.OK)
        self.assertEqual(acc.balance_native, Decimal("200.000000"))
        self.assertEqual(acc.balance_usd, Decimal("200.000000"))
        self.assertEqual(acc.fx_rate_to_usd, Decimal("1.0000000000"))

    def test_capture_marks_quote_missing_for_investment_position_without_price(self):
        """验证capture 会将无价格的投资持仓标记为缺少行情。"""
        investment_account = Accounts.objects.create(
            user=self.user,
            name="投资账户",
            type=Accounts.AccountType.INVESTMENT,
            currency=Currency.USD,
            status=Accounts.Status.ACTIVE,
            balance=Decimal("0"),
        )
        Position.objects.create(
            user=self.user,
            instrument=self.instrument,
            quantity=Decimal("3"),
            avg_cost=Decimal("120"),
            cost_total=Decimal("360"),
            realized_pnl_total=Decimal("0"),
        )
        cache.set(
            WATCHLIST_QUOTES_KEY,
            {
                "updated_at": "2026-03-04T00:00:00+00:00",
                "updated_markets": [],
                "stale_markets": ["US"],
                "data": {"US": []},
            },
            timeout=None,
        )
        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {
                "base": "USD",
                "updated_at": "2026-03-04T00:00:00+00:00",
                "rates": {"USD": 1.0, "CNY": 7.0},
            },
            timeout=None,
        )

        result = capture_snapshots(level=SnapshotLevel.M15)
        self.assertEqual(result["position_snapshot_written"], 1)
        self.assertEqual(result["account_snapshot_written"], 1)

        pos = PositionSnapshot.objects.get(account=investment_account, instrument=self.instrument, snapshot_level=SnapshotLevel.M15)
        acc = AccountSnapshot.objects.get(account=investment_account, snapshot_level=SnapshotLevel.M15)

        self.assertEqual(pos.data_status, SnapshotDataStatus.QUOTE_MISSING)
        self.assertIsNone(pos.market_price)
        self.assertIsNone(pos.market_value)
        self.assertIsNone(pos.market_value_usd)

        self.assertEqual(acc.data_status, SnapshotDataStatus.QUOTE_MISSING)
        self.assertEqual(acc.balance_usd, Decimal("0.000000"))

    def test_capture_converts_cash_account_balance_to_usd(self):
        """验证capture 会将现金账户余额转换为 USD。"""
        cash_account = Accounts.objects.create(
            user=self.user,
            name="招商银行",
            type=Accounts.AccountType.BANK,
            currency=Currency.CNY,
            status=Accounts.Status.ACTIVE,
            balance=Decimal("700.00"),
        )
        cache.set(
            WATCHLIST_QUOTES_KEY,
            {
                "updated_at": "2026-03-04T00:00:00+00:00",
                "updated_markets": [],
                "stale_markets": [],
                "data": {},
            },
            timeout=None,
        )
        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {
                "base": "USD",
                "updated_at": "2026-03-04T00:00:00+00:00",
                "rates": {"USD": 1.0, "CNY": 7.0},
            },
            timeout=None,
        )

        result = capture_snapshots(level=SnapshotLevel.M15)
        self.assertEqual(result["account_snapshot_written"], 1)

        acc = AccountSnapshot.objects.get(account=cash_account, snapshot_level=SnapshotLevel.M15)
        self.assertEqual(acc.data_status, SnapshotDataStatus.OK)
        self.assertEqual(acc.balance_native, Decimal("700.000000"))
        self.assertEqual(acc.balance_usd, Decimal("100.000000"))
        self.assertEqual(acc.fx_rate_to_usd, Decimal("7.0000000000"))
