from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from accounts.models import Accounts, Transaction
from market.models import Instrument
from market.services.quote_snapshot_service import ensure_instrument_quote
from market.subscription_service import SOURCE_POSITION, set_user_instrument_source
from shared.constants import market_currency
from shared.exceptions import BusinessConflictError
from shared.utils import quantize_decimal, trim_decimal, trim_decimal_str

from ..models import InvestmentRecord, Position
from .account_service import sync_investment_account_for_user

POSITION_PRECISION = Decimal("0.000001")
ACCOUNT_PRECISION = Decimal("0.01")
POSITION_ZERO = Decimal("0")
ConflictError = BusinessConflictError


def quantize_position(value: Decimal) -> Decimal:
    return quantize_decimal(value, POSITION_PRECISION)


def quantize_account(value: Decimal) -> Decimal:
    return quantize_decimal(value, ACCOUNT_PRECISION)


def _expected_currency_for_instrument(instrument: Instrument) -> str:
    base_currency = str(getattr(instrument, "base_currency", "") or "").strip().upper()
    if base_currency:
        return base_currency
    return market_currency(instrument.market, "")


def _safe_category_name(*, side: str, price: Decimal, quantity: Decimal) -> str:
    action = "买入" if side == InvestmentRecord.Side.BUY else "卖出"
    raw = f"以 {trim_decimal_str(price)}价格{action}:{trim_decimal_str(quantity)}"
    return raw[:24]


def _get_instrument(instrument_id: int) -> Instrument:
    instrument = (
        Instrument.objects
        .filter(id=instrument_id)
        .only("id", "symbol", "short_code", "name", "is_active", "market", "base_currency", "asset_class")
        .first()
    )
    if instrument is None:
        raise NotFound("标的不存在")
    if not instrument.is_active:
        raise ConflictError("标的不可交易")
    if instrument.asset_class == Instrument.AssetClass.INDEX:
        raise ConflictError("指数暂不支持交易")
    return instrument


def _lock_account(*, user, cash_account_id: int, instrument: Instrument) -> Accounts:
    account = (
        Accounts.objects
        .select_for_update()
        .filter(id=cash_account_id)
        .first()
    )
    if account is None:
        raise NotFound("账户不存在")
    if account.user_id != user.id:
        raise PermissionDenied("您无权使用该账户")
    if account.status != Accounts.Status.ACTIVE:
        raise ConflictError("账户未启用")

    expected_currency = _expected_currency_for_instrument(instrument)
    if expected_currency and account.currency != expected_currency:
        raise ConflictError(
            f"账户币种不匹配：该标的需使用 {expected_currency} 账户，当前账户币种为 {account.currency}"
        )
    return account


def _lock_or_create_position(*, user, instrument: Instrument, create_if_missing: bool) -> Position:
    position = (
        Position.objects
        .select_for_update()
        .filter(user=user, instrument=instrument)
        .first()
    )
    if position is not None:
        return position

    if not create_if_missing:
        raise ConflictError("持仓不足")

    try:
        Position.objects.create(user=user, instrument=instrument)
    except IntegrityError:
        pass
    return Position.objects.select_for_update().get(user=user, instrument=instrument)


def _assert_trade_amount_positive(amount: Decimal):
    if amount <= 0:
        raise ConflictError("成交金额过小，按账户精度入账后为 0.00")


def _build_response(*, record: InvestmentRecord, position: Position, tx: Transaction, realized_pnl=None):
    payload = {
        "investment_record_id": record.id,
        "position": {
            "instrument_id": position.instrument_id,
            "quantity": trim_decimal_str(position.quantity),
            "avg_cost": trim_decimal_str(position.avg_cost),
            "cost_total": trim_decimal_str(position.cost_total),
            "realized_pnl_total": trim_decimal_str(position.realized_pnl_total),
        },
        "transaction_id": tx.id,
        "balance_after": trim_decimal_str(tx.balance_after),
    }
    if realized_pnl is not None:
        payload["realized_pnl"] = trim_decimal_str(realized_pnl)
    return payload


def _warm_quote_snapshot_for_instrument(instrument: Instrument) -> None:
    try:
        ensure_instrument_quote(instrument, fetch_missing=True, use_orphan=False)
    except Exception:
        return


def _sync_investment_account_or_raise(*, user) -> None:
    try:
        sync_investment_account_for_user(user=user)
    except ValueError as exc:
        raise ConflictError(str(exc))


def execute_buy(*, user, instrument_id: int, quantity: Decimal, price: Decimal, cash_account_id: int, trade_at=None) -> dict:
    trade_at = trade_at or timezone.now()
    with transaction.atomic():
        instrument = _get_instrument(instrument_id)
        account = _lock_account(
            user=user,
            cash_account_id=cash_account_id,
            instrument=instrument,
        )
        position = _lock_or_create_position(user=user, instrument=instrument, create_if_missing=True)

        cost = quantity * price
        account_cost = quantize_account(cost)
        _assert_trade_amount_positive(account_cost)
        if account.balance < account_cost:
            raise ConflictError("余额不足")

        tx = Transaction.objects.create(
            user=user,
            account=account,
            counterparty=instrument.name,
            category_name=_safe_category_name(side=InvestmentRecord.Side.BUY, price=price, quantity=quantity),
            amount=POSITION_ZERO - account_cost,
            add_date=trade_at,
            source=Transaction.Source.INVESTMENT,
        )

        old_qty = position.quantity or POSITION_ZERO
        old_cost_total = position.cost_total or POSITION_ZERO
        new_cost_total = quantize_position(old_cost_total + cost)
        new_qty = quantize_position(old_qty + quantity)
        new_avg_cost = quantize_position(new_cost_total / new_qty) if new_qty > 0 else POSITION_ZERO

        position.quantity = new_qty
        position.cost_total = new_cost_total
        position.avg_cost = new_avg_cost
        position.save(update_fields=["quantity", "cost_total", "avg_cost", "updated_at"])
        set_user_instrument_source(
            user=user,
            instrument=instrument,
            source=SOURCE_POSITION,
            enabled=True,
        )
        _sync_investment_account_or_raise(user=user)
        if getattr(settings, "INVESTMENT_QUOTE_WARMUP_ENABLED", True):
            transaction.on_commit(lambda i=instrument: _warm_quote_snapshot_for_instrument(i))

        record = InvestmentRecord.objects.create(
            user=user,
            instrument=instrument,
            side=InvestmentRecord.Side.BUY,
            quantity=trim_decimal(quantity),
            price=trim_decimal(price),
            cash_account=account,
            cash_transaction=tx,
            trade_at=trade_at,
            realized_pnl=None,
        )

    return _build_response(record=record, position=position, tx=tx)


def execute_sell(*, user, instrument_id: int, quantity: Decimal, price: Decimal, cash_account_id: int, trade_at=None) -> dict:
    trade_at = trade_at or timezone.now()
    with transaction.atomic():
        instrument = _get_instrument(instrument_id)
        account = _lock_account(
            user=user,
            cash_account_id=cash_account_id,
            instrument=instrument,
        )
        position = _lock_or_create_position(user=user, instrument=instrument, create_if_missing=False)

        old_qty = position.quantity or POSITION_ZERO
        if old_qty < quantity:
            raise ConflictError("持仓不足")

        old_cost_total = position.cost_total or POSITION_ZERO
        sell_proceeds = quantity * price
        account_proceeds = quantize_account(sell_proceeds)
        _assert_trade_amount_positive(account_proceeds)

        cost_released = quantize_position((position.avg_cost or POSITION_ZERO) * quantity)
        realized_pnl = quantize_position(sell_proceeds - cost_released)
        old_realized_pnl_total = position.realized_pnl_total or POSITION_ZERO
        new_realized_pnl_total = quantize_position(old_realized_pnl_total + realized_pnl)

        new_qty = quantize_position(old_qty - quantity)
        if new_qty <= 0:
            new_qty = POSITION_ZERO
            new_cost_total = POSITION_ZERO
            new_avg_cost = POSITION_ZERO
        else:
            new_cost_total = quantize_position(old_cost_total - cost_released)
            if new_cost_total < 0 and abs(new_cost_total) <= POSITION_PRECISION:
                new_cost_total = POSITION_ZERO
            if new_cost_total < 0:
                raise ConflictError("持仓成本异常，无法卖出")
            new_avg_cost = quantize_position(new_cost_total / new_qty)

        tx = Transaction.objects.create(
            user=user,
            account=account,
            counterparty=instrument.name,
            category_name=_safe_category_name(side=InvestmentRecord.Side.SELL, price=price, quantity=quantity),
            amount=account_proceeds,
            add_date=trade_at,
            source=Transaction.Source.INVESTMENT,
        )

        if new_qty == POSITION_ZERO:
            position_snapshot = Position(
                user=user,
                instrument=instrument,
                quantity=POSITION_ZERO,
                avg_cost=POSITION_ZERO,
                cost_total=POSITION_ZERO,
                realized_pnl_total=new_realized_pnl_total,
            )
            position.delete()
            set_user_instrument_source(
                user=user,
                instrument=instrument,
                source=SOURCE_POSITION,
                enabled=False,
            )
        else:
            position.quantity = new_qty
            position.cost_total = new_cost_total
            position.avg_cost = new_avg_cost
            position.realized_pnl_total = new_realized_pnl_total
            position.save(update_fields=["quantity", "cost_total", "avg_cost", "realized_pnl_total", "updated_at"])
            position_snapshot = position

        _sync_investment_account_or_raise(user=user)

        record = InvestmentRecord.objects.create(
            user=user,
            instrument=instrument,
            side=InvestmentRecord.Side.SELL,
            quantity=trim_decimal(quantity),
            price=trim_decimal(price),
            cash_account=account,
            cash_transaction=tx,
            trade_at=trade_at,
            realized_pnl=trim_decimal(realized_pnl),
        )

    return _build_response(
        record=record,
        position=position_snapshot,
        tx=tx,
        realized_pnl=trim_decimal(realized_pnl),
    )


def delete_zero_position(*, user, instrument_id: int) -> dict:
    with transaction.atomic():
        position = (
            Position.objects
            .select_for_update()
            .select_related("instrument")
            .filter(user=user, instrument_id=instrument_id)
            .first()
        )
        if position is None:
            raise NotFound("持仓不存在")
        if (position.quantity or POSITION_ZERO) != POSITION_ZERO:
            raise ConflictError("仅允许删除数量为 0 的持仓")

        instrument = position.instrument
        position.delete()
        set_user_instrument_source(
            user=user,
            instrument=instrument,
            source=SOURCE_POSITION,
            enabled=False,
        )
        _sync_investment_account_or_raise(user=user)

    return {
        "deleted": True,
        "instrument_id": instrument_id,
        "stock_code": instrument.symbol,
    }
