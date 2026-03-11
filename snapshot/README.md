# Snapshot Module / 快照模块

## 中文

- 定位：负责账户和持仓的周期性快照采集、聚合、清理和查询。
- 核心模型：`AccountSnapshot`、`PositionSnapshot`。
- 关键设计：快照分为 `M15`、`H4`、`D1`、`MON1` 四个层级；账户快照和持仓快照都保留原币值与美元口径；数据状态显式标记行情或汇率缺失。
- 主要接口：`/api/snapshot/accounts/`、`/api/snapshot/positions/`。
- 依赖关系：依赖 `accounts`、`investment`、`market` 提供原始数据，并通过 Celery 定时任务持续生成。

## English

- Role: owns periodic capture, aggregation, cleanup, and querying of account and position snapshots.
- Core models: `AccountSnapshot`, `PositionSnapshot`.
- Key design: snapshots are stored at `M15`, `H4`, `D1`, and `MON1` levels; both account and position snapshots keep native-currency and USD values; data status explicitly marks missing quote or FX input.
- Main APIs: `/api/snapshot/accounts/`, `/api/snapshot/positions/`.
- Dependencies: depends on `accounts`, `investment`, and `market` as data sources, and is continuously populated by Celery tasks.
