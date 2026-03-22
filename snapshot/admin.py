from django.contrib import admin

from .models import AccountSnapshot, PositionSnapshot


@admin.register(AccountSnapshot)
class AccountSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "account",
        "snapshot_level",
        "snapshot_time",
        "account_currency",
        "balance_native",
        "balance_usd",
        "data_status",
    )
    list_filter = ("snapshot_level", "account_currency", "data_status", "snapshot_time")
    search_fields = ("account__name", "account__user__username", "account__user__email")
    list_select_related = ("account", "account__user")
    ordering = ("-snapshot_time", "-id")
    autocomplete_fields = ("account",)
    date_hierarchy = "snapshot_time"


@admin.register(PositionSnapshot)
class PositionSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "account",
        "instrument",
        "snapshot_level",
        "snapshot_time",
        "quantity",
        "market_price",
        "market_value",
        "market_value_usd",
        "currency",
        "data_status",
    )
    list_filter = ("snapshot_level", "currency", "data_status", "snapshot_time")
    search_fields = (
        "account__name",
        "account__user__username",
        "account__user__email",
        "instrument__symbol",
        "instrument__name",
    )
    list_select_related = ("account", "account__user", "instrument")
    ordering = ("-snapshot_time", "-id")
    autocomplete_fields = ("account", "instrument")
    date_hierarchy = "snapshot_time"
