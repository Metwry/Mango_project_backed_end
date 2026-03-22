from celery import shared_task

from market.services.data.sync import pull_data


@shared_task(name="market.tasks.task_pull_data")
def task_pull_data():
    return pull_data()
