from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import AccountSnapshotQuerySerializer, PositionSnapshotQuerySerializer
from .services import build_account_snapshot_query_result, build_position_snapshot_query_result


class AccountSnapshotQueryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = AccountSnapshotQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        payload = build_account_snapshot_query_result(user=request.user, params=serializer.validated_data)
        return Response(payload, status=status.HTTP_200_OK)


class PositionSnapshotQueryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = PositionSnapshotQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        payload = build_position_snapshot_query_result(user=request.user, params=serializer.validated_data)
        return Response(payload, status=status.HTTP_200_OK)
