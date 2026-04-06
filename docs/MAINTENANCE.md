# Mango Backend 维护手册

更新时间：`2026-04-07`

相关项目文档：

- [README.md](../README.md)
- [Deployment/backend_first_deploy_conda.md](./Deployment/backend_first_deploy_conda.md)
- [Deployment/backend_deployment_guide.md](./Deployment/backend_deployment_guide.md)

## 1. 维护范围

本手册只记录仓库级、环境无关的维护要点，不再写死某台机器的绝对路径、特定 `launchd/systemd` 标签或个人目录结构。

当前系统维护重点：

- Django Web 服务
- Celery Worker / Beat
- PostgreSQL
- Redis
- 市场同步与快照采集链路

## 2. 快速健康检查

先确认基础依赖：

```bash
redis-cli -h 127.0.0.1 -p 6379 ping
pg_isready -h 127.0.0.1 -p 5432
```

再确认 Django 和文档路由：

```bash
python manage.py check
curl -I http://127.0.0.1:8000/docs/swagger/
```

再确认 Celery 关键任务名称没有漂移：

- `market.tasks.task_pull_data`
- `snapshot.tasks.task_capture_m15_snapshots`
- `snapshot.tasks.task_aggregate_h4_snapshots`
- `snapshot.tasks.task_aggregate_d1_snapshots`
- `snapshot.tasks.task_aggregate_mon1_snapshots`
- `snapshot.tasks.task_cleanup_snapshot_history`

## 3. 发布后基础回归

改代码后建议至少执行：

```bash
python manage.py check
python manage.py migrate --plan
python manage.py test market.tests.test_api market.tests.test_snapshot_sync_service market.tests.test_integration_market_snapshot snapshot.tests.test_query_api --keepdb --noinput -v 1
```

如果涉及账号、投资或账本逻辑，再补：

```bash
python manage.py test accounts.tests.test_accounts investment.tests --keepdb --noinput -v 1
```

Windows 如果 `conda run -n Back_end_project ...` 出现临时文件或激活异常，优先改用显式激活：

```powershell
& 'D:\Develop\Anaconda\shell\condabin\conda-hook.ps1'
conda activate Back_end_project
python manage.py check
python manage.py migrate --plan
```

## 4. 按改动类型决定重启范围

只改 Django 接口或普通服务逻辑：

- 重启 Web

改 Celery 任务执行逻辑：

- 重启 Worker

改 Celery Beat 调度、`CELERY_BEAT_SCHEDULE` 或任务路由：

- 重启 Worker 和 Beat

改 `.env`、数据库连接、Redis、缓存键结构：

- 重启 Web、Worker、Beat

改 PostgreSQL / Redis 本身配置：

- 按你的托管方式重启数据库或 Redis 服务

## 5. 市场与快照联动排查

如果发现“投资账户当前余额”和“历史快照曲线”不一致，优先按这个顺序排查：

1. `market.tasks.task_pull_data` 是否正常执行
2. Redis 中 `watchlist:quotes:latest` 和 `watchlist:fx:usd-rates:latest` 是否存在
3. `snapshot.tasks.task_capture_m15_snapshots` 是否正常执行
4. 市场同步后，投资账户余额是否已被 `sync_investment_accounts_after_market_refresh()` 重估

关键事实：

- 当前余额依赖 `market` 同步后的账户重估
- 历史曲线依赖 `snapshot` 采集任务
- 两者不是同一条链路，也不会互相回写

## 6. 常用日志位置

如果你用仓库自带脚本启动 Celery，默认日志目录通常是：

```bash
resource/tmp_celery_logs/
```

常见日志文件包括：

- `market_sync.log`
- `beat.log`
- 你所在环境自定义的 worker / web 输出日志

查看示例：

```bash
tail -f resource/tmp_celery_logs/market_sync.log
tail -f resource/tmp_celery_logs/beat.log
```

Windows：

```powershell
Get-Content resource\tmp_celery_logs\market_sync.log -Wait
Get-Content resource\tmp_celery_logs\beat.log -Wait
```

## 7. 维护注意事项

- `market` 的 Redis 快照是 `snapshot` 和 `investment` 的共享契约，改字段前必须联动回归
- `watchlist:quotes:*`、`watchlist:fx:usd-rates:latest`、`market:index:quotes:*` 不是普通缓存键，属于运行时主数据
- `accounts.Transaction.save()` 仍有余额副作用，批量改账本逻辑前先跑回归
- `docs/Api`、`docs/Design`、`docs/Test` 与实现耦合较强，服务名、任务名、接口路径变更后要同步更新文档

## 8. 何时回看部署文档

下面这些场景不要只看本手册，应回到部署文档：

- 首次部署
- 新机器迁移
- Conda 环境重建
- `systemd` 或 `launchd` 托管
- logo、代码表、核心指数初始化

对应入口：

- [Deployment/backend_first_deploy_conda.md](./Deployment/backend_first_deploy_conda.md)
- [Deployment/backend_deployment_guide.md](./Deployment/backend_deployment_guide.md)

