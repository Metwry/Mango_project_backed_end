import os
import logging

from celery import Celery
from celery.signals import worker_ready
from shared.logging_utils import log_info


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mango_project.settings")

app = Celery("mango_project")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

logger = logging.getLogger(__name__)
STARTUP_PULL_LOCK_KEY = "watchlist:quotes:startup-pull-lock"


@worker_ready.connect
def trigger_startup_pull(sender=None, **kwargs):
    """
    worker 启动后立即触发一次补拉。
    用 Redis 锁防止多 worker 同时启动造成重复触发。
    """
    try:
        from django.core.cache import cache

        if not cache.add(STARTUP_PULL_LOCK_KEY, "1", timeout=300):
            log_info(logger, "worker.startup.pull.skipped", reason="lock_exists")
            return

        app.send_task("market.tasks.task_pull_watchlist_quotes")
        logger.warning("worker 启动完成，已立即触发一次行情补拉任务")
    except Exception:
        logger.exception("worker 启动补拉触发失败")
