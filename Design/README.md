# Mango Project Design Package

## 1. 文档目标

本目录从设计架构视角，对当前 `mango_project` 的后端实现做一次规范化沉淀，目标不是重复接口文档，而是回答下面几类问题：

- 系统由哪些模块组成，边界怎么划分
- 每个 app 负责什么职责，内部是如何分层的
- 核心数据模型为什么这样设计，关键约束是什么
- 模块之间有哪些依赖、哪些耦合是刻意设计、哪些是当前实现遗留
- 典型业务流程如何穿过多 app 协同完成

这套文档按“现状设计”编写，内容以代码真实实现为准。

## 2. 阅读顺序

建议按下面顺序阅读：

1. [00_system_architecture.md](./00_system_architecture.md)
2. [01_shared_foundation.md](./01_shared_foundation.md)
3. [02_login_app_design.md](./02_login_app_design.md)
4. [03_accounts_app_design.md](./03_accounts_app_design.md)
5. [04_market_app_design.md](./04_market_app_design.md)
6. [05_investment_app_design.md](./05_investment_app_design.md)
7. [06_snapshot_app_design.md](./06_snapshot_app_design.md)

## 3. 文档范围

覆盖内容：

- `mango_project` 运行时架构、路由、Celery 调度、缓存与外部依赖
- `login / accounts / market / investment / snapshot / shared`
- 每个模块的设计思路、数据模型设计、依赖关系、核心业务流程

不覆盖内容：

- 部署细节和运维脚本的逐行说明
- 前端页面交互
- 压测执行细节
- 第三方库内部实现

## 4. 当前项目的设计结论摘要

当前后端可以概括成 5 个业务域加 1 个基础设施层：

- `login`: 认证、注册、找回密码、用户名修改
- `accounts`: 账户主数据、手工流水、转账流水、资金账本
- `market`: 标的主数据、用户订阅、自选、行情快照、指数与汇率缓存
- `investment`: 买卖交易、持仓、系统投资账户估值
- `snapshot`: 账户/持仓的时序快照采集、聚合、查询
- `shared`: 异常、约束、时间桶、Decimal/代码/时间处理等基础能力

## 5. 需要特别注意的现状耦合

这几个耦合点在阅读后续设计文档时要重点关注：

- `investment` 依赖 `accounts` 记资金流水，同时又反向驱动 `accounts` 中的“投资账户”
- `market` 的外部行情抓取实际落在 `accounts.services.quote_fetcher`
- `accounts.tasks` 里定义了市场同步任务入口，任务实现却在 `market.services`
- `snapshot` 是最上游的汇总层，读取 `accounts + investment + market` 三个域的结果

这说明当前项目已经形成了清晰的业务域，但还没有完全做到“依赖单向流动”。后续重构时，优先处理的不是表结构，而是跨 app 的服务边界。

## 6. 术语约定

- “投资账户”指 `accounts.Accounts` 中由系统自动维护的特殊账户，不允许手工创建
- “订阅”指 `market.UserInstrumentSubscription`
- “自选来源”指 `from_watchlist`
- “持仓来源”指 `from_position`
- “行情快照”指 Redis 中的最新价缓存，不是 `snapshot` app 的历史快照表
- “历史快照”指 `snapshot` app 落库后的时序数据

## 7. 说明

你原始需求中的“删除该模块涉及的业务流程”在上下文里语义不通，本次我按“梳理/列出该模块涉及的业务流程”处理，并在各设计文档中保留了“核心业务流程”章节。
