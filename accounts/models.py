from decimal import Decimal

from django.conf import settings
from django.db import models, transaction as db_transaction
from django.db.models import Q
from django.utils import timezone


class Currency(models.TextChoices):
    CNY = "CNY", "人民币"
    USD = "USD", "美元"
    JPY = "JPY", "日元"
    EUR = "EUR", "欧元"
    HKD = "HKD","港币"


class Accounts(models.Model):
    class AccountType(models.TextChoices):
        CASH = "cash", "现金"
        BANK = "bank", "银行卡"
        BROKER = "broker", "证券"
        CRYPTO = "crypto", "加密货币"
        INVESTMENT = "investment", "投资账户"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        ARCHIVED = "archived", "归档"
        DISABLED = "disabled", "禁用"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="accounts",
        db_index=True,
    )

    name = models.CharField(max_length=24)
    type = models.CharField(max_length=16)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.CNY)

    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts"
        ordering = ["-updated_at"]
        unique_together = [("user", "name", "currency")]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(type="investment", name="投资账户"),
                name="uniq_user_investment_named_account",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}-{self.name}({self.currency})"


class Transaction(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "手工记账"
        INVESTMENT = "investment", "投资交易"
        TRANSFER = "transfer", "账户转账"
        REVERSAL = "reversal", "冲正流水"

    counterparty = models.CharField(max_length=32)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    category_name = models.CharField(max_length=24)
    remark = models.CharField(max_length=16, blank=True, default="")
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.CNY)

    add_date = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    account = models.ForeignKey(
        Accounts,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="transactions",
        db_index=True,
    )
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.MANUAL,
        db_index=True,
    )

    # ====== 撤销相关字段（新增） ======
    # 这条交易是否是某条交易的撤销（若是撤销交易，reversal_of 指向原交易）
    reversal_of = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversal_tx",
    )
    # 原交易被撤销的时间（只有“原交易”会有这个值）
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_transaction"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "account", "-created_at", "-id"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}-{self.account_id}:{self.counterparty}-{self.currency}:{self.amount}"

    def save(self, *args, **kwargs):
        if not self.account_id:
            raise ValueError("Transaction.account 不能为空")

        with db_transaction.atomic():
            # 锁账户行，保证并发安全（余额 + 快照）
            account = Accounts.objects.select_for_update().get(pk=self.account_id)

            # ===== 更新：禁止改 account/amount/add_date/reversal_of =====
            if self.pk:
                old = Transaction.objects.only(
                    "account_id", "amount", "add_date", "reversal_of_id", "source"
                ).get(pk=self.pk)

                if old.account_id != self.account_id:
                    raise ValueError("交易创建后不能修改 account")
                if old.amount != self.amount:
                    raise ValueError("交易创建后不能修改 amount")
                if old.add_date != self.add_date:
                    raise ValueError("交易创建后不能修改 add_date")
                if old.reversal_of_id != self.reversal_of_id:
                    raise ValueError("交易创建后不能修改 reversal_of")
                if old.source != self.source:
                    raise ValueError("交易创建后不能修改 source")

                # 注意：更新不改余额、不改 balance_after
                return super().save(*args, **kwargs)

            # ===== 创建交易 =====
            # 撤销交易也必须属于同一账户/同一用户
            self.user = account.user
            self.currency = account.currency

            amt = self.amount or Decimal("0")
            account.balance = (account.balance or Decimal("0")) + amt
            account.save(update_fields=["balance", "updated_at"])

            self.balance_after = account.balance
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("不允许删除交易记录。请使用撤销功能。")


class Transfer(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "成功"
        REVERSED = "reversed", "已撤销"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="transfers",
        db_index=True,
    )
    from_account = models.ForeignKey(
        Accounts,
        on_delete=models.PROTECT,
        related_name="outgoing_transfers",
    )
    to_account = models.ForeignKey(
        Accounts,
        on_delete=models.PROTECT,
        related_name="incoming_transfers",
    )
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.CNY)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    note = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUCCESS, db_index=True)
    out_transaction = models.OneToOneField(
        "accounts.Transaction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="transfer_outbound",
    )
    in_transaction = models.OneToOneField(
        "accounts.Transaction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="transfer_inbound",
    )
    reversed_out_transaction = models.OneToOneField(
        "accounts.Transaction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="transfer_reversed_outbound",
    )
    reversed_in_transaction = models.OneToOneField(
        "accounts.Transaction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="transfer_reversed_inbound",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_transfer"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "-created_at", "-id"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(from_account=models.F("to_account")),
                name="transfer_from_to_account_not_equal",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.from_account_id}->{self.to_account_id} {self.currency} {self.amount}"
