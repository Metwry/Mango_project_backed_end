from __future__ import annotations

import re

from news.utils.text_filters import is_noise_paragraph, is_tail_cutoff


BLOCK_SPLIT_RE = re.compile(r"\n\s*\n+")
HEADING_PREFIX_RE = re.compile(r"^#{1,6}\s+")
LIST_PREFIX_RE = re.compile(r"^(?:[-*+]\s+|\d+\.\s+)")
BLOCKQUOTE_PREFIX_RE = re.compile(r"^>\s+")
CAPTION_PREFIX_RE = re.compile(r"^\[caption\]\s*", re.I)


def clean_stored_article_content(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    cleaned_blocks: list[str] = []
    for raw_block in BLOCK_SPLIT_RE.split(normalized):
        block = raw_block.strip()
        if not block:
            continue

        plain_text = _normalize_block_for_matching(block)
        if is_tail_cutoff(plain_text):
            break
        if is_noise_paragraph(plain_text):
            continue

        cleaned_blocks.append(block)

    return "\n\n".join(cleaned_blocks).strip()


def _normalize_block_for_matching(block: str) -> str:
    text = block.strip()
    text = HEADING_PREFIX_RE.sub("", text)
    text = BLOCKQUOTE_PREFIX_RE.sub("", text)
    text = CAPTION_PREFIX_RE.sub("", text)
    text = LIST_PREFIX_RE.sub("", text)
    return " ".join(part.strip() for part in text.splitlines() if part.strip())
