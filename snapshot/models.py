from decimal import Decimal

from django.db import models
from django.db.models import Q

from accounts.models import Currency
from shared.db import check_constraint


class SnapshotDataStatus(models.TextChoices):
    OK = "ok", "正常"
    QUOTE_MISSING = "quote_missing", "缺少行情"
    FX_MISSING = "fx_missing", "缺少汇率"


class SnapshotLevel(models.TextChoices):
    M15 = "M15", "15分钟"
    H4 = "H4", "4小时"
    D1 = "D1", "1天"
    MON1 = "MON1", "1月"


class AccountSnapshot(models.Model):
    account = models.ForeignKey(
        "accounts.Accounts",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="account_snapshots",
    )
    snapshot_time = models.DateTimeField(db_index=True)
    snapshot_level = models.CharField(max_length=8, choices=SnapshotLevel.choices, default=SnapshotLevel.M15)
    account_currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.USD)
    balance_native = models.DecimalField(max_digits=20, decimal_places=6)
    balance_usd = models.DecimalField(max_digits=20, decimal_places=6)
    fx_rate_to_usd = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    data_status = models.CharField(max_length=20, choices=SnapshotDataStatus.choices, default=SnapshotDataStatus.OK)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "snapshot_account_snapshot"
        constraints = [
            models.UniqueConstraint(fields=["account", "snapshot_level", "snapshot_time"], name="uniq_snap_acc_lvl_time"),
            check_constraint(expr=Q(fx_rate_to_usd__isnull=True) | Q(fx_rate_to_usd__gt=0), name="snap_acc_fx_rate_null_or_gt_0"),
        ]
        indexes = [
            models.Index(fields=["snapshot_level", "snapshot_time"], name="snap_acc_lvl_time_idx"),
        ]


class PositionSnapshot(models.Model):
    account = models.ForeignKey(
        "accounts.Accounts",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="position_snapshots",
    )
    instrument = models.ForeignKey(
        "market.Instrument",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="position_snapshots",
    )
    snapshot_time = models.DateTimeField(db_index=True)
    snapshot_level = models.CharField(max_length=8, choices=SnapshotLevel.choices, default=SnapshotLevel.M15)
    quantity = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    avg_cost = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    market_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    market_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    market_value_usd = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    fx_rate_to_usd = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    realized_pnl = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    price_time = models.DateTimeField(null=True, blank=True)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.USD)
    data_status = models.CharField(max_length=20, choices=SnapshotDataStatus.choices, default=SnapshotDataStatus.OK)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "snapshot_position_snapshot"
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
        indexes = [
            models.Index(fields=["account", "snapshot_level", "snapshot_time"], name="snap_pos_acc_lvl_time_idx"),
            models.Index(fields=["snapshot_level", "snapshot_time"], name="snap_pos_lvl_time_idx"),
        ]
