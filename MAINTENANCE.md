# Mango Backend 维护手册

版本：`V1.0.0`

更新时间：2026-03-11

相关项目文档：

- [README.md](README.md)
- [README.zh-CN.md](README.zh-CN.md)
- [README.en.md](README.en.md)

## 1. 当前部署基线

- 运行目录：`/Users/wry/Services/Mango_project/Mango_project_backed_end`
- Python 环境：`/opt/anaconda3/envs/Back_end_project`
- Web 端口：`8000`
- Redis：`127.0.0.1:6379`
- PostgreSQL：`127.0.0.1:5432`

系统级 LaunchDaemon 标签：

- `cc.mango.redis`
- `cc.mango.postgresql16`
- `cc.mango.backend.web`
- `cc.mango.backend.celery.worker`
- `cc.mango.backend.celery.beat`

## 2. 快速健康检查

```bash
redis-cli ping
/opt/homebrew/opt/postgresql@16/bin/pg_isready -h 127.0.0.1 -p 5432
curl -I http://127.0.0.1:8000
```

查看服务状态：

```bash
sudo launchctl print system/cc.mango.backend.web | rg "state =|pid =|last exit code"
sudo launchctl print system/cc.mango.backend.celery.worker | rg "state =|pid =|last exit code"
sudo launchctl print system/cc.mango.backend.celery.beat | rg "state =|pid =|last exit code"
sudo launchctl print system/cc.mango.redis | rg "state =|pid =|last exit code"
sudo launchctl print system/cc.mango.postgresql16 | rg "state =|pid =|last exit code"
```

## 3. 日常发布流程（改代码后）

建议直接在运行目录开发和发布：

```bash
cd /Users/wry/Services/Mango_project/Mango_project_backed_end
```

标准发布步骤：

```bash
git pull
conda run -n Back_end_project pip install -r requirements.txt
conda run -n Back_end_project python manage.py migrate
sudo launchctl kickstart -k system/cc.mango.backend.web
sudo launchctl kickstart -k system/cc.mango.backend.celery.worker
sudo launchctl kickstart -k system/cc.mango.backend.celery.beat
```

如果你仍在 `Desktop/...` 目录改代码，先同步到运行目录：

```bash
rsync -a --delete --exclude '.git' \
  /Users/wry/Desktop/Services/Mango_project/Mango_project_backed_end/ \
  /Users/wry/Services/Mango_project/Mango_project_backed_end/
```

## 4. 按场景重启命令

只改 Django 接口代码：

```bash
sudo launchctl kickstart -k system/cc.mango.backend.web
```

改 Celery 任务逻辑：

```bash
sudo launchctl kickstart -k system/cc.mango.backend.celery.worker
```

改 Celery 定时策略（beat schedule）：

```bash
sudo launchctl kickstart -k system/cc.mango.backend.celery.beat
```

改 `.env`、认证、缓存、数据库连接参数：

```bash
sudo launchctl kickstart -k system/cc.mango.backend.web
sudo launchctl kickstart -k system/cc.mango.backend.celery.worker
sudo launchctl kickstart -k system/cc.mango.backend.celery.beat
```

改 Redis/PostgreSQL 配置：

```bash
sudo launchctl kickstart -k system/cc.mango.redis
sudo launchctl kickstart -k system/cc.mango.postgresql16
```

## 5. 日志查看

Web：

```bash
tail -f /Users/wry/Services/Mango_project/Mango_project_backed_end/tmp_celery_logs/web.err.log
tail -f /Users/wry/Services/Mango_project/Mango_project_backed_end/tmp_celery_logs/web.out.log
```

Celery Worker：

```bash
tail -f /Users/wry/Services/Mango_project/Mango_project_backed_end/tmp_celery_logs/celery_worker.err.log
tail -f /Users/wry/Services/Mango_project/Mango_project_backed_end/tmp_celery_logs/celery_worker.out.log
```

Celery Beat：

```bash
tail -f /Users/wry/Services/Mango_project/Mango_project_backed_end/tmp_celery_logs/celery_beat.err.log
tail -f /Users/wry/Services/Mango_project/Mango_project_backed_end/tmp_celery_logs/celery_beat.out.log
```

Redis/PostgreSQL：

```bash
tail -f /opt/homebrew/var/log/redis.log
tail -f /opt/homebrew/var/log/postgresql@16.log
```

## 6. 修改启动配置后如何生效

如果你改了这些文件，需要重新安装 system LaunchDaemons：

- `deploy/launchd/*.plist`
- `scripts/start_web.sh`
- `scripts/start_celery_worker.sh`
- `scripts/start_celery_beat.sh`

执行：

```bash
cd /Users/wry/Services/Mango_project/Mango_project_backed_end
sudo bash scripts/install_system_launchdaemons.sh
```

## 7. 常见问题

`curl -I http://127.0.0.1:8000` 返回 `400 Bad Request`：

- 服务通常是正常的，常见原因是 `ALLOWED_HOSTS` 限制。

服务起不来：

- 先看 `launchctl print system/<label>`
- 再看对应日志文件。

## 8. 重启/断电恢复验证

系统重启后执行：

```bash
redis-cli ping
/opt/homebrew/opt/postgresql@16/bin/pg_isready -h 127.0.0.1 -p 5432
curl -I http://127.0.0.1:8000
```

如果三条都通过，说明“开机自动恢复运行”正常。
