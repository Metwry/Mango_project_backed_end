from datetime import timedelta, timezone as dt_timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from shared.utils import trim_decimal_str

from .models import AccountSnapshot, PositionSnapshot, SnapshotLevel
from .serializers import AccountSnapshotQuerySerializer, PositionSnapshotQuerySerializer


INTERVAL_SECONDS = {
    SnapshotLevel.M15: 15 * 60,
    SnapshotLevel.H4: 4 * 60 * 60,
    SnapshotLevel.D1: 24 * 60 * 60,
}
INTERVAL_UNIT = {
    SnapshotLevel.M15: "minute",
    SnapshotLevel.H4: "hour",
    SnapshotLevel.D1: "day",
    SnapshotLevel.MON1: "month",
}


def _floor_bucket(dt, level: str):
    ts = dt.astimezone(dt_timezone.utc).replace(second=0, microsecond=0)
    if level == SnapshotLevel.M15:
        return ts.replace(minute=(ts.minute // 15) * 15)
    if level == SnapshotLevel.H4:
        return ts.replace(hour=(ts.hour // 4) * 4, minute=0)
    if level == SnapshotLevel.D1:
        return ts.replace(hour=0, minute=0)
    if level == SnapshotLevel.MON1:
        return ts.replace(day=1, hour=0, minute=0)
    return ts


def _next_bucket(ts, level: str):
    if level == SnapshotLevel.M15:
        return ts + timedelta(minutes=15)
    if level == SnapshotLevel.H4:
        return ts + timedelta(hours=4)
    if level == SnapshotLevel.D1:
        return ts + timedelta(days=1)
    if level == SnapshotLevel.MON1:
        month = ts.month + 1
        year = ts.year
        if month == 13:
            month = 1
            year += 1
        return ts.replace(year=year, month=month, day=1)
    return ts


def _ceil_bucket(dt, level: str):
    floored = _floor_bucket(dt, level)
    raw = dt.astimezone(dt_timezone.utc).replace(second=0, microsecond=0)
    if floored < raw:
        return _next_bucket(floored, level)
    return floored


def _build_axis(start_time, end_time, level: str):
    axis_start = _ceil_bucket(start_time, level)
    axis_end = _floor_bucket(end_time, level)
    if axis_start > axis_end:
        return [], axis_start, axis_end

    buckets = []
    current = axis_start
    while current <= axis_end:
        buckets.append(current)
        current = _next_bucket(current, level)
    return buckets, axis_start, axis_end


class AccountSnapshotQueryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = AccountSnapshotQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        level = params["level"]
        buckets, axis_start, axis_end = _build_axis(params["start_time"], params["end_time"], level)
        bucket_index = {bucket: idx for idx, bucket in enumerate(buckets)}
        point_count = len(buckets)

        if point_count == 0:
            return Response(
                {
                    "meta": {
                        "level": level,
                        "start_time": params["start_time"].isoformat(),
                        "end_time": params["end_time"].isoformat(),
                        "axis_start_time": axis_start.isoformat(),
                        "axis_end_time": axis_end.isoformat(),
                        "interval_unit": INTERVAL_UNIT.get(level),
                        "interval_seconds": INTERVAL_SECONDS.get(level),
                        "point_count": 0,
                    },
                    "series": [],
                },
                status=status.HTTP_200_OK,
            )

        queryset = (
            AccountSnapshot.objects
            .filter(
                account__user=request.user,
                snapshot_level=level,
                snapshot_time__gte=axis_start,
                snapshot_time__lte=axis_end,
            )
            .select_related("account")
            .only(
                "account_id",
                "account__name",
                "snapshot_time",
                "account_currency",
                "balance_usd",
                "data_status",
            )
            .order_by("account_id", "snapshot_time", "id")
        )

        account_id = params.get("account_id")
        if account_id is not None:
            queryset = queryset.filter(account_id=account_id)

        rows = list(queryset[: params["limit"]])
        series_map = {}
        for row in rows:
            key = row.account_id
            series = series_map.get(key)
            if series is None:
                series = {
                    "account_id": row.account_id,
                    "account_name": row.account.name,
                    "account_currency": row.account_currency,
                    "balance_usd": [None] * point_count,
                    "data_status": [None] * point_count,
                }
                series_map[key] = series

            ts = row.snapshot_time.astimezone(dt_timezone.utc).replace(second=0, microsecond=0)
            idx = bucket_index.get(ts)
            if idx is None:
                continue
            series["balance_usd"][idx] = trim_decimal_str(row.balance_usd)
            series["data_status"][idx] = row.data_status

        return Response(
            {
                "meta": {
                    "level": level,
                    "start_time": params["start_time"].isoformat(),
                    "end_time": params["end_time"].isoformat(),
                    "axis_start_time": axis_start.isoformat(),
                    "axis_end_time": axis_end.isoformat(),
                    "interval_unit": INTERVAL_UNIT.get(level),
                    "interval_seconds": INTERVAL_SECONDS.get(level),
                    "point_count": point_count,
                },
                "series_count": len(series_map),
                "series": list(series_map.values()),
            },
            status=status.HTTP_200_OK,
        )


class PositionSnapshotQueryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = PositionSnapshotQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        level = params["level"]
        buckets, axis_start, axis_end = _build_axis(params["start_time"], params["end_time"], level)
        bucket_index = {bucket: idx for idx, bucket in enumerate(buckets)}
        point_count = len(buckets)

        if point_count == 0:
            return Response(
                {
                    "meta": {
                        "level": level,
                        "start_time": params["start_time"].isoformat(),
                        "end_time": params["end_time"].isoformat(),
                        "axis_start_time": axis_start.isoformat(),
                        "axis_end_time": axis_end.isoformat(),
                        "interval_unit": INTERVAL_UNIT.get(level),
                        "interval_seconds": INTERVAL_SECONDS.get(level),
                        "point_count": 0,
                    },
                    "series": [],
                },
                status=status.HTTP_200_OK,
            )

        queryset = (
            PositionSnapshot.objects
            .filter(
                account__user=request.user,
                snapshot_level=level,
                snapshot_time__gte=axis_start,
                snapshot_time__lte=axis_end,
            )
            .select_related("account", "instrument")
            .only(
                "account_id",
                "account__name",
                "instrument_id",
                "instrument__symbol",
                "snapshot_time",
                "currency",
                "market_price",
                "market_value",
                "data_status",
            )
            .order_by("account_id", "instrument_id", "snapshot_time", "id")
        )

        if params.get("account_id") is not None:
            queryset = queryset.filter(account_id=params["account_id"])
        if params.get("instrument_id") is not None:
            queryset = queryset.filter(instrument_id=params["instrument_id"])

        rows = list(queryset[: params["limit"]])
        series_map = {}
        for row in rows:
            key = (row.account_id, row.instrument_id)
            series = series_map.get(key)
            if series is None:
                series = {
                    "account_id": row.account_id,
                    "account_name": row.account.name,
                    "instrument_id": row.instrument_id,
                    "symbol": row.instrument.symbol,
                    "currency": row.currency,
                    "market_price": [None] * point_count,
                    "market_value": [None] * point_count,
                    "data_status": [None] * point_count,
                }
                series_map[key] = series

            ts = row.snapshot_time.astimezone(dt_timezone.utc).replace(second=0, microsecond=0)
            idx = bucket_index.get(ts)
            if idx is None:
                continue
            series["market_price"][idx] = trim_decimal_str(row.market_price) if row.market_price is not None else None
            series["market_value"][idx] = trim_decimal_str(row.market_value) if row.market_value is not None else None
            series["data_status"][idx] = row.data_status

        return Response(
            {
                "meta": {
                    "level": level,
                    "start_time": params["start_time"].isoformat(),
                    "end_time": params["end_time"].isoformat(),
                    "axis_start_time": axis_start.isoformat(),
                    "axis_end_time": axis_end.isoformat(),
                    "interval_unit": INTERVAL_UNIT.get(level),
                    "interval_seconds": INTERVAL_SECONDS.get(level),
                    "point_count": point_count,
                },
                "series_count": len(series_map),
                "series": list(series_map.values()),
            },
            status=status.HTTP_200_OK,
        )
