# Market Data 行情拉取设计（V2.1 - Calendar Guard 规范版）

## 1. 目标

基于现有项目逻辑，重构一套更规范的行情拉取方案：

1. 使用 `pandas_market_calendars` 离线生成本地 `CSV` 交易日历。
2. Celery 任务启动后，先做“日历守卫判定”，再决定是否拉取。
3. 保留现有 Redis 快照、缺口修复、watchlist/position 订阅合并逻辑。
4. 让调度频率与交易时段规则可配置、可解释、可审计。

---

## 2. 当前问题（现状）

现有代码的主要问题：

1. 交易时段判断散落在 `should_fetch_market`，只基于工作日 + 固定时段，不识别节假日/半日市。
2. 调度统一 `*/10`，无法精确覆盖 `09:25`、`09:20`、`16:10` 这类单点需求。
3. 行情“该不该拉”与“何时拉”缺少统一决策层，导致行为不透明。

---

## 3. 设计原则

1. **先判定后请求**：任何外部行情请求前必须通过 Calendar Guard。
2. **日历本地化**：运行时只读本地 CSV，不在线查询交易日历。
3. **单任务兼容**：优先复用现有 `task_pull_watchlist_quotes -> sync_watchlist_snapshot` 主链路。
4. **分市场策略**：US/CN/HK 按交易日历，FX/CRYPTO 使用专属规则。
5. **可回退**：当日历文件缺失时，允许降级策略但必须打 `ERROR/WARN` 日志。

---

## 4. 总体架构

## 4.1 离线层（生成日历 CSV）

新增管理命令（建议）：

`python manage.py build_market_calendar_csv --start 2026-01-01 --end 2027-12-31 --markets US CN HK`

职责：

1. 调用 `pandas_market_calendars` 拉取市场交易日程。
2. 标准化为统一字段后写入 CSV。
3. 每次全量覆盖或按年份增量生成。

## 4.2 在线层（任务执行判定）

`task_pull_watchlist_quotes` 执行流程改为：

1. 读取订阅市场集合（来自 `UserInstrumentSubscription`）。
2. 读取本地 CSV（可启动时预加载 + 内存缓存）。
3. 调用 `CalendarGuard` 判定本次“应拉市场列表 + 拉取模式”。
4. 仅对 `due_markets` 执行拉取。
5. 复用现有 `sync_watchlist_snapshot` 的合并、修复、回退、写 Redis 逻辑。

---

## 5. CSV 数据契约

## 5.1 文件组织（建议）

目录：

`data/market_calendars/`

文件：

1. `US_2026.csv`
2. `CN_2026.csv`
3. `HK_2026.csv`

## 5.2 字段定义（统一）

每行代表“某市场某交易日”：

1. `market`：`US/CN/HK`
2. `trade_date`：本地日期（`YYYY-MM-DD`）
3. `timezone`：如 `America/New_York`
4. `is_open`：`1/0`
5. `market_open_local`：本地开盘时间（ISO）
6. `market_close_local`：本地收盘时间（ISO）
7. `market_open_utc`：UTC 开盘时间（ISO）
8. `market_close_utc`：UTC 收盘时间（ISO）
9. `is_half_day`：`1/0`
10. `session_tag`：可选，标记特殊会话
11. `source`：`pandas_market_calendars`
12. `generated_at_utc`

说明：

1. 盘前盘后规则由策略层定义，不强耦合在 CSV。
2. 半日市通过 `market_close_*` 生效，避免硬编码节日。

---

## 6. 拉取策略（Policy）

## 6.1 建议调度粒度

Beat 改为 `*/5 * * * *`（每 5 分钟触发一次）。  
原因：兼容 09:20、09:25、16:10 单点策略，且改造成本低（仍单任务）。

## 6.2 各市场时段策略（按你原规范）

US（`America/New_York`）：

1. 盘前 `04:00-09:30`：每 60 分钟
2. 盘中 `09:30-16:00`：每 10 分钟
3. 盘后 `16:00-20:00`：每 60 分钟
4. 超过当日 `market_close_local`（半日市）后，盘中任务必须拦截

CN（`Asia/Shanghai`）：

1. 盘前：`09:25` 单次
2. 盘中：`09:30-11:30`、`13:00-15:00` 每 10 分钟
3. 午休：`11:30-13:00` 静默
4. 盘后：`15:30` 单次

HK（`Asia/Shanghai`）：

1. 盘前：`09:20` 单次
2. 盘中：`09:30-12:00`、`13:00-16:00` 每 10 分钟
3. 午休：`12:00-13:00` 静默
4. 盘后：`16:10` 单次

FX：

1. 非 CSV 市场，使用 24x5（UTC 工作日）策略
2. 建议固定每 30 或 60 分钟

CRYPTO：

1. 非 CSV 市场，24x7
2. 建议每 10 分钟（与主行情一致）

---

## 7. Calendar Guard 判定算法

输入：

1. `market`
2. `now_utc`
3. 当日交易日历行（CSV）
4. `last_success_pull_at`（按 market 维度）
5. 策略配置（频率/单点）

输出：

1. `should_pull: bool`
2. `reason`
3. `session_type`（`pre/regular/post/special`）

判定顺序：

1. 若市场无订阅标的，返回 `False(no_subscription)`
2. 若 `market in {US,CN,HK}`：
   - 当日 `is_open=0` -> `False(non_trading_day)`
   - 当前时间不在任一策略窗口 -> `False(outside_session)`
   - 命中窗口但未到频率/单点 -> `False(not_due_yet)`
   - 若盘中且 `now_local > market_close_local` -> `False(after_close_half_day_guard)`
3. 若 `market in {FX,CRYPTO}`：按专用策略判定
4. 满足条件 -> `True(due)`

---

## 8. 与现有代码的集成方案（最小改动）

## 8.1 新增模块（建议）

`market/services/calendar_guard_service.py`

职责：

1. 读取并缓存 CSV
2. 计算某市场当前 session 与 due 状态
3. 返回 `due_markets`

## 8.2 改造点

1. `accounts/services/quote_fetcher.py`
   - `should_fetch_market` 降级为 fallback，不再主判定
2. `market/services/snapshot_sync_service.py`
   - 拉取前加入 Calendar Guard 过滤
3. `accounts/tasks.py`
   - 保持入口不变（兼容当前队列与任务名）
4. `mango_project/settings.py`
   - `pull-watchlist-quotes-every-10-minutes` 改为 `*/5`

## 8.3 保持不变

1. `WATCHLIST_QUOTES_KEY` 结构不改
2. 缺口修复与 fallback 合并逻辑不改
3. orphan 行情复用机制不改
4. API 入参与返回结构不改

---

## 9. 配置项建议

新增配置（示例）：

1. `MARKET_CALENDAR_DIR=data/market_calendars`
2. `MARKET_CALENDAR_REQUIRED=True`
3. `MARKET_PULL_POLICY_VERSION=v2_1`
4. `MARKET_PULL_FALLBACK_ON_MISSING_CALENDAR=False`

---

## 10. 监控与日志

## 10.1 日志事件

1. `calendar.guard.skip`（包含 market/reason/session/now_local）
2. `calendar.guard.due`（包含 market/session/policy_slot）
3. `calendar.guard.file_missing`
4. `calendar.guard.parse_error`
5. `market.pull.executed`（市场、条数、耗时）

## 10.2 指标建议

1. 每市场：`due_count/skip_count/success_count/fail_count`
2. `non_trading_day_skip_count`
3. `after_close_half_day_guard_count`
4. 日历文件版本与覆盖范围（最小/最大日期）

---

## 11. 验收标准

1. US/CN/HK 在节假日不发起外部行情请求。
2. US 半日市收盘后不再执行盘中抓取。
3. CN/HK 午休时段完全静默。
4. 单点策略（CN 09:25、CN 15:30、HK 09:20、HK 16:10）按预期触发。
5. 现有 API 与 Redis 输出结构保持兼容。
6. investment/snapshot 读取逻辑无需改动即可继续运行。

---

## 12. 实施计划（建议）

1. 第一步：新增 `build_market_calendar_csv` 命令并产出 CSV。
2. 第二步：引入 `calendar_guard_service`，先以日志模式（只判定不拦截）运行 3-5 天。
3. 第三步：切换为强拦截模式（guard fail 则不拉取）。
4. 第四步：将 Beat 从 `*/10` 调整为 `*/5`，启用单点策略。
5. 第五步：补齐单元测试与集成测试（节假日、半日市、午休、单点触发）。

---

## 13. 结论

该方案在不推翻现有主链路的前提下，把“行情是否拉取”的核心决策收敛到 `Calendar Guard`：  
既兼容现有 Redis/快照/投资模块，又能严格落实你在 `market_data` 文档里的交易时段规范与日历约束。

