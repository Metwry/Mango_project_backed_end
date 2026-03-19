from decimal import Decimal

from django.db import models
from django.db.models import Q

from accounts.models import Currency
from common.db.constraints import check_constraint


class SnapshotDataStatus(models.TextChoices):
    """快照数据状态枚举，用于标记行情或汇率是否完整。"""

    OK = "ok", "正常"
    QUOTE_MISSING = "quote_missing", "缺少行情"
    FX_MISSING = "fx_missing", "缺少汇率"


class SnapshotLevel(models.TextChoices):
    """快照粒度枚举，表示时间序列的采样间隔。"""

    M15 = "M15", "15分钟"
    H4 = "H4", "4小时"
    D1 = "D1", "1天"
    MON1 = "MON1", "1月"


class AccountSnapshot(models.Model):
    """
    账户维度快照模型。

    用途：
    - 记录某个账户在某一时间桶上的账户余额快照。
    - 既支持普通现金类账户，也支持系统投资账户聚合后的估值结果。

    约束说明：
    - `UniqueConstraint(account, snapshot_level, snapshot_time)`：同一账户在同一粒度、同一时间点仅保留一条快照。
    - `fx_rate_to_usd` 允许为空；若存在则必须大于 0。
    - 索引 `("snapshot_level", "snapshot_time")` 便于按粒度和时间区间批量查询。
    """

    # 对应的账户。
    # 使用 `PROTECT`，防止存在快照时账户被删除。
    account = models.ForeignKey(
        "accounts.Accounts",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="account_snapshots",
    )
    # 快照时间点。
    # 实际写入前会在服务层对齐到对应粒度时间桶。
    snapshot_time = models.DateTimeField(db_index=True)
    # 快照粒度，例如 15 分钟、4 小时、日、月。
    snapshot_level = models.CharField(max_length=8, choices=SnapshotLevel.choices, default=SnapshotLevel.M15)
    # 账户本位币。
    account_currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.USD)
    # 账户余额的本币值。
    balance_native = models.DecimalField(max_digits=20, decimal_places=6)
    # 账户余额折算后的美元值，用于跨币种汇总。
    balance_usd = models.DecimalField(max_digits=20, decimal_places=6)
    # 从账户本位币折算到美元所使用的汇率。
    # 若账户本位币即 USD，则通常为 1；若汇率缺失，则可能为空。
    fx_rate_to_usd = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    # 数据状态，标记该快照是否缺失汇率或其他必要数据。
    data_status = models.CharField(max_length=20, choices=SnapshotDataStatus.choices, default=SnapshotDataStatus.OK)
    # 快照记录创建时间。
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 数据库物理表名。
        db_table = "snapshot_account_snapshot"
        # 同一账户同一时间桶只允许一条记录。
        constraints = [
            models.UniqueConstraint(fields=["account", "snapshot_level", "snapshot_time"], name="uniq_snap_acc_lvl_time"),
            check_constraint(expr=Q(fx_rate_to_usd__isnull=True) | Q(fx_rate_to_usd__gt=0), name="snap_acc_fx_rate_null_or_gt_0"),
        ]
        # 优化按粒度和时间范围扫描账户快照。
        indexes = [
            models.Index(fields=["snapshot_level", "snapshot_time"], name="snap_acc_lvl_time_idx"),
        ]


class PositionSnapshot(models.Model):
    """
    持仓维度快照模型。

    用途：
    - 记录某个投资账户下某个标的在指定时间桶上的持仓数量、成本和市值信息。
    - 为前端绘制持仓价格/市值曲线、分析行情缺失情况提供基础数据。

    约束说明：
    - `UniqueConstraint(account, instrument, snapshot_level, snapshot_time)`：同一账户、同一标的、同一粒度、同一时间点只能有一条快照。
    - `quantity / avg_cost >= 0`，`market_value / market_value_usd >= 0`。
    - `market_price`、`fx_rate_to_usd` 若存在则必须大于 0。
    - `snap_pos_status_price_consistent`：当状态为 `OK` 时必须存在行情价格和本币市值；
      若状态为 `QUOTE_MISSING` 或 `FX_MISSING`，允许部分估值字段为空。
    - 两组索引分别优化按账户查询和按全局粒度时间扫描。
    """

    # 对应的投资账户。
    # 快照以账户为维度存储，通常为系统投资账户。
    account = models.ForeignKey(
        "accounts.Accounts",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="position_snapshots",
    )
    # 对应的交易标的。
    instrument = models.ForeignKey(
        "market.Instrument",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="position_snapshots",
    )
    # 快照时间点，对齐后写入。
    snapshot_time = models.DateTimeField(db_index=True)
    # 快照粒度。
    snapshot_level = models.CharField(max_length=8, choices=SnapshotLevel.choices, default=SnapshotLevel.M15)
    # 持仓数量。
    quantity = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    # 平均持仓成本。
    avg_cost = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    # 快照时刻对应的市场价格；若缺行情可为空。
    market_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    # 本币市值，即数量 * 市场价格；行情缺失时可为空。
    market_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    # 折算为美元后的市值；汇率缺失时可为空。
    market_value_usd = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    # 本币转美元所用汇率；若缺失则为空。
    fx_rate_to_usd = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    # 累计已实现盈亏快照值。
    realized_pnl = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    # 使用的行情时间戳，用于判断价格新鲜度。
    price_time = models.DateTimeField(null=True, blank=True)
    # 持仓计价币种。
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.USD)
    # 数据状态，标识是否缺失行情或汇率。
    data_status = models.CharField(max_length=20, choices=SnapshotDataStatus.choices, default=SnapshotDataStatus.OK)
    # 快照记录创建时间。
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 数据库物理表名。
        db_table = "snapshot_position_snapshot"
        # 唯一约束与数值约束共同保证单个持仓快照的完整性。
        constraints = [
            models.UniqueConstraint(
                fields=["account", "instrument", "snapshot_level", "snapshot_time"],
                name="uniq_snap_pos_inst_lvl_time",
            ),
            check_constraint(expr=Q(quantity__gte=0), name="snap_pos_quantity_gte_0"),
            check_constraint(expr=Q(avg_cost__gte=0), name="snap_pos_avg_cost_gte_0"),
            check_constraint(
                expr=Q(market_price__isnull=True) | Q(market_price__gt=0),
                name="snap_pos_market_price_null_or_gt_0",
            ),
            check_constraint(
                expr=Q(market_value__isnull=True) | Q(market_value__gte=0),
                name="snap_pos_market_value_null_or_gte_0",
            ),
            check_constraint(
                expr=Q(market_value_usd__isnull=True) | Q(market_value_usd__gte=0),
                name="snap_pos_market_usd_null_or_gte_0",
            ),
            check_constraint(
                expr=Q(fx_rate_to_usd__isnull=True) | Q(fx_rate_to_usd__gt=0),
                name="snap_pos_fx_rate_null_or_gt_0",
            ),
            check_constraint(
                expr=(
                    Q(data_status=SnapshotDataStatus.OK, market_price__isnull=False, market_value__isnull=False)
                    | Q(data_status=SnapshotDataStatus.QUOTE_MISSING)
                    | Q(data_status=SnapshotDataStatus.FX_MISSING)
                ),
                name="snap_pos_status_price_consistent",
            ),
        ]
        # 账户维度索引用于单账户时序查询，全局索引用于批量聚合或清理。
        indexes = [
            models.Index(fields=["account", "snapshot_level", "snapshot_time"], name="snap_pos_acc_lvl_time_idx"),
            models.Index(fields=["snapshot_level", "snapshot_time"], name="snap_pos_lvl_time_idx"),
        ]

