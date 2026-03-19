from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import Accounts, is_system_investment_account
from investment.models import Position
from market.services.snapshot.fx_rate import get_fx_rates
from market.services.snapshot.quote_store import build_quote_index, get_snapshot_payload
from common.constants.market import market_currency
from common.fx.rates import normalize_usd_rates
from common.time.buckets import floor_bucket
from common.utils.code_utils import normalize_code, strip_market_suffix
from common.utils.decimal_utils import quantize_decimal, to_decimal

from snapshot.models import AccountSnapshot, PositionSnapshot, SnapshotDataStatus, SnapshotLevel

SNAPSHOT_PRECISION = Decimal("0.000001")
FX_RATE_PRECISION = Decimal("0.0000000001")
ZERO = Decimal("0")
RETENTION_DAYS = {
    SnapshotLevel.M15: 1,
    SnapshotLevel.H4: 30,
    SnapshotLevel.D1: 90,
}
AGGREGATE_SOURCE_LEVELS = {
    SnapshotLevel.H4: [SnapshotLevel.M15],
    SnapshotLevel.D1: [SnapshotLevel.H4, SnapshotLevel.M15],
    SnapshotLevel.MON1: [SnapshotLevel.D1, SnapshotLevel.H4, SnapshotLevel.M15],
}


@dataclass
class _InvestmentAggregate:
    total_usd: Decimal = ZERO
    has_quote_missing: bool = False
    has_fx_missing: bool = False

    @property
    def status(self) -> str:
        if self.has_quote_missing:
            return SnapshotDataStatus.QUOTE_MISSING
        if self.has_fx_missing:
            return SnapshotDataStatus.FX_MISSING
        return SnapshotDataStatus.OK


# 按快照金额精度量化金额字段。
def _q_amount(value: Decimal) -> Decimal:
    return quantize_decimal(value, SNAPSHOT_PRECISION)


# 按汇率精度量化汇率字段。
def _q_fx(value: Decimal) -> Decimal:
    return quantize_decimal(value, FX_RATE_PRECISION)


# 将输入时间对齐到指定快照粒度对应的时间桶。
def _align_snapshot_time(raw_dt, level: str) -> timezone.datetime:
    dt = raw_dt or timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return floor_bucket(dt, level)


# 加载美元基准汇率，并统一量化到快照精度。
def _load_usd_rates() -> tuple[dict[str, Decimal], str | None]:
    payload = get_fx_rates("USD")
    raw_rates = payload.get("rates", {}) if isinstance(payload, dict) else {}
    rates: dict[str, Decimal] = {
        code: _q_fx(value)
        for code, value in normalize_usd_rates(raw_rates).items()
    }
    rates["USD"] = Decimal("1")
    updated_at = payload.get("updated_at") if isinstance(payload, dict) else None
    return rates, updated_at


# 将指定币种金额转换为美元金额并返回所用汇率。
def _to_usd(amount: Decimal, currency: str, usd_rates: dict[str, Decimal]) -> tuple[Decimal | None, Decimal | None]:
    ccy = normalize_code(currency) or "USD"
    if ccy == "USD":
        return _q_amount(amount), Decimal("1")
    rate = usd_rates.get(ccy)
    if rate is None or rate <= 0:
        return None, None
    return _q_amount(amount / rate), rate


# 将美元金额转换回目标币种金额并返回所用汇率。
def _usd_to_native(amount_usd: Decimal, currency: str, usd_rates: dict[str, Decimal]) -> tuple[Decimal | None, Decimal | None]:
    ccy = normalize_code(currency) or "USD"
    if ccy == "USD":
        return _q_amount(amount_usd), Decimal("1")
    rate = usd_rates.get(ccy)
    if rate is None or rate <= 0:
        return None, None
    return _q_amount(amount_usd * rate), rate


# 推断持仓标的对应的计价币种。
def _position_currency(position: Position) -> str:
    instrument = position.instrument
    base_currency = normalize_code(getattr(instrument, "base_currency", ""))
    if base_currency:
        return base_currency
    return market_currency(instrument.market, "USD")


# 从行情行中提取有效价格。
def _quote_price(quote_row: dict[str, Any] | None) -> Decimal | None:
    if not isinstance(quote_row, dict):
        return None
    value = to_decimal(quote_row.get("price"))
    if value is None or value <= 0:
        return None
    return value


# 解析行情更新时间，用于写入持仓快照中的 price_time。
def _quote_time(quote_row: dict[str, Any] | None, default_ts: str | None) -> timezone.datetime | None:
    raw = None
    if isinstance(quote_row, dict):
        raw = quote_row.get("updated_at") or quote_row.get("time")
    raw = raw or default_ts
    if not raw:
        return None
    dt = parse_datetime(str(raw))
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt


# 采集当前账户与持仓快照，并写入最细粒度快照表。
def capture_snapshots(*, level: str = SnapshotLevel.M15, snapshot_time=None) -> dict[str, int | str]:
    snapshot_level = str(level or SnapshotLevel.M15)
    snapshot_at = _align_snapshot_time(snapshot_time, snapshot_level)

    usd_rates, _ = _load_usd_rates()
    payload = get_snapshot_payload()
    quote_index = build_quote_index(payload)
    quote_default_ts = payload.get("updated_at") if isinstance(payload, dict) else None

    active_accounts = list(
        Accounts.objects.filter(status=Accounts.Status.ACTIVE).only("id", "user_id", "type", "currency", "balance")
    )
    investment_accounts_by_user = {
        account.user_id: account
        for account in active_accounts
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
            "instrument__short_code",
            "instrument__symbol",
            "instrument__base_currency",
        )
    )

    investment_aggregates: dict[int, _InvestmentAggregate] = {}
    position_written = 0
    account_written = 0

    with transaction.atomic():
        for position in positions:
            investment_account = investment_accounts_by_user.get(position.user_id)
            if investment_account is None:
                continue

            market = normalize_code(position.instrument.market)
            short_code = normalize_code(position.instrument.short_code) or strip_market_suffix(position.instrument.symbol)
            quote_row = quote_index.get((market, short_code))
            price = _quote_price(quote_row)
            price_time = _quote_time(quote_row, quote_default_ts)
            currency = _position_currency(position)

            quantity = _q_amount(position.quantity or ZERO)
            avg_cost = _q_amount(position.avg_cost or ZERO)
            realized_pnl = _q_amount(position.realized_pnl_total or ZERO)

            market_value = None
            market_value_usd = None
            fx_rate_to_usd = None
            status = SnapshotDataStatus.OK

            agg = investment_aggregates.setdefault(investment_account.id, _InvestmentAggregate())
            if price is None:
                status = SnapshotDataStatus.QUOTE_MISSING
                agg.has_quote_missing = True
            else:
                market_value = _q_amount(quantity * price)
                converted_usd, fx_rate = _to_usd(market_value, currency, usd_rates)
                if converted_usd is None:
                    status = SnapshotDataStatus.FX_MISSING
                    agg.has_fx_missing = True
                else:
                    market_value_usd = converted_usd
                    fx_rate_to_usd = _q_fx(fx_rate)
                    agg.total_usd = _q_amount(agg.total_usd + market_value_usd)

            PositionSnapshot.objects.update_or_create(
                account=investment_account,
                instrument=position.instrument,
                snapshot_level=snapshot_level,
                snapshot_time=snapshot_at,
                defaults={
                    "quantity": quantity,
                    "avg_cost": avg_cost,
                    "market_price": _q_amount(price) if price is not None else None,
                    "market_value": market_value,
                    "market_value_usd": market_value_usd,
                    "fx_rate_to_usd": fx_rate_to_usd,
                    "realized_pnl": realized_pnl,
                    "price_time": price_time,
                    "currency": currency,
                    "data_status": status,
                },
            )
            position_written += 1

        for account in active_accounts:
            account_currency = normalize_code(account.currency) or "USD"

            if is_system_investment_account(account=account):
                agg = investment_aggregates.get(account.id, _InvestmentAggregate())
                balance_usd = _q_amount(agg.total_usd)
                native_value, fx_rate = _usd_to_native(balance_usd, account_currency, usd_rates)
                status = agg.status

                if native_value is None:
                    native_value = _q_amount(account.balance or ZERO)
                    if status == SnapshotDataStatus.OK:
                        status = SnapshotDataStatus.FX_MISSING

                AccountSnapshot.objects.update_or_create(
                    account=account,
                    snapshot_level=snapshot_level,
                    snapshot_time=snapshot_at,
                    defaults={
                        "account_currency": account_currency,
                        "balance_native": native_value,
                        "balance_usd": balance_usd,
                        "fx_rate_to_usd": _q_fx(fx_rate) if fx_rate is not None else None,
                        "data_status": status,
                    },
                )
                account_written += 1
                continue

            native_balance = _q_amount(account.balance or ZERO)
            converted_usd, fx_rate = _to_usd(native_balance, account_currency, usd_rates)
            status = SnapshotDataStatus.OK
            balance_usd = converted_usd
            if balance_usd is None:
                balance_usd = ZERO
                status = SnapshotDataStatus.FX_MISSING

            AccountSnapshot.objects.update_or_create(
                account=account,
                snapshot_level=snapshot_level,
                snapshot_time=snapshot_at,
                defaults={
                    "account_currency": account_currency,
                    "balance_native": native_balance,
                    "balance_usd": _q_amount(balance_usd),
                    "fx_rate_to_usd": _q_fx(fx_rate) if fx_rate is not None else None,
                    "data_status": status,
                },
            )
            account_written += 1

    return {
        "snapshot_level": snapshot_level,
        "snapshot_time": snapshot_at.isoformat(),
        "account_snapshot_written": account_written,
        "position_snapshot_written": position_written,
    }


# 清理超过保留期的细粒度快照数据。
def cleanup_expired_snapshots(*, now_dt=None) -> dict[str, int]:
    now_value = now_dt or timezone.now()
    account_deleted = 0
    position_deleted = 0

    for level, days in RETENTION_DAYS.items():
        cutoff = now_value - timedelta(days=days)
        account_deleted += AccountSnapshot.objects.filter(snapshot_level=level, snapshot_time__lt=cutoff).delete()[0]
        position_deleted += PositionSnapshot.objects.filter(snapshot_level=level, snapshot_time__lt=cutoff).delete()[0]

    return {
        "account_deleted": account_deleted,
        "position_deleted": position_deleted,
    }


# 计算聚合快照所对应的源数据窗口起点。
def _aggregation_window_start(snapshot_at: timezone.datetime, level: str) -> timezone.datetime:
    if level == SnapshotLevel.H4:
        return snapshot_at - timedelta(hours=4)
    if level == SnapshotLevel.D1:
        return snapshot_at - timedelta(days=1)
    if level == SnapshotLevel.MON1:
        prev_month_end = snapshot_at - timedelta(days=1)
        return prev_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"unsupported aggregate level: {level}")


# 查询指定时间窗口内每个账户最新的一条账户快照。
def _latest_account_rows(source_level: str, window_start: timezone.datetime, window_end: timezone.datetime):
    return list(
        AccountSnapshot.objects
        .filter(
            snapshot_level=source_level,
            snapshot_time__gt=window_start,
            snapshot_time__lte=window_end,
        )
        .select_related("account")
        .order_by("account_id", "-snapshot_time", "-id")
        .distinct("account_id")
    )


# 查询指定时间窗口内每个账户持仓的最新一条持仓快照。
def _latest_position_rows(source_level: str, window_start: timezone.datetime, window_end: timezone.datetime):
    return list(
        PositionSnapshot.objects
        .filter(
            snapshot_level=source_level,
            snapshot_time__gt=window_start,
            snapshot_time__lte=window_end,
        )
        .select_related("account", "instrument")
        .order_by("account_id", "instrument_id", "-snapshot_time", "-id")
        .distinct("account_id", "instrument_id")
    )


# 将细粒度快照聚合为更粗粒度快照，或在 M15 时直接执行采集。
def aggregate_snapshots(*, level: str, snapshot_time=None) -> dict[str, int | str]:
    target_level = str(level or "")
    if target_level == SnapshotLevel.M15:
        return capture_snapshots(level=SnapshotLevel.M15, snapshot_time=snapshot_time)
    if target_level not in AGGREGATE_SOURCE_LEVELS:
        raise ValueError(f"unsupported aggregate level: {target_level}")

    snapshot_at = _align_snapshot_time(snapshot_time, target_level)
    window_start = _aggregation_window_start(snapshot_at, target_level)

    source_level = None
    account_rows = []
    position_rows = []
    for candidate_source in AGGREGATE_SOURCE_LEVELS[target_level]:
        source_account_rows = _latest_account_rows(candidate_source, window_start, snapshot_at)
        source_position_rows = _latest_position_rows(candidate_source, window_start, snapshot_at)
        if source_account_rows or source_position_rows:
            source_level = candidate_source
            account_rows = source_account_rows
            position_rows = source_position_rows
            break

    if source_level is None:
        return {
            "snapshot_level": target_level,
            "source_level": "none",
            "snapshot_time": snapshot_at.isoformat(),
            "account_snapshot_written": 0,
            "position_snapshot_written": 0,
        }

    account_written = 0
    position_written = 0
    with transaction.atomic():
        for source in account_rows:
            AccountSnapshot.objects.update_or_create(
                account=source.account,
                snapshot_level=target_level,
                snapshot_time=snapshot_at,
                defaults={
                    "account_currency": source.account_currency,
                    "balance_native": source.balance_native,
                    "balance_usd": source.balance_usd,
                    "fx_rate_to_usd": source.fx_rate_to_usd,
                    "data_status": source.data_status,
                },
            )
            account_written += 1

        for source in position_rows:
            PositionSnapshot.objects.update_or_create(
                account=source.account,
                instrument=source.instrument,
                snapshot_level=target_level,
                snapshot_time=snapshot_at,
                defaults={
                    "quantity": source.quantity,
                    "avg_cost": source.avg_cost,
                    "market_price": source.market_price,
                    "market_value": source.market_value,
                    "market_value_usd": source.market_value_usd,
                    "fx_rate_to_usd": source.fx_rate_to_usd,
                    "realized_pnl": source.realized_pnl,
                    "price_time": source.price_time,
                    "currency": source.currency,
                    "data_status": source.data_status,
                },
            )
            position_written += 1

    return {
        "snapshot_level": target_level,
        "source_level": str(source_level),
        "snapshot_time": snapshot_at.isoformat(),
        "account_snapshot_written": account_written,
        "position_snapshot_written": position_written,
    }

