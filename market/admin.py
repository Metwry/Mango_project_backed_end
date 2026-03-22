from django.contrib import admin

from .models import Instrument, UserInstrumentSubscription


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ("id", "symbol", "short_code", "name", "market", "asset_class", "is_active")
    list_filter = ("market", "asset_class", "is_active", "base_currency", "created_at", "updated_at")
    search_fields = ("symbol", "short_code", "name")
    ordering = ("asset_class", "symbol")
    readonly_fields = ("created_at", "updated_at", "logo_updated_at")


@admin.register(UserInstrumentSubscription)
class UserInstrumentSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "instrument",
        "from_position",
        "from_watchlist",
        "updated_at",
        "created_at",
    )
    list_filter = ("from_position", "from_watchlist", "created_at", "updated_at")
    search_fields = ("user__username", "user__email", "instrument__symbol", "instrument__name")
    list_select_related = ("user", "instrument")
    ordering = ("-updated_at", "-id")
    autocomplete_fields = ("user", "instrument")
    readonly_fields = ("created_at", "updated_at")
