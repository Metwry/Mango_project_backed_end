# pagination.py
from rest_framework.pagination import PageNumberPagination

class TransactionPagination(PageNumberPagination):
    page_size = 10                 # 默认每页 20（前端不传 page_size 时）
    page_query_param = "page"      # 默认就是 page，可不写
    page_size_query_param = "page_size"  # ✅ 允许前端传 page_size
    max_page_size = 200            # 防止一次拉太多
