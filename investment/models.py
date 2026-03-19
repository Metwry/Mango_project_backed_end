from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from common.db.constraints import check_constraint


class InvestmentRecord(models.Model):
    """
    投资买卖记录模型。

    用途：
    - 记录用户对某个交易标的的买入/卖出操作。
    - 与 `accounts.Transaction` 一对一关联，描述该笔交易对应的现金流。
    - 作为投资历史查询、盈亏计算和持仓变更的审计依据。

    约束说明：
    - `quantity > 0`、`price > 0`：禁止零值或负值成交。
    - `BUY` 时 `realized_pnl` 必须为 `NULL`，因为买入不会产生已实现盈亏。
    - `SELL` 时 `realized_pnl` 必须非空，用于保存卖出已实现盈亏。
    - 用户一致性、资金账户一致性等跨表约束无法通过数据库 CheckConstraint 表达，
      在 `clean()` 中进行模型层兜底校验。
    """

    class Side(models.TextChoices):
        """交易方向枚举，仅允许买入或卖出。"""

        BUY = "BUY", "BUY"
        SELL = "SELL", "SELL"

    # 交易所属用户。
    # 用户删除时级联清理；建立索引便于按用户查询投资历史。
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="investment_records",
    )

    # 交易标的。
    # 使用 `PROTECT`，防止历史记录仍存在时标的被删除。
    instrument = models.ForeignKey(
        "market.Instrument",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="investment_records",
    )

    # 买卖方向，受 `Side` 枚举约束，并建立索引支持方向筛选。
    side = models.CharField(max_length=8, choices=Side.choices, db_index=True)

    # 成交数量，支持 6 位小数，适合股票/基金/加密货币等场景。
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    # 成交价格，支持 6 位小数。
    price = models.DecimalField(max_digits=20, decimal_places=6)

    # 发生现金流的账户。
    # 买卖交易会从该账户扣款或入账。
    cash_account = models.ForeignKey(
        "accounts.Accounts",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="investment_records",
    )
    # 与该笔投资记录绑定的现金流水。
    # 一笔投资记录最多绑定一条资金流水；允许为空是为了兼容删除流水后的解绑场景。
    cash_transaction = models.OneToOneField(
        "accounts.Transaction",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="investment_record",
    )

    # 业务成交时间，用于按真实交易时刻排序和筛选。
    trade_at = models.DateTimeField(default=timezone.now, db_index=True)

    # 已实现盈亏。
    # 买入必须为空；卖出必须保存本次卖出的已实现盈亏。
    realized_pnl = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)

    # 记录创建时间。
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 数据库物理表名。
        db_table = "investment_record"
        # 常用查询索引：按用户时间、用户+标的、资金账户、用户+方向检索。
        indexes = [
            models.Index(fields=["user", "trade_at"]),
            models.Index(fields=["user", "instrument", "trade_at"]),
            models.Index(fields=["cash_account", "trade_at"]),
            models.Index(fields=["user", "side", "trade_at"]),
        ]
        # 数据层约束：数量、价格大于 0，以及买卖方向与已实现盈亏字段保持一致。
        constraints = [
            check_constraint(expr=Q(quantity__gt=0), name="invrec_quantity_gt_0"),
            check_constraint(expr=Q(price__gt=0), name="invrec_price_gt_0"),

            # BUY: realized_pnl 必须为 NULL
            check_constraint(
                expr=Q(side="BUY", realized_pnl__isnull=True) | Q(side="SELL"),
                name="invrec_buy_realized_pnl_null",
            ),
            # SELL: realized_pnl 必须非 NULL
            check_constraint(
                expr=Q(side="SELL", realized_pnl__isnull=False) | Q(side="BUY"),
                name="invrec_sell_realized_pnl_not_null",
            ),
        ]

    # 执行数据库无法表达的跨表一致性校验。
    def clean(self):
        # 用户一致性约束（跨表，DB CheckConstraint 做不到，只能在模型/业务层兜住）
        if self.cash_account_id and self.user_id:
            if self.cash_account.user_id != self.user_id:
                raise ValidationError({"cash_account": "cash_account 不属于该 user，禁止绑定。"})
        if self.cash_transaction_id and self.user_id:
            if self.cash_transaction.user_id != self.user_id:
                raise ValidationError({"cash_transaction": "cash_transaction 不属于该 user，禁止绑定。"})
        if self.cash_transaction_id and self.cash_account_id:
            if self.cash_transaction.account_id != self.cash_account_id:
                raise ValidationError({"cash_transaction": "cash_transaction 与 cash_account 不一致。"})

        if self.side == "BUY" and self.realized_pnl is not None:
            raise ValidationError({"realized_pnl": "BUY 记录不允许填写 realized_pnl（必须为 NULL）。"})
        if self.side == "SELL" and self.realized_pnl is None:
            raise ValidationError({"realized_pnl": "SELL 记录必须填写 realized_pnl。"})

    # 保存前先做完整校验，确保模型约束与业务约束同时生效。
    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Position(models.Model):
    """
    用户持仓模型。

    用途：
    - 维护用户当前仍然存在的标的仓位。
    - 由买入/卖出服务实时更新，用于持仓列表、估值与系统投资账户余额同步。

    约束说明：
    - `UniqueConstraint(user, instrument)`：同一用户对同一标的只能存在一条持仓记录。
    - `quantity / avg_cost / cost_total` 必须大于等于 0。
    - 当 `quantity = 0` 时，`avg_cost` 和 `cost_total` 必须同时为 0，避免出现“空仓但仍有成本”。
    """

    # 持仓所属用户。
    # 用户删除时级联删除持仓，建立索引便于按用户查询。
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="positions",
    )

    # 持仓对应的交易标的。
    # 使用 `PROTECT`，防止存在持仓时标的被删除。
    instrument = models.ForeignKey(
        "market.Instrument",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="positions",
    )

    # 当前持仓数量。
    quantity = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    # 当前持仓平均成本价。
    avg_cost = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    # 当前持仓剩余总成本。
    cost_total = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    # 累计已实现盈亏。
    # 即使仓位被清空，该值也会在持仓快照/响应中被保留用于统计。
    realized_pnl_total = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))

    # 最近一次更新持仓的时间。
    updated_at = models.DateTimeField(auto_now=True)
    # 持仓记录创建时间。
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 数据库物理表名。
        db_table = "investment_position"
        # 唯一约束与数值约束共同保证持仓状态自洽。
        constraints = [
            models.UniqueConstraint(fields=["user", "instrument"], name="uniq_user_instrument_position"),

            check_constraint(expr=Q(quantity__gte=0), name="pos_quantity_gte_0"),
            check_constraint(expr=Q(avg_cost__gte=0), name="pos_avg_cost_gte_0"),
            check_constraint(expr=Q(cost_total__gte=0), name="pos_cost_total_gte_0"),

            # quantity=0 => avg_cost=0 且 cost_total=0
            check_constraint(
                expr=Q(quantity=0, avg_cost=0, cost_total=0) | Q(quantity__gt=0),
                name="pos_zero_qty_means_zero_cost",
            ),
        ]
        # 优化按用户查看最近更新持仓的查询。
        indexes = [
            models.Index(fields=["user", "updated_at"]),
        ]

