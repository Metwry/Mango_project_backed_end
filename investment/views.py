from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    InvestmentHistoryItemSerializer,
    InvestmentHistoryQuerySerializer,
    InvestmentBuySerializer,
    InvestmentSellSerializer,
    PositionDeleteSerializer,
    PositionListItemSerializer,
)
from .services import (
    build_position_list_queryset,
    delete_zero_position,
    execute_buy,
    execute_sell,
    query_investment_history,
)


class InvestmentBuyView(APIView):
    permission_classes = [IsAuthenticated]

    # 执行买入交易并返回持仓与资金流水结果。
    def post(self, request, *args, **kwargs):
        serializer = InvestmentBuySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = execute_buy(user=request.user, **serializer.validated_data)
        return Response(result, status=status.HTTP_201_CREATED)


class InvestmentSellView(APIView):
    permission_classes = [IsAuthenticated]

    # 执行卖出交易并返回持仓、已实现盈亏与资金流水结果。
    def post(self, request, *args, **kwargs):
        serializer = InvestmentSellSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = execute_sell(user=request.user, **serializer.validated_data)
        return Response(result, status=status.HTTP_201_CREATED)


class InvestmentPositionListView(APIView):
    permission_classes = [IsAuthenticated]

    # 返回当前用户的有效持仓列表。
    def get(self, request, *args, **kwargs):
        queryset = build_position_list_queryset(user=request.user)
        serializer = PositionListItemSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class InvestmentPositionDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    # 删除数量为 0 的持仓记录。
    def delete(self, request, instrument_id: int, *args, **kwargs):
        serializer = PositionDeleteSerializer(data={"instrument_id": instrument_id})
        serializer.is_valid(raise_exception=True)
        result = delete_zero_position(
            user=request.user,
            instrument_id=serializer.validated_data["instrument_id"],
        )
        return Response(result, status=status.HTTP_200_OK)


class InvestmentHistoryListView(APIView):
    permission_classes = [IsAuthenticated]

    # 按筛选条件查询投资交易历史。
    def get(self, request, *args, **kwargs):
        query_serializer = InvestmentHistoryQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        result = query_investment_history(user=request.user, params=query_serializer.validated_data)

        return Response(
            {
                "count": result["count"],
                "offset": result["offset"],
                "limit": result["limit"],
                "items": InvestmentHistoryItemSerializer(result["rows"], many=True).data,
            },
            status=status.HTTP_200_OK,
        )
