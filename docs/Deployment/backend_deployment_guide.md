# 后端部署总指南

本文档是后端部署总入口，覆盖：

1. 部署前准备
2. `.env` 配置
3. Conda 环境安装
4. Django 初始化
5. 首次数据初始化
6. Django / Celery 启动
7. 生产托管建议
8. 日常维护命令

如果你现在要做的是“第一次把后端完整跑起来”，优先看：

- `docs/Deployment/backend_first_deploy_conda.md`

那份文档更细，包含：

- `.env` 字段怎么填
- PostgreSQL / Redis 准备
- 首次 `migrate`
- 股票代码表初始化
- 核心指数初始化
- logo 初始化
- Celery 启动
- 所有可选参数说明

## 1. 部署前准备

建议环境：

- 操作系统：Linux 优先，Windows 可用于开发和单机部署
- Python：`3.12.12`
- Conda 环境名：`Back_end_project`
- 基础服务：
  - PostgreSQL
  - Redis
- 仓库自带脚本默认会自动回溯到仓库根目录，即 `manage.py` 所在目录

代码目录示例：

```bash
/srv/mango_project
```

## 2. 拉取代码

```bash
cd /srv
git clone <your-repo-url> mango_project
cd mango_project
```

## 3. 配置 `.env`

先复制模板：

```bash
cp .env.example .env
```

Windows：

```powershell
Copy-Item .env.example .env
```

至少确认这些字段：

```env
DJANGO_SECRET_KEY=replace-with-a-random-secret
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,your.domain.com

DB_ENGINE=django.db.backends.postgresql
DB_NAME=mango_project_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=127.0.0.1
DB_PORT=5432

CELERY_BROKER_URL=pyamqp://mango:change-me@127.0.0.1:5672//

LOGO_DEV_IMAGE_BASE_URL=https://img.logo.dev
LOGO_DEV_PUBLISHABLE_KEY=
LOGO_DOWNLOAD_DIR=

SYNC_SYMBOLS_PROXY=
```

说明：

- `DJANGO_SECRET_KEY`：必须改
- `DJANGO_DEBUG`：生产环境必须是 `false`
- `DB_*`：必须改成真实 PostgreSQL 连接
- `CELERY_BROKER_URL`：必须指向真实 Celery Broker，当前推荐 RabbitMQ
- `LOGO_DEV_PUBLISHABLE_KEY`：需要 logo.dev 图片时建议填写

### 3.1 如果 PostgreSQL 跑在 Docker 中并需要向量存储

如果你后面要在 PostgreSQL 里存 embedding 或做向量检索，不要继续用纯 `postgres:18` 镜像，直接用带 `pgvector` 的镜像：

```bash
pgvector/pgvector:pg18-trixie
```

`docker run` 示例：

```bash
docker run -d \
  --name mango-postgres \
  --restart unless-stopped \
  -e POSTGRES_DB=mango_project_db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=your_password \
  -p 5432:5432 \
  -v mango_postgres_data:/var/lib/postgresql \
  pgvector/pgvector:pg18-trixie
```

如果你用 `docker compose`，核心改动只有一处：把 PostgreSQL 服务的镜像从 `postgres:18` 改成 `pgvector/pgvector:pg18-trixie`。

容器启动后，在目标数据库里执行一次：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

说明：

- 现有数据卷场景下，`docker-entrypoint-initdb.d` 不会重新执行，所以扩展要手工创建一次
- 选择 `pg18-trixie` 是为了尽量和 Debian 13 系的 PostgreSQL 18 数据目录保持一致，减少 collation mismatch 风险

### 3.2 如果你要把基础设施统一交给 Docker

仓库现在补了一份可直接启动的基础设施编排文件：

- `docker-compose.yml`
- `resource/deploy/docker-compose.infrastructure.yml`

它只负责三类基础服务：

- PostgreSQL，默认镜像是 `pgvector/pgvector:pg18-trixie`
- Redis，供 Django cache 使用
- RabbitMQ，供 Celery Broker 使用

启动方式：

```bash
cp docker-compose.env.example .env.compose
docker compose --env-file .env.compose up -d
```

说明：

- 这份 compose 只启动基础设施，不会把 Django 或 Celery 一起容器化
- Django 仍按本文档中的 Conda 方式运行，所以 `.env` 里的 `DB_HOST`、`DB_PORT`、`CELERY_BROKER_URL` 继续写 `127.0.0.1` 即可
- 如果你修改了 `docker-compose.env.example` 中的数据库或 RabbitMQ 账号，记得同步修改项目根目录 `.env`
## 4. 安装 Conda 环境和依赖

### 4.1 按 `environment.yml` 创建

```bash
conda env create -f environment.yml
```

如果环境已存在：

```bash
conda env update -f environment.yml --prune
```

### 4.2 重新安装 Python 依赖

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File resource/scripts/windows/install_python_deps_conda.ps1 -EnvName Back_end_project -UpgradePip
```

Linux / macOS：

```bash
bash resource/scripts/unix/install_python_deps_conda.sh --env-name Back_end_project --upgrade-pip
```

说明：

- `environment.yml` 会通过 `requirements.txt` 安装 Django、DRF、Celery、`drf-spectacular` 等运行依赖
- 安装脚本默认自动定位仓库根目录读取 `requirements.txt`
- 只有脚本被拷出仓库或从外部目录包装调用时，才需要显式传 `ProjectRoot/--project-root`

## 5. Django 初始化

```bash
conda run -n Back_end_project python manage.py migrate
conda run -n Back_end_project python manage.py collectstatic --noinput
```

如果需要后台管理员：

```bash
conda run -n Back_end_project python manage.py createsuperuser
```

## 6. 首次数据初始化

第一次部署建议至少完成：

1. `sync_symbols`
2. `sync_core_indices`
3. `sync_logo_data`

### 6.1 推荐方式：用一键脚本

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File resource/scripts/windows/bootstrap_first_run_conda.ps1 -EnvName Back_end_project -WithLogoSync
```

Linux / macOS：

```bash
bash resource/scripts/unix/bootstrap_first_run_conda.sh --env-name Back_end_project --with-logo-sync
```

脚本默认会做：

1. `migrate`
2. `sync_symbols`
3. 可选 `sync_logo_data`

注意：

- 默认 logo 初始化市场是：`us hk crypto`
- 如果你第一次部署就需要 A 股 logo，也要把 `cn` 加进去
- `sync_symbols --markets cn hk us` 会顺带补入核心指数
- 但我仍然建议第一次部署后再单独执行一次 `sync_core_indices`

### 6.2 首次部署时把 A 股 logo 一起初始化

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File resource/scripts/windows/bootstrap_first_run_conda.ps1 -EnvName Back_end_project -WithLogoSync -LogoMarkets us,hk,cn,crypto
```

Linux / macOS：

```bash
bash resource/scripts/unix/bootstrap_first_run_conda.sh --env-name Back_end_project --with-logo-sync --logo-markets "us hk cn crypto"
```

### 6.3 一次性手工执行

如果你不想走 bootstrap，也可以按顺序手工执行：

```bash
conda run -n Back_end_project python manage.py migrate
conda run -n Back_end_project python manage.py collectstatic --noinput
conda run -n Back_end_project python manage.py sync_symbols --markets cn hk us fx crypto
conda run -n Back_end_project python manage.py sync_core_indices --markets cn hk us
conda run -n Back_end_project python manage.py sync_logo_data --markets cn hk us crypto
```

## 7. 启动 Django

```bash
conda run -n Back_end_project python manage.py runserver 0.0.0.0:8000
```

## 8. 启动 Celery

当前一键脚本会先解析 Conda 环境里的 Python，再直接执行 `python -m celery`，不要求你先手工 `conda activate`。
默认日志目录是仓库根目录下的 `resource/tmp_celery_logs`。

### 8.1 Windows

启动：

```powershell
powershell -ExecutionPolicy Bypass -File resource/scripts/windows/start_celery.ps1 -EnvName Back_end_project -Targets all -WithBeat -FollowLogs
```

停止：

```powershell
powershell -ExecutionPolicy Bypass -File resource/scripts/windows/stop_celery.ps1
```

如果你更习惯双击或 `cmd` 直接启动，也可以用。`resource\scripts\windows\start_celery.bat` 默认就是：

- `Back_end_project`
- `all`
- `WithBeat`
- `FollowLogs`

命令如下：

```bat
resource\scripts\windows\start_celery.bat
resource\scripts\windows\stop_celery.bat
```

### 8.2 Linux / macOS

启动：

```bash
bash resource/scripts/unix/start_celery.sh --env-name Back_end_project --targets all --with-beat
```

停止：

```bash
bash resource/scripts/unix/stop_celery.sh
```

## 9. 生产托管建议

生产环境建议拆成 3 个服务：

1. Django Web
2. Celery Worker
3. Celery Beat

如果你使用 Linux，建议用 `systemd`。

如果你使用 macOS，建议用 `launchd`。

注意：

- `gunicorn` 已经作为平台条件依赖写入 `requirements.txt`
- Linux / macOS 安装依赖时会自动安装
- Windows 环境会自动跳过，不需要手工处理

## 10. Linux systemd 示例

### 10.1 `mango-web.service`

```ini
[Unit]
Description=Mango Django Web
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/srv/mango_project
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash -lc 'source /opt/conda/etc/profile.d/conda.sh && conda activate Back_end_project && gunicorn mango_project.wsgi:application --bind 0.0.0.0:8000 --workers 4 --timeout 120'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 10.2 `mango-celery-worker.service`

```ini
[Unit]
Description=Mango Celery Worker
After=network.target redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/srv/mango_project
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash -lc 'source /opt/conda/etc/profile.d/conda.sh && conda activate Back_end_project && celery -A mango_project worker -Q market_sync,snapshot_capture,snapshot_aggregate,snapshot_cleanup -l info'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 10.3 `mango-celery-beat.service`

```ini
[Unit]
Description=Mango Celery Beat
After=network.target redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/srv/mango_project
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash -lc 'source /opt/conda/etc/profile.d/conda.sh && conda activate Back_end_project && celery -A mango_project beat -l info'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mango-web mango-celery-worker mango-celery-beat
sudo systemctl status mango-web mango-celery-worker mango-celery-beat
```

## 11. 日常维护命令

### 11.1 更新股票 / 外汇 / 加密代码表

```bash
python manage.py sync_symbols --markets cn hk us fx crypto
```

只插入新代码，不覆盖已有代码：

```bash
python manage.py sync_symbols --markets cn hk us fx crypto --insert-only
```

### 11.2 更新核心指数代码表

如果你以后只更新指数，专门跑这个：

```bash
python manage.py sync_core_indices --markets cn hk us
```

对应文件：

`market/management/commands/sync_core_indices.py`

### 11.3 更新 logo URL 和主题色

更新 US / HK / Crypto：

```bash
python manage.py sync_logo_data --markets us hk crypto
```

更新 A 股 + 港股 + 美股 + 加密：

```bash
python manage.py sync_logo_data --markets cn hk us crypto
```

强制覆盖已有 logo：

```bash
python manage.py sync_logo_data --markets cn hk us crypto --force
```

### 11.4 交易日历说明

当前项目不再需要手工生成交易日日历。  
`US/CN/HK` 的开市判断运行时直接使用 `exchange_calendars`。

## 12. 常见排障

### 12.1 检查数据库

```bash
conda run -n Back_end_project python manage.py migrate --plan
```

Windows 上如果 `conda run` 报激活或临时文件错误，改用：

```powershell
& 'D:\Develop\Anaconda\shell\condabin\conda-hook.ps1'
conda activate Back_end_project
python manage.py migrate --plan
```

如果你启用了向量存储，再补一条 PostgreSQL 扩展检查：

```bash
docker exec mango-postgres psql -U postgres -d mango_project_db -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

如果结果为空，执行：

```bash
docker exec mango-postgres psql -U postgres -d mango_project_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 12.2 检查 Redis

```bash
redis-cli -h 127.0.0.1 -p 6379 ping
```

### 12.3 检查 Celery 日志

如果你用脚本启动，日志默认在：

```bash
resource/tmp_celery_logs/
```

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

## 13. 上线前检查清单

上线前至少确认：

1. `DJANGO_DEBUG=false`
2. `DJANGO_ALLOWED_HOSTS` 已填真实域名
3. `.env` 没有入库
4. PostgreSQL / Redis 可用
5. `migrate` 已完成
6. 股票代码表已初始化
7. 核心指数代码表已初始化
8. logo 已初始化
9. Django / Celery / Beat 能正常启动
10. 如果使用向量检索，`vector` 扩展已启用

## 14. 说明

这个文件是总指南。

如果你后面还要继续维护部署文档，建议按职责拆分：

1. `docs/Deployment/backend_first_deploy_conda.md`：第一次部署
2. `docs/Deployment/backend_deployment_guide.md`：总入口 + 生产托管
3. `market_data_snapshot_calendar_ops_guide_v2.md`：市场数据和 Celery 运维

