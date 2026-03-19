from datetime import timezone as dt_timezone

from common.time import build_bucket_axis
from common.utils import trim_decimal_str

from snapshot.models import AccountSnapshot, PositionSnapshot, SnapshotLevel

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


# 在没有任何快照点时构造空序列返回结构。
def _build_empty_series_payload(*, params: dict, level: str, axis_start, axis_end):
    return {
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
    }


# 构造快照查询结果的元信息结构。
def _build_meta(*, params: dict, level: str, axis_start, axis_end, point_count: int):
    return {
        "level": level,
        "start_time": params["start_time"].isoformat(),
        "end_time": params["end_time"].isoformat(),
        "axis_start_time": axis_start.isoformat(),
        "axis_end_time": axis_end.isoformat(),
        "interval_unit": INTERVAL_UNIT.get(level),
        "interval_seconds": INTERVAL_SECONDS.get(level),
        "point_count": point_count,
    }


# 查询账户维度的快照时间序列数据。
def build_account_snapshot_query_result(*, user, params: dict) -> dict:
    level = params["level"]
    buckets, axis_start, axis_end = build_bucket_axis(params["start_time"], params["end_time"], level)
    bucket_index = {bucket: idx for idx, bucket in enumerate(buckets)}
    point_count = len(buckets)

    if point_count == 0:
        return _build_empty_series_payload(params=params, level=level, axis_start=axis_start, axis_end=axis_end)

    queryset = (
        AccountSnapshot.objects
        .filter(
            account__user=user,
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

    return {
        "meta": _build_meta(
            params=params,
            level=level,
            axis_start=axis_start,
            axis_end=axis_end,
            point_count=point_count,
        ),
        "series_count": len(series_map),
        "series": list(series_map.values()),
    }


# 查询持仓维度的快照时间序列数据。
def build_position_snapshot_query_result(*, user, params: dict) -> dict:
    level = params["level"]
    buckets, axis_start, axis_end = build_bucket_axis(params["start_time"], params["end_time"], level)
    bucket_index = {bucket: idx for idx, bucket in enumerate(buckets)}
    point_count = len(buckets)

    if point_count == 0:
        return _build_empty_series_payload(params=params, level=level, axis_start=axis_start, axis_end=axis_end)

    queryset = (
        PositionSnapshot.objects
        .filter(
            account__user=user,
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

    return {
        "meta": _build_meta(
            params=params,
            level=level,
            axis_start=axis_start,
            axis_end=axis_end,
            point_count=point_count,
        ),
        "series_count": len(series_map),
        "series": list(series_map.values()),
    }

