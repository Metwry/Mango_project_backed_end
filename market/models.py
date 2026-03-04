from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from shared.db import check_constraint


class Instrument(models.Model):
    class AssetClass(models.TextChoices):
        STOCK = "STOCK", _("股票 (Stock)")
        CRYPTO = "CRYPTO", _("加密货币 (Crypto)")
        FOREX = "FOREX", _("外汇 (Forex)")

    class Market(models.TextChoices):
        US = "US", _("美股 (United States)")
        CN = "CN", _("A股 (China)")
        HK = "HK", _("港股 (Hong Kong)")
        CRYPTO = "CRYPTO", _("加密货币市场 (Crypto)")
        FX = "FX", _("外汇市场 (Forex)")

    symbol = models.CharField(max_length=50, unique=True, db_index=True, verbose_name="标准代码")
    short_code = models.CharField(max_length=20, db_index=True, verbose_name="原始代码")
    name = models.CharField(max_length=100, db_index=True, verbose_name="品种名称")

    asset_class = models.CharField(
        max_length=20,
        choices=AssetClass.choices,
        default=AssetClass.STOCK,
        verbose_name="资产大类",
    )
    market = models.CharField(
        max_length=20,
        choices=Market.choices,
        default=Market.US,
        verbose_name="所属市场",
    )
    exchange = models.CharField(max_length=50, blank=True, null=True, verbose_name="交易所")
    base_currency = models.CharField(max_length=10, blank=True, null=True, verbose_name="计价货币")
    logo_url = models.URLField(max_length=500, blank=True, null=True, verbose_name="Logo URL")
    logo_color = models.CharField(max_length=16, blank=True, null=True, verbose_name="Logo 主题色")
    logo_source = models.CharField(max_length=50, blank=True, null=True, verbose_name="Logo 来源")
    logo_updated_at = models.DateTimeField(blank=True, null=True, verbose_name="Logo 更新时间")

    is_active = models.BooleanField(
        default=True,
        verbose_name="是否可交易",
        help_text="用于标记退市股票或下架品种",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "market_instrument"
        verbose_name = "交易品种"
        verbose_name_plural = "交易品种列表"
        ordering = ["asset_class", "symbol"]
        indexes = [
            models.Index(fields=["short_code", "name"], name="market_inst_short_c_cb36ea_idx"),
        ]

    def __str__(self):
        return f"{self.symbol} - {self.name}"


class UserInstrumentSubscription(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="instrument_subscriptions",
    )
    instrument = models.ForeignKey(
        "market.Instrument",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="user_subscriptions",
    )
    from_position = models.BooleanField(default=False)
    from_watchlist = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "market_user_instrument_subscription"
        constraints = [
            models.UniqueConstraint(fields=["user", "instrument"], name="uniq_user_instrument_subscription"),
            check_constraint(
                expr=Q(from_position=True) | Q(from_watchlist=True),
                name="sub_at_least_one_source_true",
            ),
        ]
        indexes = [
            models.Index(fields=["instrument"], name="mkt_sub_instrument_idx"),
            models.Index(fields=["user", "updated_at"], name="mkt_sub_user_updated_idx"),
        ]
