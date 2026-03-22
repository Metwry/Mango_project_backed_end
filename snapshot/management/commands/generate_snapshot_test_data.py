from __future__ import annotations

import json
import random
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Accounts, is_system_investment_account
from investment.models import Position
from market.services.data.rates import get_fx_rates
from common.utils import floor_bucket, market_currency
from snapshot.models import AccountSnapshot, PositionSnapshot, SnapshotDataStatus, SnapshotLevel
from snapshot.services.snapshot_service import cleanup_expired_snapshots

PREC = Decimal("0.000001")
FX_PREC = Decimal("0.0000000001")
ZERO = Decimal("0")
VOL_BY_LEVEL = {
    SnapshotLevel.M15: 0.015,
    SnapshotLevel.H4: 0.03,
    SnapshotLevel.D1: 0.05,
    SnapshotLevel.MON1: 0.08,
}


def q_amount(value: Decimal) -> Decimal:
    return value.quantize(PREC)


def q_fx(value: Decimal) -> Decimal:
    return value.quantize(FX_PREC)


def floor_ts(dt, level: str):
    return floor_bucket(dt, level)


def iter_times(start_dt, end_dt, level: str):
    if level == SnapshotLevel.MON1:
        current = floor_ts(start_dt, SnapshotLevel.MON1)
        if current < start_dt:
            month = current.month + 1
            year = current.year
            if month == 13:
                month = 1
                year += 1
            current = current.replace(year=year, month=month, day=1)
        while current <= end_dt:
            yield current
            month = current.month + 1
            year = current.year
            if month == 13:
                month = 1
                year += 1
            current = current.replace(year=year, month=month, day=1)
        return

    step = {
        SnapshotLevel.M15: timedelta(minutes=15),
        SnapshotLevel.H4: timedelta(hours=4),
        SnapshotLevel.D1: timedelta(days=1),
    }[level]
    current = floor_ts(start_dt, level)
    if current < start_dt:
        current += step
    while current <= end_dt:
        yield current
        current += step


def chunked(rows, size=2000):
    for i in range(0, len(rows), size):
        yield rows[i: i + size]


def to_usd(amount: Decimal, ccy: str, rates: dict[str, Decimal]):
    code = str(ccy or "USD").strip().upper() or "USD"
    if code == "USD":
        return q_amount(amount), Decimal("1")
    rate = rates.get(code)
    if rate is None or rate <= 0:
        return None, None
    return q_amount(amount / rate), q_fx(rate)


def from_usd(amount_usd: Decimal, ccy: str, rates: dict[str, Decimal]):
    code = str(ccy or "USD").strip().upper() or "USD"
    if code == "USD":
        return q_amount(amount_usd), Decimal("1")
    rate = rates.get(code)
    if rate is None or rate <= 0:
        return None, None
    return q_amount(amount_usd * rate), q_fx(rate)


def expected_position_ccy(position: Position) -> str:
    base = str(position.instrument.base_currency or "").strip().upper()
    if base:
        return base
    return market_currency(position.instrument.market, "USD")


class Command(BaseCommand):
    help = "Generate random snapshot test data based on current accounts/positions and keep rows by cleanup policy."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=60, help="history days to generate, default 60")
        parser.add_argument("--seed", type=int, default=20260304, help="random seed")
        parser.add_argument(
            "--wipe-all",
            action="store_true",
            help="delete all snapshot rows before generation",
        )

    def handle(self, *args, **options):
        days = max(1, int(options["days"]))
        seed = int(options["seed"])
        wipe_all = bool(options.get("wipe_all"))
        random.seed(seed)

        end_ts = timezone.now().astimezone(dt_timezone.utc).replace(second=0, microsecond=0)
        start_ts = end_ts - timedelta(days=days)

        rates = {"USD": Decimal("1")}
        try:
            payload = get_fx_rates("USD")
            raw_rates = payload.get("rates", {}) if isinstance(payload, dict) else {}
            if isinstance(raw_rates, dict):
                for code, raw in raw_rates.items():
                    c = str(code or "").strip().upper()
                    try:
                        value = Decimal(str(raw))
                    except Exception:
                        continue
                    if c and value > 0:
                        rates[c] = q_fx(value)
        except Exception:
            pass

        fallback_rates = {
            "CNY": Decimal("7.0"),
            "HKD": Decimal("7.8"),
            "JPY": Decimal("150"),
            "EUR": Decimal("0.92"),
        }
        for code, value in fallback_rates.items():
            rates.setdefault(code, value)

        accounts = list(
            Accounts.objects
            .filter(status=Accounts.Status.ACTIVE)
            .only("id", "user_id", "type", "currency", "balance", "name")
        )
        investment_account_by_user = {
            account.user_id: account
            for account in accounts
            if is_system_investment_account(account=account)
        }

        positions = list(
            Position.objects
            .filter(quantity__gt=0)
            .select_related("instrument")
            .only(
                "id",
                "user_id",
                "instrument_id",
                "quantity",
                "avg_cost",
                "realized_pnl_total",
                "instrument__market",
                "instrument__base_currency",
            )
        )
        positions_by_user: dict[int, list[Position]] = {}
        for position in positions:
            positions_by_user.setdefault(position.user_id, []).append(position)

        # 默认仅重置目标窗口，--wipe-all 时清空全部快照
        levels = [SnapshotLevel.M15, SnapshotLevel.H4, SnapshotLevel.D1, SnapshotLevel.MON1]
        if wipe_all:
            AccountSnapshot.objects.all().delete()
            PositionSnapshot.objects.all().delete()
        else:
            AccountSnapshot.objects.filter(
                snapshot_time__gte=start_ts,
                snapshot_time__lte=end_ts,
                snapshot_level__in=levels,
            ).delete()
            PositionSnapshot.objects.filter(
                snapshot_time__gte=start_ts,
                snapshot_time__lte=end_ts,
                snapshot_level__in=levels,
            ).delete()

        non_inv_balance_state: dict[int, Decimal] = {}
        for account in accounts:
            balance = Decimal(str(account.balance or 0))
            non_inv_balance_state[account.id] = q_amount(balance if balance >= 0 else ZERO)

        position_price_state: dict[int, Decimal] = {}
        for position in positions:
            avg_cost = Decimal(str(position.avg_cost or 0))
            if avg_cost <= 0:
                avg_cost = Decimal(str(random.uniform(8, 180)))
            position_price_state[position.id] = q_amount(avg_cost)

        inserted = {
            "account": {level: 0 for level in levels},
            "position": {level: 0 for level in levels},
        }

        for level in levels:
            volatility = VOL_BY_LEVEL[level]
            account_rows = []
            position_rows = []

            for ts in iter_times(start_ts, end_ts, level):
                inv_total_usd: dict[int, Decimal] = {}
                inv_status: dict[int, str] = {}

                # 先生成投资持仓，再汇总投资账户
                for user_id, inv_account in investment_account_by_user.items():
                    total_usd = ZERO
                    status = SnapshotDataStatus.OK
                    for position in positions_by_user.get(user_id, []):
                        prev_price = position_price_state[position.id]
                        factor = Decimal(str(1 + random.uniform(-volatility, volatility)))
                        price = q_amount(prev_price * factor)
                        if price <= 0:
                            price = Decimal("0.000001")
                        position_price_state[position.id] = price

                        quantity = q_amount(Decimal(str(position.quantity or 0)))
                        avg_cost = q_amount(Decimal(str(position.avg_cost or 0)))
                        realized_pnl = q_amount(Decimal(str(position.realized_pnl_total or 0)))
                        market_value = q_amount(quantity * price)
                        ccy = expected_position_ccy(position)

                        market_value_usd, fx_rate = to_usd(market_value, ccy, rates)
                        row_status = SnapshotDataStatus.OK
                        if market_value_usd is None:
                            row_status = SnapshotDataStatus.FX_MISSING
                            status = SnapshotDataStatus.FX_MISSING
                        else:
                            total_usd = q_amount(total_usd + market_value_usd)

                        position_rows.append(
                            PositionSnapshot(
                                account_id=inv_account.id,
                                instrument_id=position.instrument_id,
                                snapshot_time=ts,
                                snapshot_level=level,
                                quantity=quantity,
                                avg_cost=avg_cost,
                                market_price=price,
                                market_value=market_value,
                                market_value_usd=market_value_usd,
                                fx_rate_to_usd=fx_rate,
                                realized_pnl=realized_pnl,
                                currency=ccy,
                                data_status=row_status,
                            )
                        )

                    inv_total_usd[inv_account.id] = total_usd
                    inv_status[inv_account.id] = status

                # 全账户快照
                for account in accounts:
                    ccy = str(account.currency or "USD").strip().upper() or "USD"

                    if is_system_investment_account(account=account):
                        total_usd = inv_total_usd.get(account.id, ZERO)
                        native, fx_rate = from_usd(total_usd, ccy, rates)
                        status = inv_status.get(account.id, SnapshotDataStatus.OK)
                        if native is None:
                            native = q_amount(Decimal(str(account.balance or 0)))
                            fx_rate = None
                            status = SnapshotDataStatus.FX_MISSING

                        account_rows.append(
                            AccountSnapshot(
                                account_id=account.id,
                                snapshot_time=ts,
                                snapshot_level=level,
                                account_currency=ccy,
                                balance_native=native,
                                balance_usd=total_usd,
                                fx_rate_to_usd=fx_rate,
                                data_status=status,
                            )
                        )
                        continue

                    prev_balance = non_inv_balance_state.get(account.id, q_amount(Decimal(str(account.balance or 0))))
                    factor = Decimal(str(1 + random.uniform(-volatility, volatility)))
                    next_balance = q_amount(prev_balance * factor)
                    if next_balance < 0:
                        next_balance = ZERO
                    non_inv_balance_state[account.id] = next_balance

                    balance_usd, fx_rate = to_usd(next_balance, ccy, rates)
                    status = SnapshotDataStatus.OK
                    if balance_usd is None:
                        balance_usd = ZERO
                        status = SnapshotDataStatus.FX_MISSING

                    account_rows.append(
                        AccountSnapshot(
                            account_id=account.id,
                            snapshot_time=ts,
                            snapshot_level=level,
                            account_currency=ccy,
                            balance_native=next_balance,
                            balance_usd=balance_usd,
                            fx_rate_to_usd=fx_rate,
                            data_status=status,
                        )
                    )

            for batch in chunked(account_rows, size=2000):
                AccountSnapshot.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    unique_fields=["account", "snapshot_level", "snapshot_time"],
                    update_fields=["account_currency", "balance_native", "balance_usd", "fx_rate_to_usd", "data_status"],
                )

            for batch in chunked(position_rows, size=2000):
                PositionSnapshot.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    unique_fields=["account", "instrument", "snapshot_level", "snapshot_time"],
                    update_fields=[
                        "quantity",
                        "avg_cost",
                        "market_price",
                        "market_value",
                        "market_value_usd",
                        "fx_rate_to_usd",
                        "realized_pnl",
                        "currency",
                        "data_status",
                    ],
                )

            inserted["account"][level] = len(account_rows)
            inserted["position"][level] = len(position_rows)

        cleanup_result = cleanup_expired_snapshots(now_dt=end_ts)
        kept_count = {
            "account": {level: AccountSnapshot.objects.filter(snapshot_level=level).count() for level in levels},
            "position": {level: PositionSnapshot.objects.filter(snapshot_level=level).count() for level in levels},
        }

        summary = {
            "seed": seed,
            "wipe_all": wipe_all,
            "window": {"start": start_ts.isoformat(), "end": end_ts.isoformat()},
            "generated_count": {
                "account": {str(level): inserted["account"][level] for level in levels},
                "position": {str(level): inserted["position"][level] for level in levels},
            },
            "cleanup_deleted": cleanup_result,
            "kept_count": {
                "account": {str(level): kept_count["account"][level] for level in levels},
                "position": {str(level): kept_count["position"][level] for level in levels},
            },
        }
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))

