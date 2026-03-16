from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

SYSTEM_INVESTMENT_ACCOUNT_NAME = "投资账户"

# 判断给定账户或账户类型/名称组合是否为系统自动维护的投资账户。
def is_system_investment_account(*, account=None, account_type=None, account_name=None) -> bool:
    if account is not None:
        account_type = getattr(account, "type", account_type)
        account_name = getattr(account, "name", account_name)
    return (
        account_type == Accounts.AccountType.INVESTMENT
        and str(account_name or "").strip() == SYSTEM_INVESTMENT_ACCOUNT_NAME
    )


class Currency(models.TextChoices):
    """系统内统一使用的账户/交易币种枚举。"""

    CNY = "CNY", "人民币"
    USD = "USD", "美元"
    JPY = "JPY", "日元"
    EUR = "EUR", "欧元"
    HKD = "HKD","港币"


class Accounts(models.Model):
    """
    用户账户模型。

    用途：
    - 记录用户的现金、银行卡、证券、加密货币以及系统投资账户。
    - 作为交易流水、转账记录、投资买卖现金账户和快照数据的上游主表。

    约束说明：
    - `unique_together(user, name, type, currency)`：同一用户下，账户名称 + 类型 + 币种组合必须唯一。
    - `uniq_user_investment_named_account`：同一用户只能存在一个名称固定为“投资账户”的投资账户。
    - `ordering = ['-updated_at']`：默认按最近更新时间倒序返回，方便前端优先展示活跃账户。
    """

    class AccountType(models.TextChoices):
        """账户类型枚举，用于区分不同资金容器。"""

        CASH = "cash", "现金"
        BANK = "bank", "银行卡"
        BROKER = "broker", "证券"
        CRYPTO = "crypto", "加密货币"
        INVESTMENT = "investment", "投资账户"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        """账户状态枚举，控制账户是否可继续参与业务。"""

        ACTIVE = "active", "启用"
        ARCHIVED = "archived", "归档"
        DISABLED = "disabled", "禁用"

    # 账户归属用户。
    # 外键到认证用户表，用户删除时级联删除其全部账户；
    # `related_name="accounts"` 便于从用户反向访问账户列表；
    # 建立索引以加速按用户查询账户。
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="accounts",
        db_index=True,
    )

    # 账户名称，最大 24 个字符。
    # 与 `user + type + currency` 共同组成业务唯一标识。
    name = models.CharField(max_length=24)
    # 账户类型，取值应来自 `AccountType` 枚举。
    type = models.CharField(max_length=16)
    # 账户币种，受 `Currency.choices` 约束，默认人民币。
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.CNY)

    # 当前账户余额。
    # 采用两位小数，适用于现金类账户展示；投资账户余额由系统同步维护。
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # 账户状态，决定账户是否可继续被选择或参与业务操作。
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    # 创建时间，只在插入时写入一次。
    created_at = models.DateTimeField(auto_now_add=True)
    # 更新时间，每次保存自动刷新，用于排序和最近变更追踪。
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # 数据库物理表名。
        db_table = "accounts"
        # 默认按最近更新时间倒序返回。
        ordering = ["-updated_at"]
        # 限制同一用户下，账户名 + 类型 + 币种不能重复。
        unique_together = [("user", "name","type", "currency")]
        # 额外的条件唯一约束：每个用户只能有一个系统投资账户。
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(type="investment", name=SYSTEM_INVESTMENT_ACCOUNT_NAME),
                name="uniq_user_investment_named_account",
            ),
        ]

    # 返回便于日志和调试定位的账户标识字符串。
    def __str__(self) -> str:
        return f"{self.user_id}-{self.name}({self.currency})"


class Transaction(models.Model):
    """
    账户交易流水模型。

    用途：
    - 记录手工记账、投资买卖现金流水、账户转账记录和撤销冲正流水。
    - 通过 `save()` 中的原子逻辑同步更新账户余额，并落地余额快照值 `balance_after`。

    约束与行为说明：
    - `account` 与 `transfer_account` 使用 `PROTECT`，防止存在流水的账户被误删。
    - `source` 建立索引，便于按手工/投资/转账/冲正分类查询。
    - 索引 `["user", "account", "-created_at", "-id"]` 用于优化按用户、账户和时间倒序查询。
    - `reversal_of` 是自关联一对一字段，表示“本流水是对哪一条原流水的冲正”。
    - 创建后禁止修改数据，避免账务失真。
    """

    class Source(models.TextChoices):
        """流水来源枚举，用于区分业务来源。"""

        MANUAL = "manual", "手工记账"
        INVESTMENT = "investment", "投资交易"
        TRANSFER = "transfer", "账户转账"
        REVERSAL = "reversal", "冲正流水"

    # 交易对手方或业务对象名称，如商户名、股票名、转入账户名等。
    counterparty = models.CharField(max_length=32)
    # 本次流水金额。
    # 正数代表资金流入，负数代表资金流出。
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # 执行完本次流水后的账户余额。
    # 由模型 `save()` 自动计算，外部不应手工维护。
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # 交易分类名称，用于账单列表展示。
    category_name = models.CharField(max_length=24)
    # 备注信息，长度限制较短，通常用于标记转入/转出/撤销等补充说明。
    remark = models.CharField(max_length=16, blank=True, default="")
    # 流水币种。
    # 创建时会被强制同步为所属账户币种，确保账务币种一致。
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.CNY)

    # 业务发生时间，支持外部指定；用于按业务时间排序和筛选。
    add_date = models.DateTimeField(default=timezone.now)
    # 数据创建时间，记录落库时刻。
    created_at = models.DateTimeField(auto_now_add=True)

    # 所属账户。
    # 使用 `PROTECT` 保证流水存在时账户不可删除。
    account = models.ForeignKey(
        Accounts,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    # 转账场景下的转入账户；普通手工记账、投资流水和冲正流水均为空。
    transfer_account = models.ForeignKey(
        Accounts,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="incoming_transfer_transactions",
    )

    # 所属用户。
    # 与账户用户保持一致，并建立索引提升按用户查询流水性能。
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="transactions",
        db_index=True,
    )
    # 流水来源，决定后续删除、撤销、筛选等业务规则。
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.MANUAL,
        db_index=True,
    )

    # 若当前记录是冲正流水，则 `reversal_of` 指向被撤销的原始流水。
    # 一对一约束意味着一条原流水最多只能被冲正一次。
    reversal_of = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversal_tx",
    )
    # 原始流水被撤销的时间戳。
    # 仅原始流水会写入该值，冲正流水本身一般为空。
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # 数据库物理表名。
        db_table = "accounts_transaction"
        # 默认按创建时间和主键倒序，保证最新流水优先展示。
        ordering = ["-created_at", "-id"]
        # 优化按用户、账户维度拉取最近流水的查询。
        indexes = [
            models.Index(fields=["user", "account", "-created_at", "-id"]),
        ]

    # 返回便于日志打印的流水摘要字符串。
    def __str__(self) -> str:
        return f"{self.user_id}-{self.account_id}:{self.counterparty}-{self.currency}:{self.amount}"
