# Market Module / 市场模块

## 中文

- 定位：管理交易品种主数据、行情查询、自选订阅、汇率和指数快照。
- 核心模型：`Instrument`、`UserInstrumentSubscription`。
- 关键设计：搜索、行情批量查询和自选订阅共用品种主数据；日历文件决定是否允许执行市场同步；汇率和指数服务与行情服务解耦。
- 主要接口：`/api/user/markets/`、`/api/user/markets/indices/`、`/api/user/markets/fx-rates/`、`/api/user/markets/search/`、`/api/user/markets/quotes/latest/`、`/api/user/markets/watchlist/`。
- 依赖关系：依赖 `shared` 工具和 `data/market_calendars`，被 `investment` 和 `snapshot` 复用。

## English

- Role: manages instrument master data, market data lookup, watchlist subscriptions, FX rates, and market-index snapshots.
- Core models: `Instrument`, `UserInstrumentSubscription`.
- Key design: search, quote batch lookup, and watchlists share the same instrument master data; calendar files gate market synchronization; FX/index services are decoupled from quote lookup.
- Main APIs: `/api/user/markets/`, `/api/user/markets/indices/`, `/api/user/markets/fx-rates/`, `/api/user/markets/search/`, `/api/user/markets/quotes/latest/`, `/api/user/markets/watchlist/`.
- Dependencies: depends on `shared` helpers and `data/market_calendars`, and is reused by `investment` and `snapshot`.
