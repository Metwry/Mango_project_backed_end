from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from common.db.constraints import check_constraint


class Instrument(models.Model):
    """
    交易标的主数据模型。

    用途：
    - 维护股票、指数、加密货币、外汇等可查询/可交易标的的基础信息。
    - 被投资记录、持仓、自选订阅、快照等多个业务表引用。

    约束说明：
    - `symbol` 全局唯一，作为系统内统一代码。
    - `short_code`、`name` 均建索引，用于搜索和展示。
    - 额外组合索引 `("short_code", "name")` 用于优化搜索接口的前缀/模糊匹配。
    - `is_active` 用于软停用标的，避免历史数据丢失。
    """

    class AssetClass(models.TextChoices):
        """资产大类枚举。"""

        STOCK = "STOCK", _("股票 (Stock)")
        INDEX = "INDEX", _("指数 (Index)")
        CRYPTO = "CRYPTO", _("加密货币 (Crypto)")
        FOREX = "FOREX", _("外汇 (Forex)")

    class Market(models.TextChoices):
        """市场枚举，用于标识交易所或交易区域。"""

        US = "US", _("美股 (United States)")
        CN = "CN", _("A股 (China)")
        HK = "HK", _("港股 (Hong Kong)")
        CRYPTO = "CRYPTO", _("加密货币市场 (Crypto)")
        FX = "FX", _("外汇市场 (Forex)")

    # 系统内统一代码，全局唯一，例如 `AAPL.US`、`BTCUSDT.CRYPTO`。
    symbol = models.CharField(max_length=50, unique=True, verbose_name="标准代码")
    # 原始短代码，通常用于行情源请求或展示，例如 `AAPL`、`BTCUSDT`。
    short_code = models.CharField(max_length=20, db_index=True, verbose_name="原始代码")
    # 标的名称，支持搜索与列表展示。
    name = models.CharField(max_length=100, db_index=True, verbose_name="品种名称")

    # 资产大类，决定该标的是否可被投资交易或在哪些接口中展示。
    asset_class = models.CharField(
        max_length=20,
        choices=AssetClass.choices,
        default=AssetClass.STOCK,
        verbose_name="资产大类",
    )
    # 所属市场，用于行情抓取、交易时段判断和默认币种推断。
    market = models.CharField(
        max_length=20,
        choices=Market.choices,
        default=Market.US,
        verbose_name="所属市场",
    )
    # 交易所代码或名称，可为空。
    exchange = models.CharField(max_length=50, blank=True, null=True, verbose_name="交易所")
    # 标的计价币种，可为空；为空时会按市场默认币种推断。
    base_currency = models.CharField(max_length=10, blank=True, null=True, verbose_name="计价货币")
    # 标的 logo 图片地址，可为空。
    logo_url = models.URLField(max_length=500, blank=True, null=True, verbose_name="Logo URL")
    # logo 提取出的主题色，可为空，用于前端卡片背景/装饰。
    logo_color = models.CharField(max_length=16, blank=True, null=True, verbose_name="Logo 主题色")
    # logo 数据来源标记，例如 logo.dev。
    logo_source = models.CharField(max_length=50, blank=True, null=True, verbose_name="Logo 来源")
    # 最近一次同步 logo 元数据的时间。
    logo_updated_at = models.DateTimeField(blank=True, null=True, verbose_name="Logo 更新时间")

    # 是否仍可被搜索、交易或加入自选。
    # 退市、下架或失效标的可通过该字段禁用而不删除历史数据。
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否可交易",
    )

    # 数据创建时间。
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    # 数据更新时间。
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        # 数据库物理表名。
        db_table = "market_instrument"
        # Django Admin 展示名称。
        verbose_name = "交易品种"
        verbose_name_plural = "交易品种列表"
        # 默认先按资产大类再按统一代码排序。
        ordering = ["asset_class", "symbol"]
    # 返回适合调试和管理后台展示的标的描述。
    def __str__(self):
        return f"{self.symbol} - {self.name}"


class UserInstrumentSubscription(models.Model):
    """
    用户标的订阅模型。

    用途：
    - 记录某个用户是否因“持仓”或“自选”而订阅某个标的。
    - 行情抓取、缓存裁剪和自选接口都依赖该表判断需要维护哪些标的。

    约束说明：
    - `UniqueConstraint(user, instrument)`：同一用户对同一标的只有一条订阅记录。
    - `sub_at_least_one_source_true`：`from_position` 和 `from_watchlist` 至少一个为真，
    避免出现“没有任何来源却仍保留订阅”的脏数据。
    - 索引分别优化按标的统计订阅、按用户查看最近变更订阅。
    """

    # 订阅所属用户。
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="instrument_subscriptions",
    )
    # 被订阅的标的。
    # 用户或标的删除时级联清理订阅关系。
    instrument = models.ForeignKey(
        "market.Instrument",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="user_subscriptions",
    )
    # 是否因持仓存在而自动订阅。
    from_position = models.BooleanField(default=False)
    # 是否因加入自选而订阅。
    from_watchlist = models.BooleanField(default=False)

    # 订阅创建时间。
    created_at = models.DateTimeField(auto_now_add=True)
    # 最近一次更新订阅来源的时间。
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # 数据库物理表名。
        db_table = "market_user_instrument_subscription"
        # 唯一约束和检查约束共同维护订阅来源的自洽性。
        constraints = [
            models.UniqueConstraint(fields=["user", "instrument"], name="uniq_user_instrument_subscription"),
            check_constraint(
                expr=Q(from_position=True) | Q(from_watchlist=True),
                name="sub_at_least_one_source_true",
            ),
        ]
        # 优化按标的和按用户维度的订阅查询。
        indexes = [
            models.Index(fields=["instrument"], name="mkt_sub_instrument_idx"),
            models.Index(fields=["user", "updated_at"], name="mkt_sub_user_updated_idx"),
        ]

