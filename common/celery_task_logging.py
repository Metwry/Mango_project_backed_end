from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from celery.signals import task_failure, task_postrun, task_prerun, task_retry


_REGISTERED = False


def _task_log_dir() -> Path:
    raw = os.getenv("CELERY_LOG_DIR", "").strip()
    if raw:
        path = Path(raw)
    else:
        path = Path(__file__).resolve().parents[1] / "resource" / "tmp_celery_logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _task_log_filename(task_name: str) -> str:
    parts = task_name.split(".")
    app_name = parts[0] if parts else "unknown"
    raw_name = parts[-1] if parts else task_name
    short_name = raw_name[5:] if raw_name.startswith("task_") else raw_name
    return f"{app_name}.{short_name}.log"


def _task_logger(task_name: str) -> logging.Logger:
    logger_name = f"celery.task.{task_name}"
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    log_path = _task_log_dir() / _task_log_filename(task_name)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _format_task_payload(task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    return f"id={task_id} args={args!r} kwargs={kwargs!r}"


def log_task_prerun(
    sender=None,
    task_id: str | None = None,
    task=None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    **extras,
) -> None:
    task_name = getattr(task, "name", None) or getattr(sender, "name", "unknown")
    _task_logger(task_name).info(
        "task.start %s",
        _format_task_payload(task_id or "", args or (), kwargs or {}),
    )


def log_task_postrun(
    sender=None,
    task_id: str | None = None,
    task=None,
    retval: Any = None,
    state: str | None = None,
    **extras,
) -> None:
    task_name = getattr(task, "name", None) or getattr(sender, "name", "unknown")
    _task_logger(task_name).info(
        "task.finish id=%s state=%s retval=%r",
        task_id or "",
        state or "",
        retval,
    )


def log_task_retry(
    sender=None,
    request=None,
    reason: BaseException | None = None,
    **extras,
) -> None:
    task_name = getattr(sender, "name", "unknown")
    _task_logger(task_name).warning(
        "task.retry id=%s reason=%r",
        getattr(request, "id", ""),
        reason,
    )


def log_task_failure(
    sender=None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    **extras,
) -> None:
    task_name = getattr(sender, "name", "unknown")
    _task_logger(task_name).exception(
        "task.failure %s error=%r",
        _format_task_payload(task_id or "", args or (), kwargs or {}),
        exception,
    )


def register_task_logging() -> None:
    global _REGISTERED
    if _REGISTERED:
        return

    task_prerun.connect(
        log_task_prerun,
        weak=False,
        dispatch_uid="common.celery_task_logging.task_prerun",
    )
    task_postrun.connect(
        log_task_postrun,
        weak=False,
        dispatch_uid="common.celery_task_logging.task_postrun",
    )
    task_retry.connect(
        log_task_retry,
        weak=False,
        dispatch_uid="common.celery_task_logging.task_retry",
    )
    task_failure.connect(
        log_task_failure,
        weak=False,
        dispatch_uid="common.celery_task_logging.task_failure",
    )
    _REGISTERED = True
