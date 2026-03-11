# Mango Backend 项目说明

版本：`V1.0.0`

## 1. 项目定位

Mango Backend 是 Mango Finance 的后端服务，基于 Django + Django REST Framework 构建，负责用户认证、账户记账、行情查询、投资交易记录、资产快照归档以及定时任务调度。

## 2. 技术栈

- Django 6
- Django REST Framework
- Simple JWT
- PostgreSQL
- Redis
- Celery
- yfinance / akshare / pandas-market-calendars

## 3. 核心业务模块

- [login/README.md](login/README.md)：邮箱注册、邮箱验证码、密码重置、登录和用户名维护
- [accounts/README.md](accounts/README.md)：资金账户、流水、转账、撤销与归档
- [market/README.md](market/README.md)：交易品种、行情查询、自选股、汇率和指数快照
- [investment/README.md](investment/README.md)：买卖记录、持仓、已实现盈亏
- [snapshot/README.md](snapshot/README.md)：账户和持仓快照采集、聚合、查询
- [shared/README.md](shared/README.md)：公共约束、异常、时间与工具方法

## 4. 目录结构

```text
.
|-- mango_project/   Django 工程入口、配置、URL、Celery
|-- login/           认证与用户登录相关接口
|-- accounts/        账户、流水、转账
|-- market/          行情与交易品种
|-- investment/      投资交易与持仓
|-- snapshot/        快照采集与查询
|-- shared/          公共基础设施
|-- data/            静态市场日历数据
|-- scripts/         本地启动和安装脚本
|-- deploy/          部署模板文件
```

## 5. 运行要求

- Python 3.12
- PostgreSQL 作为主数据库
- Redis 作为缓存和 Celery Broker
- 可用 SMTP 服务用于发送邮箱验证码

环境变量模板见 [`.env.example`](.env.example)。

## 6. 本地启动

```bash
conda env create -f environment.yml
conda activate Back_end_project
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

后台任务建议单独启动：

```bash
celery -A mango_project worker -l info
celery -A mango_project beat -l info
```

也可以直接使用 [scripts/README.md](scripts/README.md) 中的脚本。

## 7. 定时任务

- 自选行情补拉：`accounts.tasks.task_pull_watchlist_quotes`
- 15 分钟快照采集：`snapshot.tasks.task_capture_m15_snapshots`
- H4 / D1 / MON1 聚合：`snapshot.tasks.task_aggregate_*`
- 历史快照清理：`snapshot.tasks.task_cleanup_snapshot_history`

## 8. 接口入口

- `/api/login/`
- `/api/register/email/code/`
- `/api/register/email/`
- `/api/password/reset/code/`
- `/api/password/reset/`
- `/api/user/accounts/`
- `/api/user/transactions/`
- `/api/user/transfers/`
- `/api/user/markets/`
- `/api/investment/*`
- `/api/snapshot/*`

## 9. 测试与维护

- 自动化测试入口：`python manage.py test`
- 维护与发布说明：[`MAINTENANCE.md`](MAINTENANCE.md)

## 10. 英文文档

英文版见 [README.en.md](README.en.md)。
