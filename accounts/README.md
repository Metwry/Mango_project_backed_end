# Accounts Module / 账户模块

## 中文

- 定位：管理资金账户、手工流水、账户间转账，以及基于撤销而非硬删除的资金变更。
- 核心模型：`Accounts`、`Transaction`、`Transfer`。
- 关键设计：交易创建时直接回写账户余额；交易记录禁止物理删除，删除动作通过撤销流水完成；投资账户名称存在单用户唯一约束。
- 主要接口：`/api/user/accounts/`、`/api/user/transactions/`、`/api/user/transfers/`。
- 依赖关系：依赖 Django 用户体系；被 `investment` 用作现金账户和资金流水落账；被 `snapshot` 作为账户快照源。

## English

- Role: owns cash accounts, manual transactions, internal transfers, and reversal-based bookkeeping.
- Core models: `Accounts`, `Transaction`, `Transfer`.
- Key design: account balances are updated on transaction creation; records are reversed instead of hard-deleted; one special investment account name is constrained per user.
- Main APIs: `/api/user/accounts/`, `/api/user/transactions/`, `/api/user/transfers/`.
- Dependencies: built on Django users; used by `investment` for cash settlement; used by `snapshot` as the account snapshot source.
