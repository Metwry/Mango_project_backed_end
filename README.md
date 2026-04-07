# Mango Backend

Version: `V1.0.0`

Mango Backend is a Django REST API service for Mango Finance. It covers authentication, account bookkeeping, market data, investment trading, and periodic snapshots.

Mango Backend 是 Mango Finance 的 Django REST API 后端，覆盖认证登录、账户记账、市场行情、投资交易和周期快照。

## 中文说明

### 1. 项目定位

Mango Backend 是 Mango Finance 的后端服务，基于 Django + Django REST Framework 构建，负责用户认证、账户记账、行情查询、投资交易记录、资产快照归档以及定时任务调度。

### 2. 技术栈

- Django 6
- Django REST Framework
- Simple JWT
- PostgreSQL
- Redis
- RabbitMQ
- Celery
- yfinance / akshare / exchange-calendars

### 3. 核心业务模块

- [login/README.md](login/README.md)：邮箱注册、邮箱验证码、密码重置、登录和用户名维护
- [accounts/README.md](accounts/README.md)：资金账户、流水、简化转账、撤销与归档
- [market/README.md](market/README.md)：交易品种、行情查询、自选股、汇率和指数快照
- [investment/README.md](investment/README.md)：买卖记录、持仓、已实现盈亏
- [snapshot/README.md](snapshot/README.md)：账户和持仓快照采集、聚合、查询
- [common/README.md](common/README.md)：公共约束、异常、时间与工具方法

### 4. 目录结构

```text
.
|-- mango_project/   Django 工程入口、配置、URL、Celery
|-- login/           认证与用户登录相关接口
|-- accounts/        账户、流水、简化转账
|-- market/          行情与交易品种
|-- investment/      投资交易与持仓
|-- snapshot/        快照采集与查询
|-- common/          公共基础设施
|-- docs/            项目文档与维护手册
|-- resource/data/   运行期静态资源
|-- resource/scripts/ 启动、停止和安装脚本
|-- resource/deploy/  部署模板文件
|-- resource/test/    压测与测试资源
```

### 5. 运行要求

- Python 3.12
- PostgreSQL 作为主数据库
- Redis 作为缓存
- RabbitMQ 作为 Celery Broker
- 可用 SMTP 服务用于发送邮箱验证码

环境变量模板见 [`.env.example`](.env.example)。

如果你想直接用 Docker 启动整套后端栈，优先使用根目录的 [`docker-compose.yml`](docker-compose.yml)。
它现在同时编排 PostgreSQL / Redis / RabbitMQ / Django Web / Celery Beat / 3 个 Celery Worker。
仅基础设施模板仍保留在 [`resource/deploy/docker-compose.infrastructure.yml`](resource/deploy/docker-compose.infrastructure.yml)。

### 6. 本地启动

```bash
conda env create -f environment.yml
conda activate Back_end_project
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

后台任务建议单独启动：

```bash
celery -A mango_project worker -n market_worker@%h -Q market_sync,news_ingest -l info -P threads --concurrency 4
celery -A mango_project worker -n snapshot_worker@%h -Q snapshot_capture,snapshot_aggregate,snapshot_cleanup -l info -P threads --concurrency 4
celery -A mango_project worker -n ai_worker@%h -Q news_embedding,ai_analysis -l info -P threads --concurrency 4
celery -A mango_project beat -l info
```

说明：

- 当前推荐拆分为 3 个 worker：`market`、`snapshot`、`ai`
- `beat` 启动后会额外投递一次 `market_sync` 全量初始化任务，后续定时任务继续按原有市场时段和拉取节奏执行
- 每个 worker 默认使用 `threads` 池，并发数为 `4`

也可以直接使用 [resource/scripts/README.md](resource/scripts/README.md) 中的脚本。

如果你要直接以 Docker 方式运行整套服务，可执行：

```bash
docker compose up -d --build
```

容器列表：

- `mango-postgres`
- `mango-redis`
- `mango-rabbit`
- `mango-web`
- `mango-beat`
- `mango-worker-market`
- `mango-worker-snapshot`
- `mango-worker-ai`

如果你只想单独维护基础设施容器，再继续按宿主机方式启动 Django / Celery，才使用 [`resource/deploy/docker-compose.infrastructure.yml`](resource/deploy/docker-compose.infrastructure.yml)。

### 7. 定时任务

- 市场数据拉取：`market.tasks.task_refresh_all`
- 新闻抓取：`news.tasks.task_ingest_yahoo_news`，默认每 2 小时一次
- 新闻 embedding 补齐：`news.tasks.task_embed_missing_news_articles`，默认每 30 分钟一次
- 新闻 AI 分析补齐：`ai.tasks.task_analyze_pending_news_articles` / `ai.tasks.task_analyze_missing_news_articles`，默认每 30 分钟一次
- 15 分钟快照采集：`snapshot.tasks.task_capture_m15_snapshots`
- H4 / D1 / MON1 聚合：`snapshot.tasks.task_aggregate_*`
- 历史快照清理：`snapshot.tasks.task_cleanup_snapshot_history`

### 8. 接口入口

- `/api/login/`
- `/api/register/email/code/`
- `/api/register/email/`
- `/api/password/reset/code/`
- `/api/password/reset/`
- `/api/user/accounts/`
- `/api/user/transactions/`
- `/api/user/markets/`
- `/api/investment/*`
- `/api/snapshot/*`

### 9. 测试与维护

- 自动化测试入口：`python manage.py test`
- 维护与发布说明：[`MAINTENANCE.md`](docs/MAINTENANCE.md)

## English Guide

### 1. Overview

Mango Backend is the API service behind Mango Finance. It is built with Django and Django REST Framework and owns authentication, cash-account bookkeeping, market data access, investment trade recording, portfolio snapshots, and scheduled jobs.

### 2. Stack

- Django 6
- Django REST Framework
- Simple JWT
- PostgreSQL
- Redis
- RabbitMQ
- Celery
- yfinance / akshare / exchange-calendars

### 3. Core Domains

| Path | Responsibility |
| --- | --- |
| [login/README.md](login/README.md) | Authentication, email verification, JWT issuing |
| [accounts/README.md](accounts/README.md) | Accounts, transactions, simplified transfers |
| [market/README.md](market/README.md) | Instrument master data, quotes, FX, watchlist |
| [investment/README.md](investment/README.md) | Buy/sell execution, positions, trade history |
| [snapshot/README.md](snapshot/README.md) | Timed snapshots, aggregation, query APIs |
| [common/README.md](common/README.md) | Common exceptions, constraints, utilities |
| [mango_project/README.md](mango_project/README.md) | Django project wiring, settings, and Celery runtime policies |
| [resource/data/README.md](resource/data/README.md) | Static market calendar data |
| [resource/scripts/README.md](resource/scripts/README.md) | Local bootstrap and start/stop scripts |
| [resource/deploy/README.md](resource/deploy/README.md) | Deployment descriptors for launchd |

### 4. Runtime

- Python 3.12
- PostgreSQL
- Redis for caching
- RabbitMQ as the Celery broker
- SMTP provider for email verification
- Celery worker and Celery beat

### 5. Quick Start

1. Create the environment from `environment.yml`.
2. Copy `.env.example` to `.env` and fill secrets.
3. Run `python manage.py migrate`.
4. Start Django and Celery processes.
5. Run `python manage.py test`.

Recommended Celery commands:

```bash
celery -A mango_project worker -n market_worker@%h -Q market_sync,news_ingest -l info -P threads --concurrency 4
celery -A mango_project worker -n snapshot_worker@%h -Q snapshot_capture,snapshot_aggregate,snapshot_cleanup -l info -P threads --concurrency 4
celery -A mango_project worker -n ai_worker@%h -Q news_embedding,ai_analysis -l info -P threads --concurrency 4
celery -A mango_project beat -l info
```

`beat` publishes one forced `market_sync` refresh on startup, while later scheduled refreshes still follow the normal market guard logic.

For deployment and maintenance details, see [MAINTENANCE.md](docs/MAINTENANCE.md).
