# Snapshot 业务逻辑（V2 - 项目整合版）

## 1. 文档目标

本文件是 `v1`（策略设计）与当前已落地实现（改造后的 `v2`）的整合版，结论以“当前项目代码”为准。

适用范围：

1. 非投资账户余额快照。
2. 投资账户持仓快照。
3. 投资账户按 USD 统一汇总分析。

---

## 2. 核心原则

1. 全量快照落数据库，Redis 只做缓存与行情/汇率来源，不做唯一存储。
2. 统一货币口径为 `USD`，非投资账户也必须落 `balance_usd`。
3. 持仓快照保留原币，同时保留 USD 折算值。
4. 高频采集 + 低频聚合 + 分层清理。
5. 幂等写入（唯一键 + upsert），可重试。

---

## 3. App 与模型归属（当前）

快照已迁移到 `snapshot` app：

1. `snapshot.AccountSnapshot`（表：`snapshot_account_snapshot`）
2. `snapshot.PositionSnapshot`（表：`snapshot_position_snapshot`）

`investment` app 仅保留交易与持仓主模型，不再承载快照模型。

---

## 4. 统一货币规则

## 4.1 基准币种

1. 系统分析基准币：`USD`。
2. 所有账户走势分析统一以 `USD` 输出。

## 4.2 非投资账户

1. 读取账户原币余额 `balance_native`。
2. 使用 USD 汇率表折算 `balance_usd`。
3. 快照必须写入 `balance_usd`（缺汇率时标记 `fx_missing`，并按降级值写入）。

## 4.3 投资账户与持仓

1. 持仓快照保留原币字段：`currency`、`market_price`、`market_value`。
2. 同时写入 `market_value_usd` 与 `fx_rate_to_usd`。
3. 投资账户快照按持仓 USD 汇总值写入 `balance_usd`。

---

## 5. 快照层级与保留策略

| 层级 | 标识 | 频率 | 保留 |
|---|---|---|---|
| 短期 | `M15` | 每 15 分钟采集 | 1 天 |
| 中期 | `H4` | 每 4 小时聚合 | 1 个月 |
| 长期 | `D1` | 每日聚合 | 3 个月 |
| 超长期 | `MON1` | 每月聚合 | 永久 |

说明：

1. `H4/D1/MON1` 优先从低层级快照聚合，不重复拉行情。
2. 聚合窗口无低层数据时返回 `source_level=none`，不强行补假数据。

---

## 6. 数据模型（当前字段）

## 6.1 AccountSnapshot

字段：

1. `account_id`
2. `snapshot_time`
3. `snapshot_level`（`M15/H4/D1/MON1`）
4. `account_currency`
5. `balance_native`
6. `balance_usd`
7. `fx_rate_to_usd`
8. `data_status`（`ok/quote_missing/fx_missing`）
9. `created_at`

约束与索引：

1. 唯一键：`(account_id, snapshot_level, snapshot_time)`
2. 索引：`(snapshot_level, snapshot_time)`

## 6.2 PositionSnapshot

字段：

1. `account_id`
2. `instrument_id`
3. `snapshot_time`
4. `snapshot_level`
5. `quantity`
6. `avg_cost`
7. `market_price`（原币）
8. `market_value`（原币）
9. `market_value_usd`
10. `fx_rate_to_usd`
11. `realized_pnl`
12. `currency`（原币）
13. `price_time`
14. `data_status`
15. `created_at`

约束与索引：

1. 唯一键：`(account_id, instrument_id, snapshot_level, snapshot_time)`
2. 索引：`(account_id, snapshot_level, snapshot_time)`、`(snapshot_level, snapshot_time)`

---

## 7. 生成流程（当前实现）

## 7.1 M15 采集（`capture_snapshots`）

1. 对齐 `snapshot_time`（UTC，15 分钟桶）。
2. 拉取 USD 汇率表（整批使用同一份）。
3. 拉取行情快照索引。
4. 写投资持仓 `PositionSnapshot`（原币 + USD）。
5. 写所有活跃账户 `AccountSnapshot`：
   - 非投资账户：原币余额折算 USD。
   - 投资账户：持仓 USD 汇总后写入。
6. 通过 `update_or_create` 幂等写入。

## 7.2 H4/D1/MON1 聚合（`aggregate_snapshots`）

1. 计算窗口起止时间并对齐目标层级时间点。
2. 在窗口内读取源层级每个账户/持仓“最后一个点”。
3. upsert 到目标层级快照。
4. 源层级选择规则：
   - `H4 <- M15`
   - `D1 <- H4`（无则回退 `M15`）
   - `MON1 <- D1`（无则回退 `H4/M15`）

## 7.3 清理（`cleanup_expired_snapshots`）

1. 删除 `M15` 超 1 天。
2. 删除 `H4` 超 30 天。
3. 删除 `D1` 超 90 天。
4. `MON1` 不删除。

---

## 8. 删除规则

1. 账户删除：级联删除该账户相关快照（数据库外键行为）。
2. 持仓删除：不立即删历史快照，按保留策略清理。

---

## 9. Celery 队列与调度（当前配置）

## 9.1 队列分工

1. `market_sync`
   - `accounts.tasks.task_pull_watchlist_quotes`
2. `snapshot_capture`
   - `snapshot.tasks.task_capture_m15_snapshots`
3. `snapshot_aggregate`
   - `snapshot.tasks.task_aggregate_h4_snapshots`
   - `snapshot.tasks.task_aggregate_d1_snapshots`
   - `snapshot.tasks.task_aggregate_mon1_snapshots`
4. `snapshot_cleanup`
   - `snapshot.tasks.task_cleanup_snapshot_history`

## 9.2 Beat 调度

1. M15：`*/15 * * * *`
2. H4：`10 */4 * * *`
3. D1：`20 0 * * *`
4. MON1：`30 0 1 * *`
5. Cleanup：`45 1 * * *`

---

## 10. 启动说明（多 Worker）

Windows 推荐：

1. Beat（只开一个）
```powershell
celery -A mango_project beat -l info
```

2. Worker（行情）
```powershell
celery -A mango_project worker -n market_sync@%h -Q market_sync -l info -P solo
```

3. Worker（采集）
```powershell
celery -A mango_project worker -n snapshot_capture@%h -Q snapshot_capture -l info -P solo
```

4. Worker（聚合）
```powershell
celery -A mango_project worker -n snapshot_aggregate@%h -Q snapshot_aggregate -l info -P solo
```

5. Worker（清理）
```powershell
celery -A mango_project worker -n snapshot_cleanup@%h -Q snapshot_cleanup -l info -P solo
```

注意：

1. `beat` 只能启动一个实例。
2. Linux 环境可去掉 `-P solo` 使用默认并发池。
3. 任务已做幂等，重复投递不会产生重复快照记录。

---

## 11. 测试数据生成（已支持）

已提供管理命令：`generate_snapshot_test_data`

命令位置：

1. `snapshot/management/commands/generate_snapshot_test_data.py`

作用：

1. 基于当前账户和持仓，随机生成 `M15/H4/D1/MON1` 快照数据。
2. 可指定历史天数（默认 60 天）和随机种子。
3. 生成后自动调用清理逻辑，仅保留应保留的数据。

用法示例：

```powershell
python manage.py generate_snapshot_test_data --days 60 --seed 20260304
```

全量重建（先清空全部快照再生成）：

```powershell
python manage.py generate_snapshot_test_data --days 60 --seed 20260304 --wipe-all
```

---

## 12. 查询层建议（下一步）

1. 查询接口按跨度自动选层：
   - `<=2天` 用 `M15`
   - `<=45天` 用 `H4`
   - `<=180天` 用 `D1`
   - 其他用 `MON1`
2. 返回统一时间序列结构：
   - `[{ts, value_usd, data_status}]`
3. 支持显式 `level` 覆盖自动选层。

---

## 13. 验收标准

1. 非投资账户快照始终写入 `balance_usd`。
2. 投资持仓快照保留原币并写入 USD 折算值。
3. M15 采集、H4/D1/MON1 聚合、清理任务可独立执行。
4. 多 worker 并发下无重复记录（唯一键 + upsert）。
5. 不同时间跨度查询可稳定命中对应层级。

---

## 14. 当前结论

当前项目已具备完整快照主链路：

1. 模型与表结构已稳定。
2. M15 采集 + 聚合 + 清理已可运行。
3. 非投资账户 USD 统一口径已落地。

后续重点：

1. 增加查询 API。
2. 增加聚合与清理单元测试/集成测试。
3. 视数据规模补充分批删除与批量 upsert 优化。
