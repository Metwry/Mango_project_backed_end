import logging
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from django.db import IntegrityError, transaction

from accounts.models import Accounts, Currency, SYSTEM_INVESTMENT_ACCOUNT_NAME
from common.normalize import strip_market_suffix
from common.utils import market_currency, quantize_decimal, to_decimal
from investment.models import Position
from market.services.pricing.cache import build_quote_index, get_market_data_payload
from market.services.pricing.fx import get_usd_base_fx_snapshot

logger = logging.getLogger(__name__)

INVESTMENT_ACCOUNT_NAME = SYSTEM_INVESTMENT_ACCOUNT_NAME
POSITION_ZERO = Decimal("0")
POSITION_PRECISION = Decimal("0.000001")
ACCOUNT_PRECISION = Decimal("0.01")


def _q_position(value: Decimal) -> Decimal:
    return quantize_decimal(value, POSITION_PRECISION)


def _q_account(value: Decimal) -> Decimal:
    return quantize_decimal(value, ACCOUNT_PRECISION)


def _position_currency(position: Position) -> str:
    instrument = position.instrument
    base_currency = instrument.base_currency
    if base_currency:
        return base_currency
    return market_currency(instrument.market, "USD")


def _position_quote_price(position: Position, quote_index: dict[tuple[str, str], dict]) -> Decimal | None:
    instrument = position.instrument
    market = instrument.market
    short_code = instrument.short_code or strip_market_suffix(instrument.symbol)
    if not market or not short_code:
        return None
    row = quote_index.get((market, short_code))
    if not isinstance(row, dict):
        return None
    price = to_decimal(row.get("price"))
    if price is None or price <= 0:
        return None
    return price


def _position_value_native(position: Position, quote_index: dict[tuple[str, str], dict]) -> tuple[Decimal, bool]:
    quantity = Decimal(str(position.quantity))
    if quantity <= 0:
        return POSITION_ZERO, False

    quote_price = _position_quote_price(position, quote_index)
    if quote_price is not None:
        return _q_position(quantity * quote_price), True

    cost_total = Decimal(str(position.cost_total))
    if cost_total > 0:
        return _q_position(cost_total), False

    avg_cost = Decimal(str(position.avg_cost))
    return _q_position(quantity * avg_cost), False


def _to_usd_or_raise(amount: Decimal, currency: str, usd_rates: dict[str, Decimal]) -> Decimal:
    ccy = currency or "USD"
    if ccy == "USD":
        return _q_position(amount)

    rate = usd_rates.get(ccy)
    if rate is None or rate <= 0:
        raise ValueError(f"缺少汇率对数据：{ccy}/USD，请先刷新汇率后重试。")
    return _q_position(amount / rate)


def _from_usd_or_raise(amount_usd: Decimal, currency: str, usd_rates: dict[str, Decimal]) -> Decimal:
    ccy = currency or "USD"
    if ccy == "USD":
        return _q_account(amount_usd)

    rate = usd_rates.get(ccy)
    if rate is None or rate <= 0:
        raise ValueError(f"缺少汇率对数据：USD/{ccy}，请先刷新汇率后重试。")
    return _q_account(amount_usd * rate)


@dataclass(frozen=True)
class InvestmentAccountValuation:
    account_currency: str
    balance_native: Decimal
    balance_usd: Decimal
    quoted_position_count: int
    cost_fallback_position_count: int


def calculate_investment_account_valuation(
    *,
    positions: list[Position],
    target_currency: str,
) -> InvestmentAccountValuation:
    account_currency = target_currency or "USD"
    fx_snapshot = get_usd_base_fx_snapshot()
    usd_rates = {
        code: Decimal(str(rate))
        for code, rate in fx_snapshot["rates"].items()
    }
    quote_index = build_quote_index(get_market_data_payload())

    total_usd = POSITION_ZERO
    quoted_count = 0
    cost_fallback_count = 0

    for position in positions:
        native_value, used_quote = _position_value_native(position, quote_index)
        if used_quote:
            quoted_count += 1
        else:
            cost_fallback_count += 1
        total_usd = _q_position(total_usd + _to_usd_or_raise(native_value, _position_currency(position), usd_rates))

    return InvestmentAccountValuation(
        account_currency=account_currency,
        balance_native=_from_usd_or_raise(total_usd, account_currency, usd_rates),
        balance_usd=_q_position(total_usd),
        quoted_position_count=quoted_count,
        cost_fallback_position_count=cost_fallback_count,
    )


def _resolve_user_id(*, user=None, user_id: int | None = None) -> int:
    resolved = user_id if user_id is not None else getattr(user, "id", None)
    if resolved is None:
        raise ValueError("user_id is required")
    return int(resolved)


def sync_investment_account_for_user(
    *,
    user=None,
    user_id: int | None = None,
    target_currency: str | None = None,
) -> Accounts | None:
    owner_id = _resolve_user_id(user=user, user_id=user_id)
    with transaction.atomic():
        account = (
            Accounts.objects
            .select_for_update()
            .filter(
                user_id=owner_id,
                type=Accounts.AccountType.INVESTMENT,
                name=INVESTMENT_ACCOUNT_NAME,
            )
            .order_by("id")
            .first()
        )

        positions = list(
            Position.objects
            .select_for_update()
            .filter(user_id=owner_id, quantity__gt=0)
            .select_related("instrument")
            .only(
                "id",
                "user_id",
                "quantity",
                "avg_cost",
                "cost_total",
                "instrument_id",
                "instrument__symbol",
                "instrument__short_code",
                "instrument__market",
                "instrument__base_currency",
            )
        )
        desired_currency = target_currency or (account.currency if account else Currency.CNY)

        if not positions:
            if account is None:
                return None

            update_fields: list[str] = []
            if account.status != Accounts.Status.ACTIVE:
                account.status = Accounts.Status.ACTIVE
                update_fields.append("status")

            if account.currency != desired_currency:
                account.currency = desired_currency
                update_fields.append("currency")

            if account.balance != POSITION_ZERO:
                account.balance = POSITION_ZERO
                update_fields.append("balance")

            if update_fields:
                account.save(update_fields=[*update_fields, "updated_at"])

            return account

        valuation = calculate_investment_account_valuation(
            positions=positions,
            target_currency=desired_currency,
        )
        if account is None:
            try:
                account = Accounts.objects.create(
                    user_id=owner_id,
                    name=INVESTMENT_ACCOUNT_NAME,
                    type=Accounts.AccountType.INVESTMENT,
                    currency=valuation.account_currency,
                    status=Accounts.Status.ACTIVE,
                    balance=valuation.balance_native,
                )
            except IntegrityError:
                account = (
                    Accounts.objects
                    .select_for_update()
                    .filter(
                        user_id=owner_id,
                        type=Accounts.AccountType.INVESTMENT,
                        name=INVESTMENT_ACCOUNT_NAME,
                    )
                    .order_by("id")
                    .first()
                )
                if account is None:
                    raise

        update_fields: list[str] = []
        if account.status != Accounts.Status.ACTIVE:
            account.status = Accounts.Status.ACTIVE
            update_fields.append("status")

        if account.currency != valuation.account_currency:
            account.currency = valuation.account_currency
            update_fields.append("currency")

        if account.balance != valuation.balance_native:
            account.balance = valuation.balance_native
            update_fields.append("balance")

        if update_fields:
            account.save(update_fields=[*update_fields, "updated_at"])

        return account


def sync_investment_accounts_for_users(*, user_ids: Iterable[int]) -> dict[str, object]:
    normalized_ids: list[int] = []
    seen: set[int] = set()
    for raw_user_id in user_ids:
        try:
            candidate = int(raw_user_id)
        except (TypeError, ValueError):
            continue
        if candidate <= 0 or candidate in seen:
            continue
        seen.add(candidate)
        normalized_ids.append(candidate)

    failed_user_ids: list[int] = []
    synced = 0
    missing = 0
    for candidate in normalized_ids:
        try:
            account = sync_investment_account_for_user(user_id=candidate)
        except Exception:
            failed_user_ids.append(candidate)
            continue
        if account is None:
            missing += 1
            continue
        synced += 1

    return {
        "requested": len(normalized_ids),
        "synced": synced,
        "missing": missing,
        "failed": len(failed_user_ids),
        "failed_user_ids": failed_user_ids,
    }


def sync_investment_accounts_after_market_refresh() -> None:
    active_position_user_ids = (
        Position.objects
        .filter(quantity__gt=0)
        .values_list("user_id", flat=True)
        .distinct()
    )
    if not active_position_user_ids:
        return

    sync_result = sync_investment_accounts_for_users(user_ids=active_position_user_ids)
    failed_user_ids = sync_result["failed_user_ids"]
    if failed_user_ids:
        logger.warning("投资账户余额同步部分失败 failed_user_ids=%s", failed_user_ids)
