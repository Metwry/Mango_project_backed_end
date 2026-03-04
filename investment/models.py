from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from shared.db import check_constraint


class InvestmentRecord(models.Model):
    class Side(models.TextChoices):
        BUY = "BUY", "BUY"
        SELL = "SELL", "SELL"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="investment_records",
    )

    instrument = models.ForeignKey(
        "market.Instrument",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="investment_records",
    )

    side = models.CharField(max_length=8, choices=Side.choices, db_index=True)

    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    price = models.DecimalField(max_digits=20, decimal_places=6)

    cash_account = models.ForeignKey(
        "accounts.Accounts",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="investment_records",
    )
    cash_transaction = models.OneToOneField(
        "accounts.Transaction",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="investment_record",
    )

    trade_at = models.DateTimeField(default=timezone.now, db_index=True)

    realized_pnl = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "investment_record"
        indexes = [
            models.Index(fields=["user", "trade_at"]),
            models.Index(fields=["user", "instrument", "trade_at"]),
            models.Index(fields=["cash_account", "trade_at"]),
            models.Index(fields=["user", "side", "trade_at"]),
        ]
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

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Position(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="positions",
    )

    instrument = models.ForeignKey(
        "market.Instrument",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="positions",
    )

    quantity = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    avg_cost = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    cost_total = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    realized_pnl_total = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "investment_position"
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
        indexes = [
            models.Index(fields=["user", "updated_at"]),
        ]
