from __future__ import annotations

import hashlib
import re


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_content_for_hash(content: str) -> str:
    normalized_lines: list[str] = []
    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _WHITESPACE_RE.sub(" ", raw_line).strip()
        if line:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)


def calculate_content_md5(content: str) -> str:
    normalized = normalize_content_for_hash(content)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()
