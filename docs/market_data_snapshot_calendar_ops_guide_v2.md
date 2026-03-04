# Market Data + Snapshot 维护指南（V2）

## 1. 文档目的

本文件用于长期维护当前项目的三条核心链路：

1. 行情拉取链路（`market` + `accounts`）
2. 交易日历 CSV 链路（`pandas_market_calendars`）
3. 快照采集/聚合/清理链路（`snapshot`）

文档以当前代码行为为准，重点覆盖函数职责、数据契约、启动命令和故障排查。

---

## 2. 总体架构

## 2.1 主流程（行情）

1. Celery Beat 每 5 分钟投递 `accounts.tasks.task_pull_watchlist_quotes`
2. 任务进入 `market.services.snapshot_sync_service.sync_watchlist_snapshot`
3. 从订阅关系汇总市场集合（`UserInstrumentSubscription`）
4. `Calendar Guard` 根据 CSV 和策略判定 `due_markets`
5. 若有 `due_markets`，只拉这些市场行情
6. 若无 `due_markets` 但 Redis 冷启动/缺口修复，触发一次强制初始化拉取
7. 合并新行情 + 旧行情回退 + 空值占位，写入 Redis 快照
8. 按 4 小时规则刷新 USD 汇率快照

## 2.2 主流程（快照）

1. `snapshot.tasks.task_capture_m15_snapshots` 每 15 分钟采集一次
2. 从 Redis 行情与汇率读取价格，生成 `AccountSnapshot` 和 `PositionSnapshot`
3. H4/D1/MON1 由聚合任务从低层级快照选“窗口内最后点”聚合
4. 清理任务按保留策略删除过期数据（M15 1天、H4 30天、D1 90天）

---

## 3. 模块与函数职责

## 3.1 日历守卫（`market/services/calendar_guard_service.py`）

核心对象：

1. `CalendarDay`：交易日行模型（`trade_date/open/close/is_half_day`）
2. `GuardDecision`：判定结果（`should_pull/reason/session`）

核心函数：

1. `_load_market_calendar(market)`
   - 读取 `MARKET_CALENDAR_DIR` 下 `US_YYYY.csv/CN_YYYY.csv/HK_YYYY.csv`
   - 使用内存缓存，文件变更自动失效
2. `_last_market_pull_utc(market)`
   - 从 `watchlist:quotes:market:{market}` 取上次真实拉取时间
   - 优先 `pulled_at`，老数据兼容回退 `updated_at`
3. `_evaluate_calendar_market(market, now_utc)`
   - 对 US/CN/HK 执行时段策略（盘前/盘中/盘后/单点）
4. `_evaluate_always_open_market(market, now_utc)`
   - 对 FX/CRYPTO 执行 24x5/24x7 频率策略
5. `resolve_due_markets(markets, now_utc=None)`
   - 返回 `(due_markets, decisions)`

## 3.2 行情同步（`market/services/snapshot_sync_service.py`）

核心函数：

1. `_subscription_meta_by_market()`
   - 汇总订阅标的元数据（code/name/logo）
2. `_merge_snapshot_with_fallback(previous_data, latest_quotes, watchlist_meta)`
   - 新数据优先，旧数据回退，缺失填 null row
3. `sync_watchlist_snapshot()`
   - 总入口
   - 先跑 guard 判定，再按 `due_markets` 拉取
   - 冷启动/缺口修复会 `force_init_pull`
   - 写 Redis 主快照与分市场快照
   - 维护 `updated_at` 与 `pulled_at` 区分

## 3.3 实际拉取（`accounts/services/quote_fetcher.py`）

核心函数：

1. `pull_watchlist_quotes(now_utc=None, force_fetch_all_markets=False, allowed_markets=None)`
   - 批量拉取入口
   - `allowed_markets` 由 guard 传入，控制只拉哪些市场
2. `fetch_stocks_sina(...)`
   - US/CN/HK 股票行情
3. `fetch_crypto_quotes_binance(...)`
   - CRYPTO 行情
4. `fetch_fx_quotes_with_fallback(...)`
   - FX 主接口新浪，失败降级 yfinance
5. `pull_usd_exchange_rates(seed_rows=None)`
   - 维护 USD 视角主流货币汇率

## 3.4 CSV 生成（`market/management/commands/build_market_calendar_csv.py`）

核心函数：

1. `_load_calendar(calendar_names)`
   - 加载 `pandas_market_calendars` 对应交易所日历
2. `Command.handle(...)`
   - 按 `--start/--end/--markets` 生成分年 CSV 文件

## 3.5 快照服务（`snapshot/services/snapshot_service.py`）

核心函数：

1. `capture_snapshots(level=M15, snapshot_time=None)`
   - 从 Redis 行情与汇率采集账户/持仓快照
   - 行情缺失写 `quote_missing`，汇率缺失写 `fx_missing`
2. `aggregate_snapshots(level, snapshot_time=None)`
   - H4/D1/MON1 分层聚合
3. `cleanup_expired_snapshots(now_dt=None)`
   - 删除历史过期快照

---

## 4. 数据契约

## 4.1 交易日历 CSV

默认目录：`<BASE_DIR>/data/market_calendars`

文件：`US_2026.csv`、`CN_2026.csv`、`HK_2026.csv`

字段：

1. `market`
2. `trade_date`
3. `timezone`
4. `is_open`
5. `market_open_local`
6. `market_close_local`
7. `market_open_utc`
8. `market_close_utc`
9. `is_half_day`
10. `session_tag`
11. `source`
12. `generated_at_utc`

重要说明：

1. 当前生成逻辑只写“开市日”行；休市日是“无行”。
2. `is_half_day` 当前实现按 `close < 16:00` 判定，适合 US，不适合 CN/HK（见“已知限制”）。

## 4.2 Redis Key 契约

主行情：

1. `watchlist:quotes:latest`
   - `updated_at`
   - `bootstrap_mode`
   - `updated_markets`
   - `stale_markets`
   - `guard_due_markets`
   - `data`

分市场：

1. `watchlist:quotes:market:{MARKET}`
   - `updated_at`：快照写入时间
   - `pulled_at`：该市场最后真实拉取时间（guard 频率判定依据）
   - `market`
   - `stale`
   - `data`

孤儿缓存：

1. `watchlist:quotes:orphan:{MARKET}:{SHORT_CODE}`（短 TTL）

汇率：

1. `watchlist:fx:usd-rates:latest`
   - `base=USD`
   - `updated_at`
   - `rates`

---

## 5. 配置项（`mango_project/settings.py`）

Calendar Guard 相关：

1. `MARKET_CALENDAR_DIR`
2. `MARKET_CALENDAR_REQUIRED`
3. `MARKET_PULL_FALLBACK_ON_MISSING_CALENDAR`
4. `MARKET_PULL_TASK_INTERVAL_MINUTES`
5. `MARKET_FX_PULL_INTERVAL_MINUTES`
6. `MARKET_CRYPTO_PULL_INTERVAL_MINUTES`
7. `MARKET_QUOTE_PROVIDER`（`real/fake`）
8. `MARKET_SYNC_TEST_EVERY_SECONDS`（>0 时覆盖 beat 分钟级调度）
9. `SNAPSHOT_CAPTURE_TEST_EVERY_SECONDS`
10. `SNAPSHOT_AGG_H4_TEST_EVERY_SECONDS`
11. `SNAPSHOT_AGG_D1_TEST_EVERY_SECONDS`
12. `SNAPSHOT_AGG_MON1_TEST_EVERY_SECONDS`
13. `SNAPSHOT_CLEANUP_TEST_EVERY_SECONDS`

调度相关：

1. 行情：`pull-watchlist-quotes-every-5-minutes`（`*/5`）
2. 快照采集：`*/15`
3. 聚合：H4/D1/MON1
4. 清理：每日 `01:45`

---

## 6. 启动与部署命令

## 6.1 依赖安装（Windows / Linux / macOS）

Windows（PowerShell / CMD）：

```powershell
py -m pip install pandas_market_calendars
```

Linux/macOS（bash/zsh）：

```bash
python3 -m pip install pandas_market_calendars
```

如 FX 需要 yfinance 降级：

Windows（PowerShell / CMD）：

```powershell
py -m pip install yfinance
```

Linux/macOS（bash/zsh）：

```bash
python3 -m pip install yfinance
```

## 6.2 生成交易日历 CSV（Windows / Linux / macOS）

Windows（PowerShell / CMD）：

```powershell
py manage.py build_market_calendar_csv --start 2026-01-01 --end 2027-12-31 --markets US CN HK
```

Linux/macOS（bash/zsh）：

```bash
python3 manage.py build_market_calendar_csv --start 2026-01-01 --end 2027-12-31 --markets US CN HK
```

## 6.3 Celery 启动（Windows / Linux / macOS）

Windows（PowerShell）：

```powershell
celery -A mango_project beat -l info
celery -A mango_project worker -n market_sync@%h -Q market_sync -l info -P solo
celery -A mango_project worker -n snapshot_capture@%h -Q snapshot_capture -l info -P solo
celery -A mango_project worker -n snapshot_aggregate@%h -Q snapshot_aggregate -l info -P solo
celery -A mango_project worker -n snapshot_cleanup@%h -Q snapshot_cleanup -l info -P solo
```

Linux/macOS（bash/zsh）：

```bash
celery -A mango_project beat -l info
celery -A mango_project worker -n market_sync@%h -Q market_sync -l info
celery -A mango_project worker -n snapshot_capture@%h -Q snapshot_capture -l info
celery -A mango_project worker -n snapshot_aggregate@%h -Q snapshot_aggregate -l info
celery -A mango_project worker -n snapshot_cleanup@%h -Q snapshot_cleanup -l info
```

## 6.4 一键脚本启动（推荐）

脚本文件：

1. Windows：`scripts/start_celery_stack.ps1`、`scripts/stop_celery_stack.ps1`
2. Linux/macOS：`scripts/start_celery_stack.sh`、`scripts/stop_celery_stack.sh`

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_celery_stack.ps1 -Targets all -WithBeat
powershell -ExecutionPolicy Bypass -File scripts/start_celery_stack.ps1 -Targets market_sync,snapshot_capture -WithBeat
powershell -ExecutionPolicy Bypass -File scripts/start_celery_stack.ps1 -Targets snapshot
powershell -ExecutionPolicy Bypass -File scripts/stop_celery_stack.ps1
```

Linux/macOS（bash/zsh）：

```bash
chmod +x scripts/start_celery_stack.sh scripts/stop_celery_stack.sh
./scripts/start_celery_stack.sh --targets all --with-beat
./scripts/start_celery_stack.sh --targets market_sync,snapshot_capture --with-beat
./scripts/start_celery_stack.sh --targets snapshot
./scripts/stop_celery_stack.sh
```

---

## 7. Guard 日志 reason 说明

常见 reason：

1. `due`：本轮应拉取
2. `not_due`：在会话内但未到本周期触发点
3. `outside_session`：当前不在该市场会话时间
4. `non_trading_day`：CSV 判定非交易日或当日无交易日行
5. `calendar_missing`：要求强依赖 CSV，但文件不存在
6. `fallback_without_calendar`：无 CSV，使用旧 `should_fetch_market` 降级
7. `after_half_day_close` / `after_half_day_close_guard`：半日市提前收盘后拦截

---

## 8. 冷启动与缺口修复机制

触发条件：

1. `need_bootstrap=True`（主快照无数据）
2. `need_repair=True`（订阅应有 code 与现有快照不一致）

行为：

1. 即使本轮 `due_markets` 为空，也执行一次 `force_init_pull`
2. 冷启动拉全部订阅市场
3. 修复只拉缺口市场

目的：避免“服务刚启动后一直等下个 due 点才有数据”。

---

## 9. 快照联动说明（重点）

`snapshot` 依赖的是 Redis 契约而不是拉取实现细节。  
只要以下契约不变，快照逻辑不需改：

1. `watchlist:quotes:latest` 仍提供 `data + updated_at`
2. `watchlist:fx:usd-rates:latest` 仍提供 `rates`
3. `market/services/fx_rate_service.get_fx_rates()` 返回结构不变

---

## 10. 常见问题排查（无数据）

按顺序检查：

1. 是否启动了 Beat（只启动 worker 不会定时投递）
2. `task_pull_watchlist_quotes` 是否在 `market_sync` 队列消费
3. 是否存在订阅（`UserInstrumentSubscription`）
4. guard 判定是否全 `not_due/outside_session`
5. `MARKET_CALENDAR_REQUIRED=True` 时 CSV 文件是否存在且日期覆盖当前日期
6. 外部源是否报错（新浪/币安/yfinance）
7. Redis 是否可写（主 key 与 market key）
8. 是否触发 `calendar.guard.force_init_pull`

---

## 11. 维护周期建议

1. 每年 12 月或每季度滚动重建下一年 CSV
2. 上线前先用 `MARKET_PULL_FALLBACK_ON_MISSING_CALENDAR=true` 灰度，再切强校验
3. 定期检查 `guard_due_markets` 与 `updated_markets` 差异
4. 监控 `quote_missing/fx_missing` 比例，评估行情质量

---

## 12. 已知限制与后续改进

1. `build_market_calendar_csv` 的 `is_half_day` 规则目前按 `close<16:00`，对 CN/HK 不准确，建议改为仅 US 判断或按交易所基准收盘时间分别判断。
2. 当前 CSV 生成是管理命令，不是 HTTP API；若要“平台化生成”，可补一个受控管理 API。
3. 建议补集成测试：节假日、半日市、午休、首次启动、缺口修复全链路。

---

## 13. 快速操作清单（SOP）

新环境首次上线：

1. 安装依赖 `pandas_market_calendars`
2. 生成 CSV（覆盖当前年份+下一年）
3. 启动 Redis
4. 启动 Beat + `market_sync` worker
5. 观察日志是否出现 `calendar.guard.force_init_pull` 与 `calendar.guard.due`
6. 验证 Redis 中 `watchlist:quotes:latest`、`watchlist:quotes:market:{M}`、`watchlist:fx:usd-rates:latest`
7. 启动 snapshot workers，确认 `M15` 快照可写入

---

## 14. 测试用例与结果

## 14.1 测试范围

本轮已补充并执行两类测试：

1. 无数据库单元测试（Guard/同步策略/CSV命令）
2. 带数据库集成测试（行情同步 -> Redis -> 快照入库）

对应测试文件：

1. `market/tests_fake_provider.py`
1. `market/tests_calendar_guard.py`
2. `market/tests_snapshot_sync_service.py`
3. `market/tests_calendar_command.py`
4. `market/tests_integration_market_snapshot.py`

## 14.2 关键测试用例

Calendar Guard：

1. 非交易日应拦截（`non_trading_day`）
2. CN `09:25` 单点预开盘只触发一次
3. FX 频率判定优先使用 `pulled_at`（不被 `updated_at` 干扰）
4. 当 `pulled_at=None` 时视为“从未拉取”，允许本轮 due

行情同步：

1. `due_markets` 为空且冷启动时，触发 `force_init_pull`
2. `due_markets` 为空且非冷启动时，不拉取并保留旧 `pulled_at`

CSV 命令：

1. `build_market_calendar_csv` 能输出 `US_2026.csv`
2. 输出包含标准表头和预期行内容

Fake Provider：

1. `MARKET_QUOTE_PROVIDER=fake` 时，不访问真实 API
2. `pull_watchlist_quotes`、`pull_single_instrument_quote`、`pull_usd_exchange_rates` 均返回可复现测试数据

数据库集成：

1. `sync_watchlist_snapshot -> capture_snapshots(M15)` 端到端写入 `PositionSnapshot` 与 `AccountSnapshot`
2. 缺行情时，投资持仓快照标记 `quote_missing`
3. 现金账户按汇率折算 `balance_usd`

## 14.3 执行命令

无数据库测试：

Windows（PowerShell / CMD）：

```powershell
py manage.py test market.tests_calendar_guard market.tests_snapshot_sync_service market.tests_calendar_command -v 2
```

Linux/macOS（bash/zsh）：

```bash
python3 manage.py test market.tests_calendar_guard market.tests_snapshot_sync_service market.tests_calendar_command -v 2
```

数据库集成测试（建议使用 `--keepdb`）：

Windows（PowerShell / CMD）：

```powershell
py manage.py test market.tests_integration_market_snapshot -v 2 --noinput --keepdb
```

Linux/macOS（bash/zsh）：

```bash
python3 manage.py test market.tests_integration_market_snapshot -v 2 --noinput --keepdb
```

全量本轮新增测试：

Windows（PowerShell / CMD）：

```powershell
py manage.py test market.tests_fake_provider market.tests_calendar_guard market.tests_snapshot_sync_service market.tests_calendar_command market.tests_integration_market_snapshot -v 1 --noinput --keepdb
```

Linux/macOS（bash/zsh）：

```bash
python3 manage.py test market.tests_fake_provider market.tests_calendar_guard market.tests_snapshot_sync_service market.tests_calendar_command market.tests_integration_market_snapshot -v 1 --noinput --keepdb
```

## 14.4 执行结果

1. 全量新增测试：`Found 13 test(s)`
2. `Ran 13 tests`
3. `OK`

备注：

1. 集成测试环境下，若未使用 `--keepdb`，你的本机 PostgreSQL 可能在 teardown 时出现“无法删除当前使用的数据库”错误；该问题不影响测试用例本身通过。
2. 日志中可见 `calendar.guard.force_init_pull`、`calendar.guard.due`、`calendar.guard.skip`，用于验证调度判定行为。

---

## 15. 高频无限压测（Fake 模式）

适用场景：

1. 不希望触发真实行情 API 限流
2. 想把周期压到秒级长期跑稳定性

关键配置（环境变量）：

1. `MARKET_QUOTE_PROVIDER=fake`
2. `MARKET_SYNC_TEST_EVERY_SECONDS=5`
3. `SNAPSHOT_CAPTURE_TEST_EVERY_SECONDS=7`
4. `SNAPSHOT_AGG_H4_TEST_EVERY_SECONDS=13`
5. `SNAPSHOT_AGG_D1_TEST_EVERY_SECONDS=17`
6. `SNAPSHOT_AGG_MON1_TEST_EVERY_SECONDS=19`
7. `SNAPSHOT_CLEANUP_TEST_EVERY_SECONDS=23`

示例（每个命令一个终端）：

Windows（PowerShell）：

```powershell
$env:MARKET_QUOTE_PROVIDER='fake'
$env:MARKET_SYNC_TEST_EVERY_SECONDS='5'
$env:SNAPSHOT_CAPTURE_TEST_EVERY_SECONDS='7'
$env:SNAPSHOT_AGG_H4_TEST_EVERY_SECONDS='13'
$env:SNAPSHOT_AGG_D1_TEST_EVERY_SECONDS='17'
$env:SNAPSHOT_AGG_MON1_TEST_EVERY_SECONDS='19'
$env:SNAPSHOT_CLEANUP_TEST_EVERY_SECONDS='23'
celery -A mango_project beat -l info
```

```powershell
$env:MARKET_QUOTE_PROVIDER='fake'
celery -A mango_project worker -n market_sync@%h -Q market_sync -l info -P solo
```

```powershell
$env:MARKET_QUOTE_PROVIDER='fake'
celery -A mango_project worker -n snapshot_capture@%h -Q snapshot_capture -l info -P solo
```

```powershell
$env:MARKET_QUOTE_PROVIDER='fake'
celery -A mango_project worker -n snapshot_aggregate@%h -Q snapshot_aggregate -l info -P solo
```

```powershell
$env:MARKET_QUOTE_PROVIDER='fake'
celery -A mango_project worker -n snapshot_cleanup@%h -Q snapshot_cleanup -l info -P solo
```

Linux/macOS（bash/zsh）：

```bash
export MARKET_QUOTE_PROVIDER=fake
export MARKET_SYNC_TEST_EVERY_SECONDS=5
export SNAPSHOT_CAPTURE_TEST_EVERY_SECONDS=7
export SNAPSHOT_AGG_H4_TEST_EVERY_SECONDS=13
export SNAPSHOT_AGG_D1_TEST_EVERY_SECONDS=17
export SNAPSHOT_AGG_MON1_TEST_EVERY_SECONDS=19
export SNAPSHOT_CLEANUP_TEST_EVERY_SECONDS=23
celery -A mango_project beat -l info
```

```bash
export MARKET_QUOTE_PROVIDER=fake
celery -A mango_project worker -n market_sync@%h -Q market_sync -l info
```

```bash
export MARKET_QUOTE_PROVIDER=fake
celery -A mango_project worker -n snapshot_capture@%h -Q snapshot_capture -l info
```

```bash
export MARKET_QUOTE_PROVIDER=fake
celery -A mango_project worker -n snapshot_aggregate@%h -Q snapshot_aggregate -l info
```

```bash
export MARKET_QUOTE_PROVIDER=fake
celery -A mango_project worker -n snapshot_cleanup@%h -Q snapshot_cleanup -l info
```

观察点：

1. Beat 日志应持续出现 `Scheduler: Sending due task ...`
2. `market_sync` 日志应持续出现 `calendar.guard.*` 与任务 `succeeded`
3. `snapshot_capture` 日志应持续出现 `task_capture_m15_snapshots ... succeeded`
4. 不应出现真实 API 网络错误（Fake 模式下不会访问外部行情源）

一键脚本：

1. Windows：`scripts/start_soak_mode.ps1`、`scripts/stop_soak_mode.ps1`
2. Linux/macOS：`scripts/start_soak_mode.sh`、`scripts/stop_soak_mode.sh`

统一脚本等价命令（同样可无限跑）：

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_celery_stack.ps1 -Targets all -WithBeat -FakeProvider -MarketSyncEverySeconds 5 -SnapshotCaptureEverySeconds 7 -SnapshotAggH4EverySeconds 13 -SnapshotAggD1EverySeconds 17 -SnapshotAggMon1EverySeconds 19 -SnapshotCleanupEverySeconds 23
powershell -ExecutionPolicy Bypass -File scripts/stop_celery_stack.ps1
```

Linux/macOS（bash/zsh）：

```bash
chmod +x scripts/start_celery_stack.sh scripts/stop_celery_stack.sh scripts/start_soak_mode.sh scripts/stop_soak_mode.sh
./scripts/start_celery_stack.sh --targets all --with-beat --fake-provider --market-sync-every-seconds 5 --snapshot-capture-every-seconds 7 --snapshot-agg-h4-every-seconds 13 --snapshot-agg-d1-every-seconds 17 --snapshot-agg-mon1-every-seconds 19 --snapshot-cleanup-every-seconds 23
./scripts/stop_celery_stack.sh
```

示例：

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_soak_mode.ps1
Get-Content tmp_stress_logs\market_sync.log -Wait
powershell -ExecutionPolicy Bypass -File scripts/stop_soak_mode.ps1
```

Linux/macOS（bash/zsh）：

```bash
./scripts/start_soak_mode.sh
tail -f tmp_stress_logs/market_sync.log
./scripts/stop_soak_mode.sh
```
