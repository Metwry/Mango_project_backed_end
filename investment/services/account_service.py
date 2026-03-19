from collections.abc import Iterable
from decimal import Decimal

from django.db import IntegrityError, transaction

from accounts.models import Accounts, Currency, SYSTEM_INVESTMENT_ACCOUNT_NAME
from common.utils.code_utils import normalize_code

from ..models import Position
from .valuation_service import calculate_investment_account_valuation

INVESTMENT_ACCOUNT_NAME = SYSTEM_INVESTMENT_ACCOUNT_NAME
POSITION_ZERO = Decimal("0")

# 解析用户对象或显式 user_id，统一得到整数用户 ID。
def _resolve_user_id(*, user=None, user_id: int | None = None) -> int:
    resolved = user_id if user_id is not None else getattr(user, "id", None)
    if resolved is None:
        raise ValueError("user_id is required")
    return int(resolved)

# 同步单个用户的系统投资账户余额、币种和状态。
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
        desired_currency = normalize_code(target_currency) or (normalize_code(account.currency) if account else Currency.CNY)

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

            if (account.balance or POSITION_ZERO) != POSITION_ZERO:
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

        if (account.balance or POSITION_ZERO) != valuation.balance_native:
            account.balance = valuation.balance_native
            update_fields.append("balance")

        if update_fields:
            account.save(update_fields=[*update_fields, "updated_at"])

        return account


# 批量同步多个用户的系统投资账户，并汇总执行结果。
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

