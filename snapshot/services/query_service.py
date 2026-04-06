from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from common.normalize import normalize_datetime_to_utc
from common.utils import build_bucket_axis, format_decimal_str

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

DEFAULT_TREND_DAYS = 30
DEFAULT_TREND_FIELDS = ("market_value",)
DEFAULT_ACCOUNT_TREND_FIELDS = ("balance_usd",)


def _parse_optional_datetime(value, *, end_of_day: bool = False):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return normalize_datetime_to_utc(value)

    text = str(value).strip()   
    parsed_datetime = parse_datetime(text)
    if parsed_datetime is not None:
        return normalize_datetime_to_utc(parsed_datetime)

    parsed_date = parse_date(text)
    if parsed_date is not None:
        return normalize_datetime_to_utc(
            datetime.combine(parsed_date, time.max if end_of_day else time.min)
        )
    raise ValueError(f"invalid datetime value: {value}")


def _resolve_trend_period(*, start, end) -> tuple[datetime, datetime]:
    resolved_end = _parse_optional_datetime(end, end_of_day=True) or normalize_datetime_to_utc(timezone.now())
    resolved_start = _parse_optional_datetime(start)
    if resolved_start is None:
        resolved_start = resolved_end - timedelta(days=DEFAULT_TREND_DAYS)
    if resolved_start > resolved_end:
        raise ValueError("start cannot be later than end")
    return resolved_start, resolved_end


def _normalize_symbols(symbols: list[str] | None) -> list[str] | None:
    if symbols is None:
        return None
    normalized = []
    seen = set()
    for symbol in symbols:
        value = str(symbol or "").strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _normalize_fields(fields: list[str] | None) -> tuple[str, ...]:
    if fields is None:
        return DEFAULT_TREND_FIELDS

    field_map = {
        "quantity": "quantity",
        "market_price": "market_price",
        "market_value": "market_value_usd",
        "market_value_usd": "market_value_usd",
    }
    normalized = []
    seen = set()
    for field in fields:
        key = field_map.get(str(field or "").strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return tuple(normalized or DEFAULT_TREND_FIELDS)


def _normalize_account_ids(account_ids: list[int] | list[str] | None) -> list[int] | None:
    if account_ids is None:
        return None
    normalized = []
    seen = set()
    for account_id in account_ids:
        value = int(account_id)
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _normalize_account_fields(fields: list[str] | None) -> tuple[str, ...]:
    if fields is None:
        return DEFAULT_ACCOUNT_TREND_FIELDS

    field_map = {
        "balance_native": "balance_native",
        "balance_usd": "balance_usd",
    }
    normalized = []
    seen = set()
    for field in fields:
        key = field_map.get(str(field or "").strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return tuple(normalized or DEFAULT_ACCOUNT_TREND_FIELDS)


def _format_series(rows: list[PositionSnapshot], field_name: str) -> list[dict]:
    series = []
    for row in rows:
        value = getattr(row, field_name)
        if value is None:
            continue
        series.append(
            {
                "date": row.snapshot_time.astimezone(dt_timezone.utc).date().isoformat(),
                "value": format_decimal_str(value),
            }
        )
    return series


def _build_market_value_points(rows: list[PositionSnapshot]) -> list[dict]:
    points = []
    for row in rows:
        if row.market_value_usd is None:
            continue
        points.append(
            {
                "date": row.snapshot_time.astimezone(dt_timezone.utc).date().isoformat(),
                "value": float(row.market_value_usd),
            }
        )
    return points


def _build_balance_points(rows: list[AccountSnapshot]) -> list[dict]:
    points = []
    for row in rows:
        if row.balance_usd is None:
            continue
        points.append(
            {
                "date": row.snapshot_time.astimezone(dt_timezone.utc).date().isoformat(),
                "value": float(row.balance_usd),
            }
        )
    return points


def _build_summary(points: list[dict]) -> tuple[dict, dict, dict, dict]:
    if not points:
        empty_summary = {
            "max_market_value_usd": "0",
            "max_market_value_at": None,
            "min_market_value_usd": "0",
            "min_market_value_at": None,
            "avg_market_value_usd": "0",
            "volatility_pct": "0",
        }
        empty_event = {"pct": "0", "start": None, "end": None}
        return empty_summary, empty_event, empty_event.copy(), empty_event.copy()

    max_point = max(points, key=lambda item: item["value"])
    min_point = min(points, key=lambda item: item["value"])
    avg_value = sum(item["value"] for item in points) / len(points)

    returns = []
    prev_point = None
    for point in points:
        if prev_point is not None and prev_point["value"] > 0:
            pct = (point["value"] - prev_point["value"]) / prev_point["value"]
            returns.append(
                {
                    "pct": pct,
                    "start": prev_point["date"],
                    "end": point["date"],
                }
            )
        prev_point = point

    if returns:
        mean_return = sum(item["pct"] for item in returns) / len(returns)
        variance = sum((item["pct"] - mean_return) ** 2 for item in returns) / len(returns)
        volatility_pct = variance ** 0.5
        max_gain_row = max(returns, key=lambda item: item["pct"])
        max_loss_row = min(returns, key=lambda item: item["pct"])
        max_gain = {
            "pct": f"{max_gain_row['pct']:.4f}",
            "start": max_gain_row["start"],
            "end": max_gain_row["end"],
        }
        max_loss = {
            "pct": f"{max_loss_row['pct']:.4f}",
            "start": max_loss_row["start"],
            "end": max_loss_row["end"],
        }
    else:
        volatility_pct = 0.0
        max_gain = {"pct": "0", "start": None, "end": None}
        max_loss = {"pct": "0", "start": None, "end": None}

    peak_value = None
    peak_date = None
    max_drawdown_pct = 0.0
    max_drawdown_start = None
    max_drawdown_end = None
    for point in points:
        if peak_value is None or point["value"] > peak_value:
            peak_value = point["value"]
            peak_date = point["date"]
        if peak_value and peak_value > 0:
            drawdown_pct = (point["value"] - peak_value) / peak_value
            if drawdown_pct < max_drawdown_pct:
                max_drawdown_pct = drawdown_pct
                max_drawdown_start = peak_date
                max_drawdown_end = point["date"]

    summary = {
        "max_market_value_usd": f"{max_point['value']:.2f}",
        "max_market_value_at": max_point["date"],
        "min_market_value_usd": f"{min_point['value']:.2f}",
        "min_market_value_at": min_point["date"],
        "avg_market_value_usd": f"{avg_value:.2f}",
        "volatility_pct": f"{volatility_pct:.4f}",
    }
    max_drawdown = {
        "pct": f"{max_drawdown_pct:.4f}",
        "start": max_drawdown_start,
        "end": max_drawdown_end,
    }
    return summary, max_drawdown, max_gain, max_loss


def _build_account_summary(points: list[dict]) -> tuple[dict, dict, dict, dict]:
    if not points:
        empty_summary = {
            "start_balance_usd": "0",
            "end_balance_usd": "0",
            "change_amount_usd": "0",
            "change_pct": "0",
            "max_balance_usd": "0",
            "max_balance_at": None,
            "min_balance_usd": "0",
            "min_balance_at": None,
            "avg_balance_usd": "0",
            "volatility_pct": "0",
        }
        empty_event = {"pct": "0", "start": None, "end": None}
        return empty_summary, empty_event, empty_event.copy(), empty_event.copy()

    max_point = max(points, key=lambda item: item["value"])
    min_point = min(points, key=lambda item: item["value"])
    start_point = points[0]
    end_point = points[-1]
    avg_value = sum(item["value"] for item in points) / len(points)
    change_amount = end_point["value"] - start_point["value"]
    change_pct = (change_amount / start_point["value"]) if start_point["value"] > 0 else 0.0

    returns = []
    prev_point = None
    for point in points:
        if prev_point is not None and prev_point["value"] > 0:
            pct = (point["value"] - prev_point["value"]) / prev_point["value"]
            returns.append(
                {
                    "pct": pct,
                    "start": prev_point["date"],
                    "end": point["date"],
                }
            )
        prev_point = point

    if returns:
        mean_return = sum(item["pct"] for item in returns) / len(returns)
        variance = sum((item["pct"] - mean_return) ** 2 for item in returns) / len(returns)
        volatility_pct = variance ** 0.5
        max_gain_row = max(returns, key=lambda item: item["pct"])
        max_loss_row = min(returns, key=lambda item: item["pct"])
        max_gain = {
            "pct": f"{max_gain_row['pct']:.4f}",
            "start": max_gain_row["start"],
            "end": max_gain_row["end"],
        }
        max_loss = {
            "pct": f"{max_loss_row['pct']:.4f}",
            "start": max_loss_row["start"],
            "end": max_loss_row["end"],
        }
    else:
        volatility_pct = 0.0
        max_gain = {"pct": "0", "start": None, "end": None}
        max_loss = {"pct": "0", "start": None, "end": None}

    peak_value = None
    peak_date = None
    max_drawdown_pct = 0.0
    max_drawdown_start = None
    max_drawdown_end = None
    for point in points:
        if peak_value is None or point["value"] > peak_value:
            peak_value = point["value"]
            peak_date = point["date"]
        if peak_value and peak_value > 0:
            drawdown_pct = (point["value"] - peak_value) / peak_value
            if drawdown_pct < max_drawdown_pct:
                max_drawdown_pct = drawdown_pct
                max_drawdown_start = peak_date
                max_drawdown_end = point["date"]

    summary = {
        "start_balance_usd": f"{start_point['value']:.2f}",
        "end_balance_usd": f"{end_point['value']:.2f}",
        "change_amount_usd": f"{change_amount:.2f}",
        "change_pct": f"{change_pct:.4f}",
        "max_balance_usd": f"{max_point['value']:.2f}",
        "max_balance_at": max_point["date"],
        "min_balance_usd": f"{min_point['value']:.2f}",
        "min_balance_at": min_point["date"],
        "avg_balance_usd": f"{avg_value:.2f}",
        "volatility_pct": f"{volatility_pct:.4f}",
    }
    max_drawdown = {
        "pct": f"{max_drawdown_pct:.4f}",
        "start": max_drawdown_start,
        "end": max_drawdown_end,
    }
    return summary, max_drawdown, max_gain, max_loss


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
        series["balance_usd"][idx] = format_decimal_str(row.balance_usd)
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
        series["market_price"][idx] = format_decimal_str(row.market_price) if row.market_price is not None else None
        series["market_value"][idx] = format_decimal_str(row.market_value) if row.market_value is not None else None
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


def get_position_trend(*, user, start=None, end=None, symbols: list[str] | None = None,
                       fields: list[str] | None = None) -> dict:
    start_time, end_time = _resolve_trend_period(start=start, end=end)
    normalized_symbols = _normalize_symbols(symbols)
    requested_fields = _normalize_fields(fields)

    queryset = (
        PositionSnapshot.objects
        .filter(
            account__user=user,
            snapshot_level=SnapshotLevel.D1,
            snapshot_time__gte=start_time,
            snapshot_time__lte=end_time,
        )
        .select_related("instrument")
        .only(
            "instrument_id",
            "instrument__symbol",
            "instrument__short_code",
            "instrument__name",
            "snapshot_time",
            "quantity",
            "market_price",
            "market_value_usd",
        )
        .order_by("instrument_id", "snapshot_time", "id")
    )

    if normalized_symbols is not None:
        queryset = queryset.filter(
            instrument__short_code__in=normalized_symbols
        ) | queryset.filter(
            instrument__symbol__in=normalized_symbols
        )

    grouped_rows: dict[int, list[PositionSnapshot]] = {}
    instrument_meta: dict[int, dict] = {}
    for row in queryset:
        instrument_id = row.instrument_id
        grouped_rows.setdefault(instrument_id, []).append(row)
        instrument_meta[instrument_id] = {
            "symbol": str(getattr(row.instrument, "short_code", "") or getattr(row.instrument, "symbol", "")),
            "name": row.instrument.name,
        }

    items = []
    for instrument_id, rows in grouped_rows.items():
        series = {}
        if "quantity" in requested_fields:
            series["quantity"] = _format_series(rows, "quantity")
        if "market_price" in requested_fields:
            series["market_price"] = _format_series(rows, "market_price")
        if "market_value_usd" in requested_fields:
            series["market_value_usd"] = _format_series(rows, "market_value_usd")

        market_value_points = _build_market_value_points(rows)
        summary, max_drawdown, max_single_period_gain, max_single_period_loss = _build_summary(market_value_points)

        items.append(
            {
                "symbol": instrument_meta[instrument_id]["symbol"],
                "name": instrument_meta[instrument_id]["name"],
                "series": series,
                "summary": summary,
                "max_drawdown": max_drawdown,
                "max_single_period_gain": max_single_period_gain,
                "max_single_period_loss": max_single_period_loss,
            }
        )

    return {
        "base_currency": "USD",
        "analysis_period": {
            "start": start_time.date().isoformat(),
            "end": end_time.date().isoformat(),
        },
        "items": items,
    }


def get_account_trend(*, user, start=None, end=None, account_ids: list[int] | list[str] | None = None,
                      fields: list[str] | None = None) -> dict:
    start_time, end_time = _resolve_trend_period(start=start, end=end)
    normalized_account_ids = _normalize_account_ids(account_ids)
    requested_fields = _normalize_account_fields(fields)

    queryset = (
        AccountSnapshot.objects
        .filter(
            account__user=user,
            snapshot_level=SnapshotLevel.D1,
            snapshot_time__gte=start_time,
            snapshot_time__lte=end_time,
        )
        .select_related("account")
        .only(
            "account_id",
            "account__name",
            "account__type",
            "snapshot_time",
            "account_currency",
            "balance_native",
            "balance_usd",
        )
        .order_by("account_id", "snapshot_time", "id")
    )
    if normalized_account_ids is not None:
        queryset = queryset.filter(account_id__in=normalized_account_ids)

    grouped_rows: dict[int, list[AccountSnapshot]] = {}
    account_meta: dict[int, dict] = {}
    for row in queryset:
        account_id = row.account_id
        grouped_rows.setdefault(account_id, []).append(row)
        account_meta[account_id] = {
            "account_id": str(account_id),
            "name": row.account.name,
            "type": row.account.type,
            "currency": row.account_currency,
        }

    items = []
    for account_id, rows in grouped_rows.items():
        series = {}
        if "balance_native" in requested_fields:
            series["balance_native"] = _format_series(rows, "balance_native")
        if "balance_usd" in requested_fields:
            series["balance_usd"] = _format_series(rows, "balance_usd")

        balance_points = _build_balance_points(rows)
        summary, max_drawdown, max_single_period_gain, max_single_period_loss = _build_account_summary(balance_points)

        items.append(
            {
                "account_id": account_meta[account_id]["account_id"],
                "name": account_meta[account_id]["name"],
                "type": account_meta[account_id]["type"],
                "currency": account_meta[account_id]["currency"],
                "series": series,
                "summary": summary,
                "max_drawdown": max_drawdown,
                "max_single_period_gain": max_single_period_gain,
                "max_single_period_loss": max_single_period_loss,
            }
        )

    return {
        "base_currency": "USD",
        "analysis_period": {
            "start": start_time.date().isoformat(),
            "end": end_time.date().isoformat(),
        },
        "items": items,
    }

