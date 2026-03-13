# Investment Module / 投资模块

## 中文

- 定位：管理买卖交易、持仓汇总、历史记录和已实现盈亏。
- 核心模型：`InvestmentRecord`、`Position`。
- 关键设计：买卖落地时会同步生成或关联 `accounts.Transaction` 作为现金流水；持仓按 `user + instrument` 唯一聚合；卖出必须生成已实现盈亏；系统投资账户在首次买入时自动创建，之后长期保留，无持仓时余额归零。
- 主要接口：`/api/investment/buy/`、`/api/investment/sell/`、`/api/investment/positions/`、`/api/investment/history/`。
- 依赖关系：依赖 `market.Instrument` 作为交易标的，依赖 `accounts` 进行现金结算，并为 `snapshot` 提供持仓基础数据。

## English

- Role: manages buy/sell records, position aggregation, trade history, and realized PnL.
- Core models: `InvestmentRecord`, `Position`.
- Key design: buy/sell execution also creates or links `accounts.Transaction` cash entries; positions are unique per `user + instrument`; sell records must carry realized PnL; the system investment account is created on the first buy, persists afterwards, and falls back to zero balance when no positions remain.
- Main APIs: `/api/investment/buy/`, `/api/investment/sell/`, `/api/investment/positions/`, `/api/investment/history/`.
- Dependencies: depends on `market.Instrument` as tradable assets, on `accounts` for cash settlement, and feeds `snapshot` with position data.
