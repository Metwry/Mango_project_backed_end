from django_filters import rest_framework as filters
from rest_framework import filters as drf_filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Transaction
from .pagination import TransactionPagination
from .services.account_service import (
    archive_account,
    get_user_accounts_queryset,
    should_include_archived,
    update_account_from_serializer,
)
from .services.query_service import get_account_summary
from .services.transaction_service import (
    create_transaction_for_user,
    delete_single_transaction,
    delete_transactions_by_source,
    reverse_transaction,
)
from .serializers import AccountSerializer, TransactionDeleteQuerySerializer, TransactionSerializer


class AccountSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        payload = get_account_summary(user=request.user)
        return Response(payload, status=status.HTTP_200_OK)


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer

    # 返回当前用户的账户列表，并按请求参数决定是否包含已归档账户。
    def get_queryset(self):
        include_archived = should_include_archived(self.request.query_params.get("include_archived"))
        return get_user_accounts_queryset(user=self.request.user, include_archived=include_archived)

    # 调用账户服务层完成账户更新，并处理投资账户的特殊同步逻辑。
    def perform_update(self, serializer):
        serializer.instance = update_account_from_serializer(serializer=serializer)

    # 将删除请求转为归档操作，并在存在业务冲突时返回冲突信息。
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        conflict_payload = archive_account(account=instance, user=request.user)
        if conflict_payload:
            return Response(conflict_payload, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)

# 查询过滤器
class TransactionFilter(filters.FilterSet):
    reversed_at__isnull = filters.BooleanFilter(field_name="reversed_at", lookup_expr="isnull")
    account_id = filters.NumberFilter(field_name="account")
    account_name = filters.CharFilter(field_name="account__name", lookup_expr="icontains")
    # 转账查询
    transfer_account_id = filters.NumberFilter(field_name="transfer_account")
    transfer_account_name = filters.CharFilter(field_name="transfer_account__name", lookup_expr="icontains")

    counterparty = filters.CharFilter(lookup_expr="icontains")
    category = filters.CharFilter(field_name="category_name", lookup_expr="icontains")
    start = filters.DateTimeFilter(field_name="add_date", lookup_expr="gte")
    end = filters.DateTimeFilter(field_name="add_date", lookup_expr="lte")

    class Meta:
        model = Transaction
        fields = ["currency", "source", "reversed_at__isnull"]


class TransactionViewSet(viewsets.ModelViewSet):
    serializer_class = TransactionSerializer
    pagination_class = TransactionPagination

    filter_backends = [filters.DjangoFilterBackend, drf_filters.OrderingFilter]
    filterset_class = TransactionFilter
    ordering_fields = ["amount", "created_at", "add_date"]

    # ed 仅返回当前用户交易；其余筛选统一交给 filter backends。
    def get_queryset(self):
        return (
            Transaction.objects
            .select_related("account", "transfer_account")
            .filter(user=self.request.user)
            .order_by("-add_date", "-id")
        )

    # 为当前用户创建一条手工记账或转账记录。
    def perform_create(self, serializer):
        serializer.instance = create_transaction_for_user(serializer=serializer, user=self.request.user)

    # ed 无法更新交易记录
    def update(self, request, *args, **kwargs):
        raise ValidationError({"message": "交易记录不允许更改。"})

    def partial_update(self, request, *args, **kwargs):
        raise ValidationError({"message": "交易记录不允许更改。"})

    # ed 统一使用集合 DELETE 接口按 id/source 删除交易。
    def destroy(self, request, *args, **kwargs):
        raise ValidationError({"message": "请使用 DELETE /api/user/transactions/delete/?id=<交易ID> 或 ?source=<类型>。"})

    @action(detail=False, methods=["delete"], url_path="delete")
    # ed 通过查询参数选择按单条 id 或 source 批量删除。
    def delete_records(self, request):
        serializer = TransactionDeleteQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        tx_id = serializer.validated_data.get("id")
        source = serializer.validated_data.get("source")

        if tx_id is not None:
            delete_single_transaction(user=request.user, tx_id=tx_id)
            return Response({"id": tx_id, "deleted_count": 1}, status=status.HTTP_200_OK)

        result = delete_transactions_by_source(
            user=request.user,
            source=source,
        )
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    # edd 撤销指定交易；仅手工记账原交易允许撤销。
    def reverse(self, request, pk=None):
        try:
            tx_id = int(pk)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"message": "交易ID格式不正确。"}) from exc

        reverse_row = reverse_transaction(user=request.user, tx_id=tx_id)
        return Response(self.get_serializer(reverse_row).data, status=status.HTTP_201_CREATED)
