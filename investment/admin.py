from django.contrib import admin

from .models import InvestmentRecord, Position


@admin.register(InvestmentRecord)
class InvestmentRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "instrument",
        "side",
        "quantity",
        "price",
        "cash_account",
        "trade_at",
        "realized_pnl",
        "created_at",
    )
    list_filter = ("side", "trade_at", "created_at")
    search_fields = (
        "user__username",
        "user__email",
        "instrument__symbol",
        "instrument__name",
        "cash_account__name",
    )
    list_select_related = ("user", "instrument", "cash_account", "cash_transaction")
    ordering = ("-trade_at", "-id")
    autocomplete_fields = ("user", "instrument", "cash_account", "cash_transaction")
    readonly_fields = ("created_at",)
    date_hierarchy = "trade_at"


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "instrument",
        "quantity",
        "avg_cost",
        "cost_total",
        "realized_pnl_total",
        "updated_at",
        "created_at",
    )
    list_filter = ("updated_at", "created_at")
    search_fields = ("user__username", "user__email", "instrument__symbol", "instrument__name")
    list_select_related = ("user", "instrument")
    ordering = ("-updated_at", "-id")
    autocomplete_fields = ("user", "instrument")
    readonly_fields = ("updated_at", "created_at")
