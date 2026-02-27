from decimal import Decimal
from django.conf import settings
from django.db import models, transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Currency(models.TextChoices):
    CNY = "CNY", "人民币"
    USD = "USD", "美元"
    JPY = "JPY", "日元"
    EUR = "EUR", "欧元"


class Accounts(models.Model):
    class AccountType(models.TextChoices):
        CASH = "cash", "现金"
        BANK = "bank", "银行卡"
        BROKER = "broker", "证券"
        CRYPTO = "crypto", "加密货币"
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

    def __str__(self) -> str:
        return f"{self.user_id}-{self.name}({self.currency})"


class Transaction(models.Model):
    counterparty = models.CharField(max_length=32)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    category_name = models.CharField(max_length=24)
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
                    "account_id", "amount", "add_date", "reversal_of_id"
                ).get(pk=self.pk)

                if old.account_id != self.account_id:
                    raise ValueError("交易创建后不能修改 account")
                if old.amount != self.amount:
                    raise ValueError("交易创建后不能修改 amount")
                if old.add_date != self.add_date:
                    raise ValueError("交易创建后不能修改 add_date")
                if old.reversal_of_id != self.reversal_of_id:
                    raise ValueError("交易创建后不能修改 reversal_of")

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


class Instrument(models.Model):
    """
    统一的交易品种基础表 (Master Symbol Table)
    包含了美股、A股、港股、加密货币和外汇
    """

    # 1. 定义枚举类型，规范数据输入
    class AssetClass(models.TextChoices):
        STOCK = 'STOCK', _('股票 (Stock)')
        CRYPTO = 'CRYPTO', _('加密货币 (Crypto)')
        FOREX = 'FOREX', _('外汇 (Forex)')

    class Market(models.TextChoices):
        US = 'US', _('美股 (United States)')
        CN = 'CN', _('A股 (China)')
        HK = 'HK', _('港股 (Hong Kong)')
        CRYPTO = 'CRYPTO', _('加密货币市场 (Crypto)')
        FX = 'FX', _('外汇市场 (Forex)')

    # 2. 核心搜索与标识字段
    # symbol 是全局唯一的标准代码，例如: AAPL.US, 0700.HK, BTC.CRYPTO
    symbol = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="标准代码"
    )

    # short_code 用于纯代码搜索，可能重复 (如平安银行 000001 和 长和 00001)
    short_code = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="原始代码"
    )

    # name 用于中文或英文名称的模糊搜索
    name = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name="品种名称"
    )

    # 3. 分类与属性字段
    asset_class = models.CharField(
        max_length=20,
        choices=AssetClass.choices,
        default=AssetClass.STOCK,
        verbose_name="资产大类"
    )

    market = models.CharField(
        max_length=20,
        choices=Market.choices,
        default=Market.US,
        verbose_name="所属市场"
    )

    exchange = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="交易所"
    )

    base_currency = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        verbose_name="计价货币"
    )

    # 4. 状态字段
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否可交易",
        help_text="用于标记退市股票或下架品种"
    )

    # 记录数据的创建和更新时间，方便日后维护
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "交易品种"
        verbose_name_plural = "交易品种列表"
        # 默认按资产类别和代码排序
        ordering = ['asset_class', 'symbol']
        # 建立联合索引，进一步提升在名称和代码上同时搜索的速度
        indexes = [
            models.Index(fields=['short_code', 'name']),
        ]

    def __str__(self):
        return f"{self.symbol} - {self.name}"


class WatchlistItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_index=True)
    instrument = models.ForeignKey("accounts.Instrument", on_delete=models.CASCADE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "instrument"], name="uniq_user_instrument_watch")
        ]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["instrument"]),
        ]