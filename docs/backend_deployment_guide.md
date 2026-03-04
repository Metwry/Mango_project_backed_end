# 后端部署文档（Django + Celery + Redis + PostgreSQL）

## 1. 部署前准备
- 操作系统：建议 Linux（Ubuntu 22.04+/Debian 12+）
- Python 环境：Conda 环境名 `Back_end_project`，Python 固定为 `3.12.12`
- 基础服务：`PostgreSQL`、`Redis`
- 代码目录示例：`/srv/mango_project`

## 2. 拉取代码
```bash
cd /srv
git clone <your-repo-url> mango_project
cd mango_project
```

## 3. 配置环境变量
1. 复制模板：
```bash
cp .env.example .env
```
2. 编辑 `.env`，至少确认以下字段：
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=false`
- `DJANGO_ALLOWED_HOSTS=your.domain.com,127.0.0.1`
- `DB_*`（数据库连接）
- `EMAIL_*`（如需发邮件）
- `CELERY_BROKER_URL`（Redis 地址）

## 4. 安装 Python 依赖

### 4.0 创建/复现 Conda 环境（推荐）
```bash
conda env create -f environment.yml
```
如果环境已存在，更新环境：
```bash
conda env update -f environment.yml --prune
```

### 4.1 Windows (PowerShell)
```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_python_deps_conda.ps1 -EnvName Back_end_project -UpgradePip
```

### 4.2 Linux / macOS (bash)
```bash
bash scripts/install_python_deps_conda.sh --env-name Back_end_project --upgrade-pip
```

## 5. Django 初始化
```bash
conda run -n Back_end_project python manage.py migrate
conda run -n Back_end_project python manage.py collectstatic --noinput
```

如需后台管理员：
```bash
conda run -n Back_end_project python manage.py createsuperuser
```

## 6. 首次数据初始化（必做）

首次部署建议先完成：
- 建立股票/外汇/加密标的代码库（`sync_symbols`）
- 生成交易日历 CSV（`build_market_calendar_csv`）
- （可选）同步 logo 元数据（`sync_logo_data`）

### 6.1 Windows (PowerShell)
```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_first_run_conda.ps1 -EnvName Back_end_project -WithLogoSync
```

### 6.2 Linux / macOS (bash)
```bash
bash scripts/bootstrap_first_run_conda.sh --env-name Back_end_project --with-logo-sync
```

可选参数：
- 指定日历范围：`--start-date YYYY-MM-DD --end-date YYYY-MM-DD`（PowerShell 对应 `-StartDate/-EndDate`）
- 跳过某一步：`--skip-migrate` / `--skip-symbols` / `--skip-calendar`

## 7. 本机验证启动（手工）

### 7.1 启动 Django
```bash
conda run -n Back_end_project python manage.py runserver 0.0.0.0:8000
```

### 7.2 启动 Celery（Linux/macOS）
```bash
bash scripts/start_celery_stack.sh --targets all --with-beat
```
停止：
```bash
bash scripts/stop_celery_stack.sh
```

### 7.3 启动 Celery（Windows）
```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_celery_stack.ps1 -Targets all -WithBeat -FollowLogs
```
停止：
```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop_celery_stack.ps1
```

## 8. 生产部署建议（systemd）

建议至少拆成 3 个服务：
- Django Web（建议 gunicorn/uvicorn）
- Celery Worker
- Celery Beat

> 说明：当前 `requirements.txt` 不含 `gunicorn`，若使用 gunicorn，请先安装：
```bash
conda run -n Back_end_project python -m pip install gunicorn
```

### 8.1 `/etc/systemd/system/mango-web.service`
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

### 8.2 `/etc/systemd/system/mango-celery-worker.service`
```ini
[Unit]
Description=Mango Celery Worker
After=network.target redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/srv/mango_project
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash -lc 'source /opt/conda/etc/profile.d/conda.sh && conda activate Back_end_project && celery -A mango_project worker -l info'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 8.3 `/etc/systemd/system/mango-celery-beat.service`
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

### 8.4 systemd 启用
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mango-web mango-celery-worker mango-celery-beat
sudo systemctl status mango-web mango-celery-worker mango-celery-beat
```

## 9. macOS 部署建议（launchd）

macOS 没有 `systemd`，建议使用 `launchd` 托管进程。

### 9.1 准备目录
```bash
mkdir -p ~/Library/LaunchAgents
mkdir -p /Users/<your_user>/mango_project/tmp_celery_logs
```

### 9.2 `~/Library/LaunchAgents/com.mango.web.plist`
> 把下面路径替换为你的真实路径（`/Users/<your_user>/mango_project`）。
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.mango.web</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>/Users/<your_user>/mango_project</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>source /opt/anaconda3/etc/profile.d/conda.sh && conda activate Back_end_project && gunicorn mango_project.wsgi:application --bind 0.0.0.0:8000 --workers 4 --timeout 120</string>
  </array>
  <key>StandardOutPath</key><string>/Users/<your_user>/mango_project/tmp_celery_logs/web.out.log</string>
  <key>StandardErrorPath</key><string>/Users/<your_user>/mango_project/tmp_celery_logs/web.err.log</string>
</dict>
</plist>
```

### 9.3 `~/Library/LaunchAgents/com.mango.celery.worker.plist`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.mango.celery.worker</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>/Users/<your_user>/mango_project</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>source /opt/anaconda3/etc/profile.d/conda.sh && conda activate Back_end_project && celery -A mango_project worker -l info</string>
  </array>
  <key>StandardOutPath</key><string>/Users/<your_user>/mango_project/tmp_celery_logs/celery_worker.out.log</string>
  <key>StandardErrorPath</key><string>/Users/<your_user>/mango_project/tmp_celery_logs/celery_worker.err.log</string>
</dict>
</plist>
```

### 9.4 `~/Library/LaunchAgents/com.mango.celery.beat.plist`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.mango.celery.beat</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>/Users/<your_user>/mango_project</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>source /opt/anaconda3/etc/profile.d/conda.sh && conda activate Back_end_project && celery -A mango_project beat -l info</string>
  </array>
  <key>StandardOutPath</key><string>/Users/<your_user>/mango_project/tmp_celery_logs/celery_beat.out.log</string>
  <key>StandardErrorPath</key><string>/Users/<your_user>/mango_project/tmp_celery_logs/celery_beat.err.log</string>
</dict>
</plist>
```

### 9.5 launchctl 启动与管理
```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.mango.web.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.mango.celery.worker.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.mango.celery.beat.plist

launchctl kickstart -k "gui/$(id -u)/com.mango.web"
launchctl kickstart -k "gui/$(id -u)/com.mango.celery.worker"
launchctl kickstart -k "gui/$(id -u)/com.mango.celery.beat"
```

卸载：
```bash
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.mango.web.plist
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.mango.celery.worker.plist
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.mango.celery.beat.plist
```

## 10. 常用排障
- 查看 Django/Celery 服务日志：
```bash
sudo journalctl -u mango-web -f
sudo journalctl -u mango-celery-worker -f
sudo journalctl -u mango-celery-beat -f
```
- macOS `launchd` 日志查看（若上文按示例输出到文件）：
```bash
tail -f /Users/<your_user>/mango_project/tmp_celery_logs/web.err.log
tail -f /Users/<your_user>/mango_project/tmp_celery_logs/celery_worker.err.log
tail -f /Users/<your_user>/mango_project/tmp_celery_logs/celery_beat.err.log
```
- 检查 Redis 连通：
```bash
redis-cli -h 127.0.0.1 -p 6379 ping
```
- 检查数据库连通：使用 `psql` 或执行
```bash
conda run -n Back_end_project python manage.py migrate --plan
```

## 11. 上线前检查清单
- `DJANGO_DEBUG=false`
- `DJANGO_ALLOWED_HOSTS` 已配置域名
- `.env` 不入库
- PostgreSQL/Redis 已设置开机自启
- Django、Celery、Beat 已由 systemd（Linux）或 launchd（macOS）托管
