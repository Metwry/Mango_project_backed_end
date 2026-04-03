import os
import logging

from celery import Celery
from celery.signals import beat_init
from common.celery_task_logging import register_task_logging


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mango_project.settings")

app = Celery("mango_project")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
register_task_logging()

logger = logging.getLogger(__name__)


@beat_init.connect
def trigger_startup_market_sync(sender=None, **kwargs):
    try:
        app.send_task(
            "market.tasks.task_refresh_all",
            kwargs={"force_full_fetch": True},
            queue="market_sync",
        )
        logger.warning("beat 启动完成，已投递一次全市场初始化行情拉取任务")
    except Exception:
        logger.exception("beat 启动初始化行情拉取任务投递失败")
