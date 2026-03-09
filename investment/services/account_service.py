from decimal import Decimal

from django.db import IntegrityError, transaction

from accounts.models import Accounts, Currency
from shared.utils import normalize_code

from ..models import Position

INVESTMENT_ACCOUNT_NAME = "投资账户"
POSITION_ZERO = Decimal("0")


def _archive_account(account: Accounts) -> None:
    if account.status == Accounts.Status.ARCHIVED:
        return
    account.status = Accounts.Status.ARCHIVED
    account.save(update_fields=["status", "updated_at"])


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

        has_positions = Position.objects.filter(user=user, quantity__gt=0).exists()
        if not has_positions:
            if account is not None:
                _archive_account(account)
            return None

        desired_currency = normalize_code(target_currency) or (normalize_code(account.currency) if account else Currency.CNY)
        if account is None:
            try:
                account = Accounts.objects.create(
                    user=user,
                    name=INVESTMENT_ACCOUNT_NAME,
                    type=Accounts.AccountType.INVESTMENT,
                    currency=desired_currency,
                    status=Accounts.Status.ACTIVE,
                    balance=POSITION_ZERO,
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

        if account.currency != desired_currency:
            account.currency = desired_currency
            update_fields.append("currency")

        if update_fields:
            account.save(update_fields=[*update_fields, "updated_at"])

        return account
