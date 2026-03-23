from django.db import transaction as db_transaction
from rest_framework.exceptions import ValidationError

from accounts.models import Accounts, is_system_investment_account
from market.services.pricing.fx import convert_amount_or_raise
from .investment_account_sync import sync_investment_account_for_user


TRUE_VALUES = {"1", "true", "yes", "on"}

# 解析是否需要包含已归档账户的布尔开关。
def should_include_archived(raw_value) -> bool:
    return str(raw_value or "").strip().lower() in TRUE_VALUES

# 返回当前用户的账户查询集，并按需要排除已归档账户。
def get_user_accounts_queryset(*, user, include_archived: bool):
    queryset = Accounts.objects.filter(user=user).order_by("-balance")
    if not include_archived:
        queryset = queryset.exclude(status=Accounts.Status.ARCHIVED)
    return queryset

# 根据序列化器输入更新账户，并处理币种转换或投资账户同步。
def update_account_from_serializer(*, serializer):
    instance: Accounts = serializer.instance
    previous_currency = instance.currency
    next_currency = serializer.validated_data.get("currency", previous_currency)

    # 处理投资账户的数据更新
    if is_system_investment_account(account=instance):
        with db_transaction.atomic():
            if next_currency == previous_currency:
                return serializer.save()
            try:
                synced = sync_investment_account_for_user(
                    user=instance.user,
                    target_currency=next_currency,
                )
            except ValueError as exc:
                raise ValidationError({"currency": str(exc)})
            return synced

    # 处理常规账户的数据更新
    extra_save_kwargs = {}
    if next_currency != previous_currency:
        try:
            converted_balance = convert_amount_or_raise(
                amount=instance.balance,
                from_currency=previous_currency,
                to_currency=next_currency,
            )
        except ValueError as exc:
            raise ValidationError({"currency": str(exc)})
        extra_save_kwargs = {"currency": next_currency, "balance": converted_balance}

    with db_transaction.atomic():
        return serializer.save(**extra_save_kwargs)

# 将普通账户归档；系统投资账户会直接返回冲突信息。
def archive_account(*, account: Accounts, user) -> dict | None:
    if is_system_investment_account(account=account):
        return {
            "code": "investment_account_delete_blocked",
            "message": "系统投资账户由系统维护，不能删除。",
        }

    if account.status != Accounts.Status.ARCHIVED:
        account.status = Accounts.Status.ARCHIVED
        account.save(update_fields=["status", "updated_at"])

    return None

