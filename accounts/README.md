# Accounts Module / 账户模块

## 中文

- 定位：管理资金账户、手工流水、账户间转账，以及基于撤销而非硬删除的资金变更。
- 核心模型：`Accounts`、`Transaction`、`Transfer`。
- 关键设计：交易创建时直接回写账户余额；交易记录禁止物理删除，删除动作通过撤销流水完成；普通账户按 `user + name + type + currency` 保证唯一；系统投资账户定义为 `type=investment` 且 `name=投资账户`，单用户仅保留一条，由系统首次买入时创建、后续长期保留，不能手工创建或删除。
- 主要接口：`/api/user/accounts/`、`/api/user/transactions/`、`/api/user/transfers/`。
- 依赖关系：依赖 Django 用户体系；被 `investment` 用作现金账户和资金流水落账；被 `snapshot` 作为账户快照源。

## English

- Role: owns cash accounts, manual transactions, internal transfers, and reversal-based bookkeeping.
- Core models: `Accounts`, `Transaction`, `Transfer`.
- Key design: account balances are updated on transaction creation; records are reversed instead of hard-deleted; regular accounts are unique by `user + name + type + currency`; the system investment account is defined as `type=investment` and `name=投资账户`, is singleton per user, is created by the first buy, remains long-lived, and cannot be created or deleted manually.
- Main APIs: `/api/user/accounts/`, `/api/user/transactions/`, `/api/user/transfers/`.
- Dependencies: built on Django users; used by `investment` for cash settlement; used by `snapshot` as the account snapshot source.
