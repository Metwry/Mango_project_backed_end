from django.contrib import admin
from .models import Accounts, Transaction


@admin.register(Accounts)
class AccountsAdmin(admin.ModelAdmin):
    # 在列表中显示的字段
    list_display = ('id', 'user', 'name', 'type', 'currency', 'balance', 'updated_at')
    # 允许点击进入编辑的字段
    list_display_links = ('name',)
    # 右侧的筛选过滤器
    list_filter = ('currency', 'type', 'status')
    # 顶部的搜索框
    search_fields = ('name', 'user__username')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    # 显示字段
    list_display = ('id', 'user', 'account', 'counterparty', 'amount', 'currency', 'created_at')
    # 筛选
    list_filter = ('currency', 'created_at')
    # 搜索
    search_fields = ('counterparty', 'account__name', 'user__username')

    # 重点：因为我们在 save 方法里自动填充 user，
    # 所以在后台创建时，可以把 user 字段设为只读，或者干脆不显示，
    # 让你亲自验证那个 save 方法是否生效。
    readonly_fields = ('user',)