from celery import shared_task

from market.services.snapshot.sync import sync_watchlist_snapshot


@shared_task
def task_pull_watchlist_quotes():
    return sync_watchlist_snapshot()
