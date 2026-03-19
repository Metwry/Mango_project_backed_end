from __future__ import annotations

from collections import Counter
from io import BytesIO
import colorsys
import hashlib
import os
from pathlib import Path
import re
from urllib.parse import quote, urlencode
from urllib.parse import urlparse

from django.conf import settings
import requests
from PIL import Image

from market.models import Instrument
from common.utils.code_utils import normalize_code


# 将港股代码标准化为 logo 服务可识别的 ticker 格式。
def _normalize_hk_logo_ticker(code: str) -> str | None:
    value = str(code or "").strip().upper()
    if not value:
        return None
    if value.endswith(".HK"):
        value = value[:-3]
    digits = re.sub(r"\D", "", value)
    if digits:
        # logo.dev expects HK tickers without leading zeros, e.g. 01810 -> 1810.HK
        return f"{int(digits)}.HK"
    return f"{value}.HK"


# 将 A 股代码标准化为 logo 服务可识别的 ticker 格式。
def _normalize_cn_logo_ticker(code: str) -> str | None:
    value = str(code or "").strip().upper()
    if not value:
        return None
    for suffix in (".SS", ".SH", ".SZ"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    digits = digits.zfill(6) if len(digits) <= 6 else digits
    if digits.startswith(("5", "6", "9")):
        return f"{digits}.SS"
    if digits.startswith(("0", "1", "2", "3")):
        return f"{digits}.SZ"
    return None


# 根据市场和短代码生成 logo 地址与来源信息。
def build_logo_metadata(*, short_code: str, market: str) -> tuple[str | None, str | None]:
    code = normalize_code(short_code)
    market_code = normalize_code(market)
    if not code:
        return None, None

    if market_code == Instrument.Market.US:
        path = f"/ticker/{quote(code)}"
        source = "logo.dev:ticker"
    elif market_code == Instrument.Market.HK:
        hk_code = _normalize_hk_logo_ticker(code)
        if not hk_code:
            return None, None
        path = f"/ticker/{quote(hk_code)}"
        source = "logo.dev:ticker"
    elif market_code == Instrument.Market.CN:
        cn_code = _normalize_cn_logo_ticker(code)
        if not cn_code:
            return None, None
        path = f"/ticker/{quote(cn_code)}"
        source = "logo.dev:ticker"
    elif market_code == Instrument.Market.CRYPTO:
        path = f"/crypto/{quote(code.lower())}"
        source = "logo.dev:crypto"
    else:
        return None, None

    base_url = str(getattr(settings, "LOGO_DEV_IMAGE_BASE_URL", "https://img.logo.dev") or "https://img.logo.dev")
    token = str(getattr(settings, "LOGO_DEV_PUBLISHABLE_KEY", "") or "").strip()
    logo_url = f"{base_url.rstrip('/')}{path}"
    query_items: list[tuple[str, str]] = []
    if token:
        query_items.append(("token", token))
    query_items.append(("retina", "true"))
    logo_url = f"{logo_url}?{urlencode(query_items)}"
    return logo_url, source


# 将 RGB 颜色值转换为十六进制颜色字符串。
def _hex_color(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02X}{g:02X}{b:02X}"


# 返回本地 logo 下载目录，并在不存在时自动创建。
def _logo_download_dir() -> Path:
    raw = str(getattr(settings, "LOGO_DOWNLOAD_DIR", "") or "").strip()
    if raw:
        target = Path(raw)
    else:
        base_dir = getattr(settings, "BASE_DIR", Path.cwd())
        target = Path(base_dir).resolve().parent / "logo_downloads"
    target.mkdir(parents=True, exist_ok=True)
    return target


# 将任意文件名片段清洗为安全的文件系统名称。
def _safe_name(raw: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]", "_", str(raw or "").strip())
    return s.strip("_") or "logo"


# 根据 URL 和响应头猜测图片扩展名。
def _guess_ext(url: str, content_type: str) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}:
        return suffix

    ctype = str(content_type or "").lower()
    if "png" in ctype:
        return ".png"
    if "jpeg" in ctype or "jpg" in ctype:
        return ".jpg"
    if "webp" in ctype:
        return ".webp"
    if "gif" in ctype:
        return ".gif"
    if "bmp" in ctype:
        return ".bmp"
    if "svg" in ctype:
        return ".svg"
    return ".img"


# 根据 logo URL 构造稳定的本地文件名。
def _build_logo_filename(logo_url: str, ext: str) -> str:
    parsed = urlparse(logo_url)
    parts = [p for p in parsed.path.split("/") if p]
    market = _safe_name(parts[-2] if len(parts) >= 2 else "logo")
    code = _safe_name(parts[-1] if parts else "unknown")
    suffix = hashlib.sha1(logo_url.encode("utf-8")).hexdigest()[:10]
    return f"{market}_{code}_{suffix}{ext}"


# 下载 logo 到本地缓存目录，并优先复用已存在文件。
def download_logo_to_local(logo_url: str, *, timeout: float = 8.0) -> Path | None:
    url = str(logo_url or "").strip()
    if not url:
        return None

    download_dir = _logo_download_dir()

    # First try to reuse any existing file for this url hash.
    suffix = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    existing = list(download_dir.glob(f"*_{suffix}.*"))
    if existing:
        try:
            if existing[0].stat().st_size > 0:
                return existing[0]
        except OSError:
            pass

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return None

    content = resp.content
    if not content:
        return None

    ext = _guess_ext(url, resp.headers.get("Content-Type", ""))
    file_path = download_dir / _build_logo_filename(url, ext)
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        return None

    return file_path


# 提取 logo 主色调，供前端展示使用。
def extract_logo_theme_color(logo_url: str, *, timeout: float = 8.0) -> str | None:
    local_path = download_logo_to_local(logo_url, timeout=timeout)
    if local_path is None:
        return None

    try:
        with open(local_path, "rb") as f:
            img = Image.open(BytesIO(f.read())).convert("RGBA")
    except Exception:
        return None

    img.thumbnail((64, 64))
    all_counter: Counter[tuple[int, int, int]] = Counter()
    colorful_counter: Counter[tuple[int, int, int]] = Counter()

    for r, g, b, a in img.getdata():
        if a < 32:
            continue

        # Bucket colors to reduce tiny shade noise.
        key = ((r // 16) * 16, (g // 16) * 16, (b // 16) * 16)
        all_counter[key] += 1

        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        if s >= 0.2 and 0.08 <= v <= 0.95:
            colorful_counter[key] += 1

    if colorful_counter:
        return _hex_color(colorful_counter.most_common(1)[0][0])
    if all_counter:
        return _hex_color(all_counter.most_common(1)[0][0])
    return None

