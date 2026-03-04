# Snapshot 查询接口文档（列表矩阵版）

## 1. 目标

本版返回结构按你的要求改为“多个列表”，不再逐条重复返回这些公共字段：

1. `snapshot_level`
2. `currency`（在系列级保留一次）
3. `snapshot_time`
4. `created_at`

返回改为：`meta + series[]`  
其中每个 `series` 内是多个等长数组（按时间桶索引对齐）。

---

## 2. 时间与层级规则

支持层级：

1. `M15`
2. `H4`
3. `D1`
4. `MON1`

时间规则：

1. `M15` 查询跨度最大 `1 天`（强校验）。
2. 所有时间按 UTC 对齐到桶边界。
3. 返回不再逐点给 `snapshot_time`，由 `meta.axis_start_time + interval` 推导。

---

## 3. 接口：账户快照查询

路径：

`GET /api/snapshot/accounts/`

参数：

1. `level`（必填）
2. `start_time`（必填）
3. `end_time`（必填）
4. `account_id`（选填，不传表示返回当前用户多个账户）
5. `limit`（选填，默认 `2000`，最大 `10000`）

---

## 4. 接口：持仓快照查询

路径：

`GET /api/snapshot/positions/`

参数：

1. `level`（必填）
2. `start_time`（必填）
3. `end_time`（必填）
4. `account_id`（选填）
5. `instrument_id`（选填）
6. `limit`（选填，默认 `2000`，最大 `10000`）

说明：

1. 可查单个持仓（`account_id + instrument_id`）。
2. 也可查多个持仓（例如只传 `account_id` 或都不传）。
3. 仅返回当前登录用户拥有账户的数据。

---

## 5. 返回结构（统一）

```json
{
  "meta": {
    "level": "M15",
    "start_time": "2026-03-03T00:00:00+00:00",
    "end_time": "2026-03-03T23:59:59+00:00",
    "axis_start_time": "2026-03-03T00:00:00+00:00",
    "axis_end_time": "2026-03-03T23:45:00+00:00",
    "interval_unit": "minute",
    "interval_seconds": 900,
    "point_count": 96
  },
  "series_count": 2,
  "series": []
}
```

字段解释：

1. `meta.axis_start_time`：时间轴起点。
2. `meta.interval_seconds`：固定桶间隔（`MON1` 为 `null`）。
3. `meta.point_count`：每个数组长度。
4. `series[]`：一个账户或一个持仓对应一个系列对象。

---

## 6. 账户查询 series 示例

```json
{
  "account_id": 12,
  "account_name": "现金账户",
  "account_currency": "CNY",
  "balance_usd": ["405.11", "404.47", null, "..."],
  "data_status": ["ok", "ok", null, "..."]
}
```

---

## 7. 持仓查询 series 示例

```json
{
  "account_id": 8,
  "account_name": "投资账户",
  "instrument_id": 1001,
  "symbol": "AAPL",
  "currency": "USD",
  "market_price": ["181.23", "181.55", null, "..."],
  "market_value": ["1812.3", "1815.5", null, "..."],
  "data_status": ["ok", "ok", null, "..."]
}
```

字段裁剪说明（减轻查询负载）：

1. 账户接口不再返回 `balance_native`。
2. 账户接口不再返回 `fx_rate_to_usd`。
3. 持仓接口不再返回 `market_value_usd`、`quantity`、`avg_cost`、`fx_rate_to_usd`、`realized_pnl`。

---

## 8. 前端还原时间轴方式

前端按数组下标 `i` 生成时间点：

1. `ts(i) = axis_start_time + i * interval_seconds`（`M15/H4/D1`）
2. `MON1`：按月加一（`axis_start_time` 为每月 1 日 00:00 UTC）

---

## 9. 错误说明

常见错误：

1. `start_time > end_time`
2. `M15` 时间跨度超过 1 天
3. 参数类型不合法（时间格式、整数格式等）

---

## 10. 代码位置

1. 路由：`snapshot/urls.py`
2. 参数校验：`snapshot/serializers.py`
3. 视图：`snapshot/views.py`
