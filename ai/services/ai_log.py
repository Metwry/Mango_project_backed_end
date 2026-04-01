from __future__ import annotations

import json
import logging
from datetime import datetime
from time import perf_counter
from typing import Any

from django.utils import timezone


LOGGER_NAME = "ai_log"


def get_ai_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def log_ai_event(
    *,
    event: str,
    status: str,
    duration_ms: float,
    **extra: Any,
) -> None:
    payload = {
        "timestamp": timezone.localtime(timezone.now()).isoformat(),
        "event": event,
        "status": status,
        "duration_ms": round(duration_ms, 2),
    }
    payload.update({key: value for key, value in extra.items() if value is not None})

    logger = get_ai_logger()
    message = json.dumps(payload, ensure_ascii=False, default=_json_default)
    if status == "error":
        logger.error(message)
    else:
        logger.info(message)


class AILogScope:
    def __init__(self, *, event: str, **fields: Any) -> None:
        self.event = event
        self.fields = {key: value for key, value in fields.items() if value is not None}
        self.started_at = perf_counter()
        self._logged = False

    def set(self, **fields: Any) -> None:
        self.fields.update({key: value for key, value in fields.items() if value is not None})

    def log(self, *, status: str, **fields: Any) -> None:
        self.set(**fields)
        log_ai_event(
            event=self.event,
            status=status,
            duration_ms=(perf_counter() - self.started_at) * 1000,
            **self.fields,
        )
        self._logged = True

    def __enter__(self) -> AILogScope:
        return self

    def __exit__(self, exc_type: Any, exc: Exception | None, tb: Any) -> bool:
        if self._logged:
            return False
        if exc is not None:
            self.log(status="error", error=str(exc))
        else:
            self.log(status="success")
        return False


def ai_log_scope(*, event: str, **fields: Any) -> AILogScope:
    return AILogScope(event=event, **fields)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
