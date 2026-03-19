from typing import Any


# 将日志字段值标准化为适合结构化日志输出的字符串。
def _format_log_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# 将键值字段按固定顺序拼接为日志扩展字段字符串。
def _format_log_fields(**fields: Any) -> str:
    items = []
    for key in sorted(fields.keys()):
        items.append(f"{key}={_format_log_value(fields[key])}")
    return " ".join(items)


# 输出带事件名和扩展字段的 info 级日志。
def log_info(logger, event: str, **fields: Any) -> None:
    payload = _format_log_fields(**fields)
    if payload:
        logger.info("%s %s", event, payload)
        return
    logger.info("%s", event)
