from celery import shared_task

from snapshot.models import SnapshotLevel
from snapshot.services import aggregate_snapshots, capture_snapshots, cleanup_expired_snapshots


@shared_task
def task_capture_m15_snapshots():
    return capture_snapshots(level=SnapshotLevel.M15)


@shared_task
def task_aggregate_h4_snapshots():
    return aggregate_snapshots(level=SnapshotLevel.H4)


@shared_task
def task_aggregate_d1_snapshots():
    return aggregate_snapshots(level=SnapshotLevel.D1)


@shared_task
def task_aggregate_mon1_snapshots():
    return aggregate_snapshots(level=SnapshotLevel.MON1)


@shared_task
def task_cleanup_snapshot_history():
    return cleanup_expired_snapshots()
