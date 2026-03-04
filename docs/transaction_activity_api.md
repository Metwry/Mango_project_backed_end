# 交易活动接口文档（查询与删除）

## 1. 通用约定
- Base URL: `/api`
- 鉴权方式: `Authorization: Bearer <JWT_ACCESS_TOKEN>`
- 时间格式: ISO 8601（建议 UTC），示例 `2026-03-04T10:30:00Z`
- Decimal 字段（金额/数量/价格）均返回 `string`

## 2. 活动记录查询

### 2.1 接口定义
- Method: `GET`
- URL: `/api/user/transactions/`
- 作用: 按活动类型查询当前用户交易记录（分页）

### 2.2 活动类型参数
前端通过 `activity_type` 区分三类数据：

| `activity_type` | 含义 | 查询规则 |
|---|---|---|
| `manual`（默认） | 正常手动交易记录 | `source=manual` 且 `reversed_at is null` |
| `investment` | 投资交易记录 | `source=investment` 且 `reversed_at is null` |
| `reversed` | 已撤销交易记录 | `reversed_at is not null`（仅原交易，不含冲正流水） |

说明：
- 列表固定排除冲正流水记录本身（`reversal_of != null`）。
- `manual` 模式不会返回已撤销记录。

### 2.3 Query 参数
| 参数 | 类型 | 必填 | 默认值 | 约束/说明 |
|---|---|---|---|---|
| `activity_type` | string | 否 | `manual` | `manual` / `investment` / `reversed` |
| `page` | int | 否 | `1` | 页码 |
| `page_size` | int | 否 | `10` | 每页条数，最大 `200` |
| `account_id` | int | 否 | - | 按账户 ID 精确过滤 |
| `account_name` | string | 否 | - | 账户名称模糊匹配（icontains） |
| `counterparty` | string | 否 | - | 交易对象模糊匹配 |
| `category` | string | 否 | - | 分类模糊匹配（字段 `category_name`） |
| `currency` | string | 否 | - | 币种精确匹配，如 `CNY`/`USD` |
| `start` | datetime | 否 | - | `add_date >= start` |
| `end` | datetime | 否 | - | `add_date <= end` |
| `search` | string | 否 | - | 搜索 `counterparty`、`category_name` |
| `ordering` | string | 否 | `-add_date,-id` | 可选：`amount`/`created_at`/`add_date`，倒序前缀 `-` |

### 2.4 成功响应（200）
```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 101,
      "counterparty": "Apple Inc.",
      "amount": "-1000.00",
      "category_name": "买入",
      "currency": "USD",
      "account": 3,
      "account_name": "美股账户",
      "balance_after": "9000.00",
      "user": 1,
      "add_date": "2026-03-04T09:30:00Z",
      "created_at": "2026-03-04T09:30:01Z",
      "reversal_of": null,
      "reversed_at": null,
      "source": "investment"
    }
  ]
}
```

### 2.5 字段说明（`results[]`）
| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 交易 ID |
| `counterparty` | string | 交易对象 |
| `amount` | string | 交易金额（正负表示流入流出） |
| `category_name` | string | 分类名称 |
| `currency` | string | 币种 |
| `account` | int | 账户 ID |
| `account_name` | string | 账户名称 |
| `balance_after` | string | 记账后余额 |
| `user` | int | 用户 ID |
| `add_date` | datetime | 业务时间 |
| `created_at` | datetime | 记录创建时间 |
| `reversal_of` | int/null | 若为冲正流水则指向原交易 ID（列表中通常为 `null`） |
| `reversed_at` | datetime/null | 原交易被撤销时间 |
| `source` | string | 交易来源：`manual` / `investment` / `reversal` |

## 3. 删除接口

### 3.1 删除单条（兼容旧调用）
- Method: `DELETE`
- URL: `/api/user/transactions/{transaction_id}/`
- 作用: 删除一条原交易（若该交易已撤销，会连同冲正流水一起删除）

成功响应（200）示例：
```json
{
  "mode": "single",
  "activity_type": "manual",
  "visible_deleted": 1,
  "transaction_rows_deleted": 1
}
```

### 3.2 统一删除入口（参数决定单删或整类删除）
- Method: `POST`
- URL: `/api/user/transactions/delete/`
- 作用: 前端通过参数决定删除单条还是删除某一类活动记录全部

请求体参数：
| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `mode` | string | 是 | `single` 或 `activity` |
| `transaction_id` | int | 条件必填 | 当 `mode=single` 时必填 |
| `activity_type` | string | 条件必填 | 当 `mode=activity` 时必填，值为 `manual` / `investment` / `reversed` |

`mode=single` 请求示例：
```json
{
  "mode": "single",
  "transaction_id": 101
}
```

`mode=activity` 请求示例：
```json
{
  "mode": "activity",
  "activity_type": "investment"
}
```

成功响应（200）示例：
```json
{
  "mode": "activity",
  "activity_type": "investment",
  "visible_deleted": 12,
  "transaction_rows_deleted": 12
}
```

返回字段说明：
| 字段 | 类型 | 说明 |
|---|---|---|
| `mode` | string | 本次删除模式 |
| `activity_type` | string | 本次删除对应活动类型 |
| `visible_deleted` | int | 删除的“可见活动记录”数量（列表可见记录数） |
| `transaction_rows_deleted` | int | 实际删除的 transaction 行数（已撤销记录可能包含冲正流水，行数可能大于可见数） |

## 4. 错误响应
- `401 Unauthorized`: 未登录或 Token 无效
- `400 Bad Request`: 参数不合法
- `404 Not Found`: 单删时交易不存在或无权限

示例：
```json
{
  "activity_type": [
    "仅支持 manual / investment / reversed"
  ]
}
```

## 5. 前端调用示例
- 查询正常手动交易：`GET /api/user/transactions/?activity_type=manual`
- 查询投资交易：`GET /api/user/transactions/?activity_type=investment`
- 查询已撤销交易：`GET /api/user/transactions/?activity_type=reversed`
- 删除单条（统一入口）：`POST /api/user/transactions/delete/` + `{"mode":"single","transaction_id":123}`
- 删除某一类全部：`POST /api/user/transactions/delete/` + `{"mode":"activity","activity_type":"manual"}`
