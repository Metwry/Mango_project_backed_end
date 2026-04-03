from __future__ import annotations

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup, NavigableString, Tag

from news.utils.cleanup import clean_stored_article_content
from news.utils.hash import calculate_content_md5
from news.utils.text_filters import is_noise_paragraph, is_tail_cutoff


RSS_URL = "https://finance.yahoo.com/news/rss"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
}
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)
DEFAULT_LIMIT = 50
DEFAULT_CONCURRENCY = 10
DEFAULT_FETCH_RETRY_ATTEMPTS = 3
DEFAULT_FETCH_RETRY_BASE_DELAY = 1.0
SUPPORTED_HOSTS = {"finance.yahoo.com"}
SKIP_TAGS = {
    "button",
    "canvas",
    "footer",
    "form",
    "header",
    "iframe",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
}
BLOCK_TAGS = {
    "blockquote",
    "figcaption",
    "ol",
    "p",
    "table",
    "ul",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}
BlockType = Literal["heading", "paragraph", "list", "table", "blockquote", "figure_caption"]


@dataclass
class ContentBlock:
    type: BlockType


@dataclass
class HeadingBlock(ContentBlock):
    level: int
    text: str


@dataclass
class ParagraphBlock(ContentBlock):
    text: str


@dataclass
class ListBlock(ContentBlock):
    ordered: bool
    items: list[str]


@dataclass
class TableBlock(ContentBlock):
    headers: list[str]
    rows: list[list[str]]


@dataclass
class BlockquoteBlock(ContentBlock):
    text: str


@dataclass
class FigureCaptionBlock(ContentBlock):
    text: str


@dataclass(slots=True)
class PreparedNewsArticle:
    provider: str
    source: str
    article_url: str
    title: str
    content: str
    content_hash: str
    language: str
    published: datetime
    fetched_at: datetime
    blocks: list[ContentBlock] = field(default_factory=list)


def normalize_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_supported_article_url(url: str) -> bool:
    return urlparse(url).netloc in SUPPORTED_HOSTS


def parse_rss_items(rss_xml: str, limit: int | None = None) -> list[dict[str, str]]:
    root = ET.fromstring(rss_xml)
    items = root.findall("./channel/item")
    if not items:
        raise ValueError("RSS feed does not contain any article item.")

    parsed_items: list[dict[str, str]] = []
    for item in items:
        source_node = item.find("source")
        link = (item.findtext("link") or "").strip()
        if not is_supported_article_url(link):
            continue
        parsed_items.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "link": link,
                "published_at": (item.findtext("pubDate") or "").strip(),
                "source": (source_node.text or "").strip() if source_node is not None else "",
            }
        )
        if limit is not None and len(parsed_items) >= limit:
            break

    return parsed_items


def extract_article_root(page_html: str) -> Tag:
    soup = BeautifulSoup(page_html, "lxml")
    article = soup.find("article")
    if article is None:
        raise ValueError("Could not find article content in page HTML.")
    return article


def should_skip_tag(tag: Tag) -> bool:
    if tag.name in SKIP_TAGS:
        return True

    classes = " ".join(tag.get("class", []))
    if any(token in classes.lower() for token in ("ad", "advert", "carousel", "related", "share")):
        return True

    return False


def iter_block_tags(node: Tag) -> list[Tag]:
    blocks: list[Tag] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            continue
        if not isinstance(child, Tag) or should_skip_tag(child):
            continue
        if child.name in BLOCK_TAGS:
            blocks.append(child)
            continue
        blocks.extend(iter_block_tags(child))
    return blocks


def extract_text_from_tag(tag: Tag) -> str:
    return normalize_text(tag.get_text(" ", strip=True))


def build_paragraph_block(tag: Tag) -> ParagraphBlock | None:
    text = extract_text_from_tag(tag)
    if not text:
        return None
    return ParagraphBlock(type="paragraph", text=text)


def build_heading_block(tag: Tag) -> HeadingBlock | None:
    text = extract_text_from_tag(tag)
    if not text:
        return None
    level = int(tag.name[1]) if len(tag.name) == 2 and tag.name[1].isdigit() else 2
    return HeadingBlock(type="heading", level=level, text=text)


def build_blockquote_block(tag: Tag) -> BlockquoteBlock | None:
    text = extract_text_from_tag(tag)
    if not text:
        return None
    return BlockquoteBlock(type="blockquote", text=text)


def build_figure_caption_block(tag: Tag) -> FigureCaptionBlock | None:
    text = extract_text_from_tag(tag)
    if not text:
        return None
    return FigureCaptionBlock(type="figure_caption", text=text)


def extract_list_item_text(item: Tag) -> str:
    parts: list[str] = []
    for child in item.contents:
        if isinstance(child, NavigableString):
            text = normalize_text(str(child))
            if text:
                parts.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        if child.name in {"ul", "ol"}:
            continue
        text = extract_text_from_tag(child)
        if text:
            parts.append(text)
    joined = normalize_text(" ".join(parts))
    return joined or extract_text_from_tag(item)


def build_list_block(tag: Tag) -> ListBlock | None:
    items: list[str] = []
    for item in tag.find_all("li", recursive=False):
        text = extract_list_item_text(item)
        if text:
            items.append(text)
    if not items:
        return None
    return ListBlock(type="list", ordered=tag.name == "ol", items=items)


def extract_table_row_cells(row: Tag) -> tuple[list[str], bool]:
    cells = row.find_all(["th", "td"], recursive=False)
    if not cells:
        cells = row.find_all(["th", "td"])
    values = [extract_text_from_tag(cell) for cell in cells]
    values = [value for value in values if value]
    is_header = bool(cells) and all(cell.name == "th" for cell in cells)
    return values, is_header


def build_table_block(tag: Tag) -> TableBlock | None:
    parsed_rows: list[tuple[list[str], bool]] = []
    for row in tag.find_all("tr"):
        values, is_header = extract_table_row_cells(row)
        if values:
            parsed_rows.append((values, is_header))

    if not parsed_rows:
        return None

    headers: list[str] = []
    rows: list[list[str]] = []
    for index, (values, is_header) in enumerate(parsed_rows):
        if index == 0 and is_header:
            headers = values
            continue
        rows.append(values)

    if not headers and rows:
        first_row = rows[0]
        if len(rows) > 1 and len(first_row) == len(rows[1]) and len(first_row) > 1:
            headers = first_row
            rows = rows[1:]

    if not headers and not rows:
        rows = [parsed_rows[0][0]]

    return TableBlock(type="table", headers=headers, rows=rows)


def convert_tag_to_block(tag: Tag) -> ContentBlock | None:
    if tag.name == "p":
        return build_paragraph_block(tag)
    if tag.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return build_heading_block(tag)
    if tag.name in {"ul", "ol"}:
        return build_list_block(tag)
    if tag.name == "table":
        return build_table_block(tag)
    if tag.name == "blockquote":
        return build_blockquote_block(tag)
    if tag.name == "figcaption":
        return build_figure_caption_block(tag)
    return None


def block_primary_text(block: ContentBlock) -> str:
    if isinstance(block, TableBlock):
        parts = list(block.headers)
        parts.extend(cell for row in block.rows for cell in row)
        return " ".join(parts)
    if isinstance(block, ListBlock):
        return " ".join(block.items)
    return block.text


def clean_blocks(blocks: list[ContentBlock], article_title: str | None = None) -> list[ContentBlock]:
    cleaned: list[ContentBlock] = []
    previous_text: str | None = None
    normalized_title = normalize_text(article_title or "").lower()

    for block in blocks:
        if isinstance(block, HeadingBlock):
            if normalize_text(block.text).lower() == normalized_title:
                continue
            text = block.text
            if is_tail_cutoff(text):
                break
            if text and text != previous_text:
                cleaned.append(block)
                previous_text = text
            continue

        if isinstance(block, ParagraphBlock):
            text = block.text
            if is_tail_cutoff(text):
                break
            if is_noise_paragraph(text):
                continue
            if text != previous_text:
                cleaned.append(block)
                previous_text = text
            continue

        if isinstance(block, ListBlock):
            items = [item for item in block.items if not is_noise_paragraph(item)]
            if not items:
                continue
            if any(is_tail_cutoff(item) for item in items):
                break
            normalized = " ".join(items)
            if normalized != previous_text:
                cleaned.append(ListBlock(type="list", ordered=block.ordered, items=items))
                previous_text = normalized
            continue

        text = block_primary_text(block)
        if is_tail_cutoff(text):
            break
        if text and text != previous_text:
            cleaned.append(block)
            previous_text = text

    return cleaned


def extract_article_blocks(page_html: str, article_title: str | None = None) -> list[ContentBlock]:
    article_root = extract_article_root(page_html)
    raw_blocks = [
        block
        for block in (convert_tag_to_block(tag) for tag in iter_block_tags(article_root))
        if block is not None
    ]
    blocks = clean_blocks(raw_blocks, article_title=article_title)
    if not blocks:
        raise ValueError("Article page was found, but no structured content was extracted.")
    return blocks


def escape_table_cell(text: str) -> str:
    return text.replace("|", "\\|")


def normalize_row_width(row: list[str], width: int) -> list[str]:
    return row + [""] * (width - len(row))


def render_table_block(block: TableBlock) -> str:
    width = max(len(block.headers), *(len(row) for row in block.rows), 0)
    if width == 0:
        return ""

    if block.headers:
        headers = normalize_row_width(block.headers, width)
        lines = [
            "| " + " | ".join(escape_table_cell(cell) for cell in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in block.rows:
            padded = normalize_row_width(row, width)
            lines.append("| " + " | ".join(escape_table_cell(cell) for cell in padded) + " |")
        return "\n".join(lines)

    lines = ["[Table]"]
    for row in block.rows:
        lines.append("- " + " | ".join(escape_table_cell(cell) for cell in row))
    return "\n".join(lines)


def render_blocks_text(blocks: list[ContentBlock]) -> str:
    rendered: list[str] = []
    for block in blocks:
        if isinstance(block, HeadingBlock):
            level = max(2, min(block.level, 6))
            rendered.append(f"{'#' * level} {block.text}")
            continue
        if isinstance(block, ParagraphBlock):
            rendered.append(block.text)
            continue
        if isinstance(block, ListBlock):
            marker_template = "{index}. " if block.ordered else "- "
            for index, item in enumerate(block.items, start=1):
                rendered.append(marker_template.format(index=index) + item)
            continue
        if isinstance(block, TableBlock):
            table_text = render_table_block(block)
            if table_text:
                rendered.append(table_text)
            continue
        if isinstance(block, BlockquoteBlock):
            rendered.append(f"> {block.text}")
            continue
        if isinstance(block, FigureCaptionBlock):
            rendered.append(f"[Caption] {block.text}")

    text = "\n\n".join(part for part in rendered if part).strip()
    if not text:
        raise ValueError("Structured content was extracted, but text rendering produced no content.")
    return text


def extract_article_text(page_html: str, article_title: str | None = None) -> str:
    return render_blocks_text(extract_article_blocks(page_html, article_title=article_title))


def parse_published_at(value: str) -> datetime:
    raw_value = str(value).strip()
    if not raw_value:
        raise ValueError("published_at is empty")

    try:
        parsed = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError):
        iso_value = raw_value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(iso_value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


def prepare_article(item: dict[str, str], *, content: str, blocks: list[ContentBlock]) -> PreparedNewsArticle:
    cleaned_content = clean_stored_article_content(content)
    return PreparedNewsArticle(
        provider="yahoo",
        source=item["source"],
        article_url=item["link"],
        title=item["title"],
        content=cleaned_content,
        content_hash=calculate_content_md5(cleaned_content),
        language="en",
        published=parse_published_at(item["published_at"]),
        fetched_at=datetime.now(dt_timezone.utc),
        blocks=blocks,
    )


async def fetch_text(
    session: aiohttp.ClientSession,
    url: str,
    *,
    retry_attempts: int = DEFAULT_FETCH_RETRY_ATTEMPTS,
    retry_base_delay: float = DEFAULT_FETCH_RETRY_BASE_DELAY,
) -> str:
    last_exc: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            async with session.get(url, timeout=DEFAULT_TIMEOUT) as response:
                response.raise_for_status()
                return await response.text()
        except (
            aiohttp.ClientPayloadError,
            aiohttp.ClientConnectionError,
            aiohttp.ClientResponseError,
            asyncio.TimeoutError,
            ConnectionResetError,
        ) as exc:
            last_exc = exc
            if attempt >= retry_attempts:
                break
            await asyncio.sleep(retry_base_delay * (2 ** (attempt - 1)))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"fetch_text failed without exception: {url}")


async def fetch_article_content(
    session: aiohttp.ClientSession,
    item: dict[str, str],
    semaphore: asyncio.Semaphore,
) -> PreparedNewsArticle | None:
    async with semaphore:
        try:
            page_html = await fetch_text(session, item["link"])
            blocks = extract_article_blocks(page_html, article_title=item["title"])
            content = render_blocks_text(blocks)
        except Exception as exc:
            print(f"Skip article: {item['link']} | {exc}")
            return None

    return prepare_article(item, content=content, blocks=blocks)


async def fetch_yahoo_finance_articles(
    rss_url: str = RSS_URL,
    limit: int = DEFAULT_LIMIT,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> list[PreparedNewsArticle]:
    connector = aiohttp.TCPConnector(limit_per_host=concurrency)
    async with aiohttp.ClientSession(
        headers=DEFAULT_HEADERS,
        connector=connector,
        max_line_size=65536,
        max_field_size=65536,
    ) as session:
        rss_xml = await fetch_text(session, rss_url)
        items = parse_rss_items(rss_xml, limit=limit)
        semaphore = asyncio.Semaphore(concurrency)
        tasks = [
            fetch_article_content(session=session, item=item, semaphore=semaphore)
            for item in items
        ]
        results = await asyncio.gather(*tasks)

    return [article for article in results if article is not None]


def fetch_yahoo_finance_articles_sync(
    rss_url: str = RSS_URL,
    limit: int = DEFAULT_LIMIT,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> list[PreparedNewsArticle]:
    return asyncio.run(
        fetch_yahoo_finance_articles(
            rss_url=rss_url,
            limit=limit,
            concurrency=concurrency,
        )
    )
