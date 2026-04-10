from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def iter_message_text(message: Any) -> Iterator[str]:
    content = getattr(message, "content", None)

    if isinstance(content, str):
        if content:
            yield content
        return

    if isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                if item:
                    yield item
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    yield text


def iter_agent_stream_text(chunk: Any) -> Iterator[str]:
    if isinstance(chunk, tuple) and len(chunk) == 2:
        message, metadata = chunk
    elif isinstance(chunk, dict) and chunk.get("type") == "messages":
        data = chunk.get("data")
        if not isinstance(data, tuple) or len(data) != 2:
            return
        message, metadata = data
    else:
        return

    if not isinstance(metadata, dict) or metadata.get("langgraph_node") != "model":
        return

    yield from iter_message_text(message)
