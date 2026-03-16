# Accounts Module / 账户模块

## 中文

- 定位：管理资金账户、手工流水，以及合并在交易模型中的简化转账记录。
- 核心模型：`Accounts`、`Transaction`。
- 关键设计：交易创建时直接回写账户余额；转账不再使用独立 `Transfer` 模型，而是在 `Transaction` 上通过 `transfer_account` 表示转入账户；只有撤销接口会通过冲正流水影响余额，删除接口只删记录、不回滚余额；普通账户按 `user + name + type + currency` 保证唯一；系统投资账户定义为 `type=investment` 且 `name=投资账户`，单用户仅保留一条，由系统首次买入时创建、后续长期保留，不能手工创建或删除。
- 主要接口：`/api/user/accounts/`、`/api/user/transactions/`。
- 依赖关系：依赖 Django 用户体系；被 `investment` 用作现金账户和资金流水落账；被 `snapshot` 作为账户快照源。

### 交易接口说明

- `POST /api/user/transactions/`：创建一条交易记录。
  - 手工记账：传 `account + counterparty + amount + category_name`
  - 转账：传 `account + transfer_account + amount`，系统会自动把 `source` 记为 `transfer`，并同步更新双方账户余额
- `GET /api/user/transactions/`：返回当前用户全部交易记录；前端可按真实字段查询，例如：
  - `?source=manual`
  - `?source=investment`
  - `?source=transfer`
  - `?reversed_at__isnull=false`
- `POST /api/user/transactions/{id}/reverse/`：撤销指定手工交易；系统会生成一条冲正流水，并给原交易写入 `reversed_at`。
- `DELETE /api/user/transactions/{id}/`：删除允许删除的原交易，返回 `204 No Content`。
- `DELETE /api/user/transactions/delete/?source=manual|investment|transfer|reversal`：按 `source` 批量删除交易记录。

### 批量删除接口

请求示例：

```http
DELETE /api/user/transactions/delete/?source=investment
```

支持的 `source`：

- `manual`
- `investment`
- `transfer`
- `reversal`

成功响应示例：

```json
{
  "source": "investment",
  "deleted_count": 3
}
```

### 删除规则

- 单条删除和批量删除都允许删除各类交易记录：`manual / investment / transfer / reversal`。
- 删除接口只删除记录，不回滚任何账户余额。
- 删除手工、投资、转账原交易时：如果该交易关联了一条冲正流水，会同时删除那条冲正流水。
- 删除 `reversal` 记录时：只删除冲正流水本身，不额外调整原交易余额状态。
- 只有 `POST /api/user/transactions/{id}/reverse/` 会通过冲正流水影响余额。

### 转账请求示例

```json
POST /api/user/transactions/
{
  "account": 12,
  "transfer_account": 15,
  "amount": "120.00",
  "remark": "账户互转"
}
```

成功响应示例：

```json
{
  "id": 88,
  "counterparty": "USD Savings",
  "amount": "120.00",
  "category_name": "转账",
  "remark": "账户互转",
  "currency": "USD",
  "account": 12,
  "account_name": "USD Cash",
  "transfer_account": 15,
  "transfer_account_name": "USD Savings",
  "balance_after": "380.00",
  "user": 7,
  "source": "transfer"
}
```

## English

- Role: owns cash accounts, manual transactions, and simplified transfer records merged into the transaction model.
- Core models: `Accounts`, `Transaction`.
- Key design: account balances are updated on transaction creation; transfers no longer use a separate `Transfer` model and instead store the destination account in `Transaction.transfer_account`; only the reverse endpoint changes balances through reversal rows; delete endpoints only remove rows and never roll balances back; regular accounts are unique by `user + name + type + currency`; the system investment account is defined as `type=investment` and `name=投资账户`, is singleton per user, is created by the first buy, remains long-lived, and cannot be created or deleted manually.
- Main APIs: `/api/user/accounts/`, `/api/user/transactions/`.
- Dependencies: built on Django users; used by `investment` for cash settlement; used by `snapshot` as the account snapshot source.

### Transaction API Notes

- `POST /api/user/transactions/`: create a transaction row.
  - Manual bookkeeping: send `account + counterparty + amount + category_name`
  - Transfer: send `account + transfer_account + amount`; the API marks the row as `source=transfer` and updates both balances
- `GET /api/user/transactions/`: return all transactions for the current user; the frontend can filter by real fields such as `source=manual`, `source=investment`, `source=transfer`, or `reversed_at__isnull=false`.
- `POST /api/user/transactions/{id}/reverse/`: reverse a manual transaction by generating a reversal row and stamping `reversed_at` on the original row.
- `DELETE /api/user/transactions/{id}/`: delete an allowed original transaction and return `204 No Content`.
- `DELETE /api/user/transactions/delete/?source=manual|investment|transfer|reversal`: batch delete transaction rows by `source`.

### Delete Rules

- All transaction sources are deletable through the delete endpoints: `manual`, `investment`, `transfer`, and `reversal`.
- Delete endpoints only remove rows; they never roll balances back.
- Deleting an original row also deletes its linked reversal row when present.
- Only `POST /api/user/transactions/{id}/reverse/` changes balances.
