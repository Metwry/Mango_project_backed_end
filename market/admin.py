from django.contrib import admin

from .models import Instrument


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ("id", "symbol", "short_code", "name", "market", "asset_class", "is_active")
    list_filter = ("market", "asset_class", "is_active")
    search_fields = ("symbol", "short_code", "name")
