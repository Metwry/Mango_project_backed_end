from decimal import Decimal

from django.db import IntegrityError, transaction

from accounts.models import Accounts, Currency
from shared.utils import normalize_code

from ..models import Position
from .valuation_service import calculate_investment_account_valuation

INVESTMENT_ACCOUNT_NAME = "投资账户"
POSITION_ZERO = Decimal("0")


def _archive_account(account: Accounts) -> None:
    update_fields: list[str] = []
    if account.status != Accounts.Status.ARCHIVED:
        account.status = Accounts.Status.ARCHIVED
        update_fields.append("status")
    if (account.balance or POSITION_ZERO) != POSITION_ZERO:
        account.balance = POSITION_ZERO
        update_fields.append("balance")
    if not update_fields:
        return
    account.save(update_fields=[*update_fields, "updated_at"])


def sync_investment_account_for_user(*, user, target_currency: str | None = None) -> Accounts | None:
    with transaction.atomic():
        account_qs = (
            Accounts.objects
            .select_for_update()
            .filter(
                user=user,
                type=Accounts.AccountType.INVESTMENT,
                name=INVESTMENT_ACCOUNT_NAME,
            )
            .order_by("id")
        )
        accounts = list(account_qs)
        account = None
        for candidate in accounts:
            if candidate.status != Accounts.Status.ARCHIVED:
                account = candidate
                break
        if account is None and accounts:
            account = accounts[0]

        for duplicate in accounts:
            if account is None or duplicate.id == account.id:
                continue
            _archive_account(duplicate)

        positions = list(
            Position.objects
            .select_for_update()
            .filter(user=user, quantity__gt=0)
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
        if not positions:
            if account is not None:
                _archive_account(account)
            return None

        desired_currency = normalize_code(target_currency) or (normalize_code(account.currency) if account else Currency.CNY)
        valuation = calculate_investment_account_valuation(
            positions=positions,
            target_currency=desired_currency,
        )
        if account is None:
            try:
                account = Accounts.objects.create(
                    user=user,
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
                        user=user,
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
