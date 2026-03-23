from celery import shared_task

from market.services.refresh.refresh_all import refresh_all


@shared_task(name="market.tasks.task_refresh_all")
def task_refresh_all(force_full_fetch: bool = False):
    return refresh_all(force_full_fetch=force_full_fetch)
