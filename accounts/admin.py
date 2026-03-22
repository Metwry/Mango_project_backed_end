from django.contrib import admin
from .models import Accounts, Transaction


@admin.register(Accounts)
class AccountsAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "name", "type", "currency", "balance", "status", "updated_at")
    list_display_links = ("name",)
    list_filter = ("type", "currency", "status", "created_at", "updated_at")
    search_fields = ("name", "user__username", "user__email")
    list_select_related = ("user",)
    ordering = ("-updated_at",)
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "account",
        "transfer_account",
        "counterparty",
        "amount",
        "currency",
        "source",
        "add_date",
        "created_at",
    )
    list_filter = ("source", "currency", "add_date", "created_at")
    search_fields = ("counterparty", "account__name", "transfer_account__name", "user__username", "user__email")
    list_select_related = ("user", "account", "transfer_account", "reversal_of")
    ordering = ("-created_at", "-id")
    autocomplete_fields = ("user", "account", "transfer_account", "reversal_of")
    readonly_fields = ("balance_after", "created_at")
    date_hierarchy = "add_date"
