# Mango Project 压力测试方案

## 1. 目标

这份方案按当前项目的真实结构排序，优先覆盖最容易出事故、最接近线上高频路径的接口与后台任务。

当前项目的关键运行依赖：

- Web: Django + DRF + JWT
- DB: PostgreSQL
- Cache: Redis
- Async: Celery + Redis Broker
- Email: SMTP

建议压测主工具用 `k6`。原因是接口以 HTTP API 为主，场景脚本比 JMeter 更容易维护。

压测时统一关注这些指标：

- 接口: `p50/p95/p99`、QPS、错误率、超时率
- Django: Gunicorn/Uvicorn worker CPU、内存、连接数
- PostgreSQL: 活跃连接数、慢 SQL、锁等待、事务回滚数
- Redis: ops/sec、内存、命中率、网络抖动
- Celery: 队列堆积、任务耗时、失败重试数

## 2. 压测前置要求

压测不要在 SQLite 或本地假环境上做结论，至少保持和目标环境同类组件：

- PostgreSQL
- Redis cache
- Redis broker
- Celery worker
- Celery beat

邮件相关接口压测时，建议把 SMTP 切到测试邮箱或假 SMTP 服务，否则外部邮件服务会污染结果。

建议准备一套压测数据：

- 200 个测试用户
- 每用户 3 到 5 个资金账户
- 每用户 10 到 30 条交易流水
- 每用户 5 到 20 个持仓
- 快照数据至少覆盖 7 天 `M15`

建议同时准备可复用的启动方式，避免压测时再临时拼命令：

- Windows PowerShell：`powershell -ExecutionPolicy Bypass -File resource/scripts/windows/start_celery.ps1 -WithBeat`
- Linux/macOS：`./resource/scripts/unix/start_celery.sh --with-beat`
- Web 进程：`./resource/scripts/macos/start_web.sh` 或 `python manage.py runserver 0.0.0.0:8000`

## 3. 优先级排序

### P0: 资金写入一致性链路

这是最先要压的一组。原因很直接：这些接口都带事务、行锁或余额变更，压坏了不是慢，而是错账。

覆盖接口：

- `POST /api/investment/buy/`
- `POST /api/investment/sell/`
- `POST /api/user/transactions/`
- `POST /api/user/transactions/{id}/reverse/`

为什么优先：

- `investment/services/trade_service.py` 里有 `transaction.atomic()` 和 `select_for_update()`
- `accounts/services/transaction_service.py` 也依赖事务和行锁
- 仓库里已经有并发撤销测试，说明这里本来就是并发风险区

建议场景：

1. 同一账户热点并发买入
   目标：验证余额扣减和持仓写入不会出现负数、重复扣款、脏写
   并发建议：`20 -> 50 -> 100`

2. 同一持仓热点并发卖出
   目标：验证不会超卖，不会出现负持仓
   并发建议：`20 -> 50 -> 100`

3. 同一交易并发撤销
   目标：验证只有一次撤销成功，其他请求返回业务失败，不写脏数据
   并发建议：`10 -> 30 -> 50`

4. 转账和普通流水混合写入
   配比建议：`转账 40% + 普通交易 40% + 撤销 20%`
   目标：验证账户余额、转入转出账户关系和删除/撤销路径都一致

建议通过标准：

- 错误率 `< 1%`
- 业务冲突类错误可接受，但数据错误不可接受
- 压测结束后抽样核对：
  - 账户余额不为负
  - 持仓数量不为负
- 转账记录的 `account / transfer_account / amount` 是否与账户余额变化一致
  - 同一原始交易最多只有一条 reversal

### P1: 行情高频读取与自选写入

这是前端最容易形成高频访问的一组，重点看 Redis 和行情快照命中情况。

覆盖接口：

- `GET /api/user/markets/`
- `POST /api/user/markets/quotes/latest/`
- `POST /api/user/markets/watchlist/`
- `DELETE /api/user/markets/watchlist/`
- `GET /api/user/markets/indices/`
- `GET /api/user/markets/fx-rates/`

为什么优先：

- `market/services/query_service.py` 基本靠缓存快照返回，属于典型高频读
- `watchlist_service.py` 在新增自选时可能触发行情补拉和缓存写入
- 这是最接近“首页刷新、列表轮询、自选操作”的真实流量

建议场景：

1. 市场首页读压测
   配比建议：`GET /markets/ 70% + POST /markets/quotes/latest/ 20% + GET /markets/indices/ 10%`
   并发建议：`50 -> 100 -> 300`

2. 自选增删混合压测
   配比建议：`读 80% + 加自选 10% + 删自选 10%`
   并发建议：`20 -> 50 -> 100`
   重点观察：Redis 写放大、响应抖动、重复添加时的幂等表现

3. 突刺测试
   从 `20` 虚拟用户瞬间升到 `200`
   目标：验证行情首页和批量最新价接口在短时高峰下是否还能稳定命中缓存

建议通过标准：

- `GET /api/user/markets/` 的 `p95 < 200ms`
- `POST /api/user/markets/quotes/latest/` 的 `p95 < 150ms`
- watchlist 增删时无明显 Redis 异常和无级联超时

### P2: 快照查询和历史分页查询

这组接口未必最频繁，但很容易在数据量上来后拖慢数据库。

覆盖接口：

- `GET /api/snapshot/accounts/`
- `GET /api/snapshot/positions/`
- `GET /api/investment/history/`
- `GET /api/user/transactions/`
- `GET /api/investment/positions/`

为什么优先级放在第三：

- 查询接口主要风险是慢，不是错账
- `snapshot/services/query_service.py` 会做时间桶展开和大范围扫描
- `investment/services/query_service.py`、`transaction_query_service.py` 有 `count + page` 模式，数据量大时容易退化

建议场景：

1. 大时间范围快照查询
   参数建议：
   - `M15` 查 1 天
   - `H4` 查 30 天
   - `D1` 查 90 天
   并发建议：`20 -> 50 -> 100`

2. 历史分页深翻页
   目标：验证 `offset` 增大后性能是否显著退化
   并发建议：`20 -> 50`

3. 混合读场景
   配比建议：`transactions 40% + investment/history 30% + snapshot/accounts 15% + snapshot/positions 15%`

建议通过标准：

- 快照查询 `p95 < 500ms`
- 历史分页 `p95 < 400ms`
- PostgreSQL 无持续放大的锁等待和全表扫描热点

### P3: 后台任务与 API 混合稳定性测试

这部分很重要，因为项目已经把市场同步和快照任务拆成了独立 Celery 队列，并提供了现成的启动脚本，可以直接把后台任务和 API 一起跑起来做长稳验证。

覆盖链路：

- `market.tasks.task_pull_data`
- `snapshot.tasks.task_capture_m15_snapshots`
- `snapshot.tasks.task_aggregate_h4_snapshots`
- `snapshot.tasks.task_aggregate_d1_snapshots`
- `snapshot.tasks.task_aggregate_mon1_snapshots`
- `snapshot.tasks.task_cleanup_snapshot_history`

为什么要单独做：

- `snapshot_service.py` 会批量读取账户、持仓、行情快照并写回快照表
- `snapshot_sync_service.py` 会同时读写 Redis 快照和汇率缓存
- 真实线上故障经常不是单个接口慢，而是后台任务把 DB/Redis 顶满后拖垮 API

建议场景：

1. 启动 soak 模式
   使用仓库里的真实脚本启动 Celery/beat：

   PowerShell:
   `powershell -ExecutionPolicy Bypass -File resource/scripts/windows/start_celery.ps1 -WithBeat`

   Bash:
   `./resource/scripts/unix/start_celery.sh --with-beat`

2. 同时压 API
   配比建议：
   - `GET /api/user/markets/` 40%
   - `POST /api/user/markets/quotes/latest/` 20%
   - `GET /api/snapshot/accounts/` 20%
   - `GET /api/snapshot/positions/` 20%

3. 长稳测试
   持续时间建议：`2 小时 -> 6 小时`

重点观察：

- Celery 队列是否堆积
- 快照任务是否出现持续延迟
- Redis key 数量和内存是否持续上涨
- 快照表写入速度是否导致 DB I/O 抬升

建议通过标准：

- 2 小时内无明显内存泄漏
- Celery 队列无持续积压
- API 的 `p95` 不因为后台任务长期恶化

### P4: 登录、Token、邮箱验证码链路

这组接口要做，但优先级可以放最后，因为它们更容易被外部 SMTP 或密码哈希成本主导。

覆盖接口：

- `POST /api/login/`
- `POST /api/token/refresh/`
- `POST /api/register/email/code/`
- `POST /api/register/email/`
- `POST /api/password/reset/code/`
- `POST /api/password/reset/`

为什么放最后：

- 登录通常不是最重流量
- 邮件验证码接口的主要瓶颈可能在 SMTP，不在应用本身
- 如果前面资金链路和行情链路还没稳，这组压测价值不高

建议场景：

1. 登录风暴
   并发建议：`20 -> 50 -> 100`

2. Token 刷新高频测试
   并发建议：`50 -> 100 -> 300`

3. 验证码接口测试
   使用假 SMTP 或测试邮箱
   目标：看缓存写入、模板渲染、邮件发送阻塞情况

补充说明：

- 当前仓库的 `resource/test/k6/p4_auth.js` 已覆盖登录、刷新 token 和可选的发码接口
- 完整的注册 / 重置密码闭环仍建议保留给功能测试，不建议在压测里依赖验证码明文回传

## 4. 推荐执行顺序

建议按下面顺序推进，不要一开始就全链路混压：

1. P0 单接口一致性压测
2. P0 混合资金链路压测
3. P1 行情读压测
4. P1 自选增删压测
5. P2 大数据量查询压测
6. P3 长稳测试
7. P4 认证与验证码压测

## 5. 数据校验清单

每轮压测后，不只看响应时间，还要做数据校验：

- 账户余额是否出现负数或异常跳变
- 持仓数量是否出现负数
- 同一笔交易是否被重复撤销
- 转账是否缺失任一侧流水
- 快照表同一 `(account/instrument, level, snapshot_time)` 是否出现异常重复
- Redis 中 `WATCHLIST_QUOTES_KEY` 是否存在异常膨胀

## 6. 对应脚本

当前仓库已经有一组和上面优先级对应的 `k6` 脚本，可以直接作为第一轮执行入口：

- P0 资金写入一致性链路：`resource/test/k6/p0_funds.js`
- P1 行情高频读取与自选写入：`resource/test/k6/p1_market.js`
- P2 快照查询和历史分页查询：`resource/test/k6/p2_queries.js`
- P3 后台任务与 API 混合稳定性测试：`resource/test/k6/p3_soak_mixed.js`
- P4 登录、Token、邮箱验证码链路：`resource/test/k6/p4_auth.js`

脚本的环境变量、示例命令和状态码口径见：`resource/test/k6/README.md`

## 7. 第一轮最小可执行方案

如果你现在只想先做第一轮，我建议先做这 4 项：

1. `investment buy/sell` 热点并发
2. `transactions + transfer + reverse` 混合并发
3. `markets + quotes/latest` 高频读压测
4. `Celery soak mode + snapshot query` 2 小时稳定性测试

这 4 项最能尽快暴露你当前项目的真实瓶颈。

