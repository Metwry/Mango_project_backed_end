from typing import Any


def _format_log_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _format_log_fields(**fields: Any) -> str:
    items = []
    for key in sorted(fields.keys()):
        items.append(f"{key}={_format_log_value(fields[key])}")
    return " ".join(items)


def log_info(logger, event: str, **fields: Any) -> None:
    payload = _format_log_fields(**fields)
    if payload:
        logger.info("%s %s", event, payload)
        return
    logger.info("%s", event)
