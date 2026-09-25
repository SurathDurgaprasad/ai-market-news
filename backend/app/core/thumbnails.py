"""
Resized, cached copies of event images.

Cards showed a 96x64 thumbnail by downloading the publisher's full image,
often 1-3 MB each. The API now serves a WebP at one of three widths.

Security: the image URL is never taken from the request. The endpoint looks
up the event and uses the image URL stored for it, which ingestion already
sanitized. The fetch goes through fetch_url: every hop is DNS-resolved,
rejected if any address is private, loopback, link-local or reserved, and
pinned; the body is capped while it streams. Only raster formats Pillow
decodes are accepted (no SVG), with a pixel-count ceiling against
decompression bombs, and the output is always a re-encoded WebP, so no
source bytes are passed through to the browser.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

WIDTHS = (192, 640, 1200)
MAX_SOURCE_BYTES = 8_000_000
MAX_SOURCE_PIXELS = 40_000_000
FAILURE_RETRY_SECONDS = 6 * 3600
_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def cache_dir() -> str:
    configured = os.environ.get("IMAGE_CACHE_DIR")
    if configured:
        return configured
    backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(backend, "image_cache")


def nearest_width(requested: int) -> int:
    for width in WIDTHS:
        if requested <= width:
            return width
    return WIDTHS[-1]


def _key(image_url: str, width: int) -> str:
    return hashlib.sha256(f"{image_url}|{width}".encode("utf-8")).hexdigest()[:40]


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def resize_to_webp(data: bytes, width: int) -> Optional[bytes]:
    """Decode a raster image and re-encode it as WebP no wider than width. None if unusable."""
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in _FORMATS:
                return None
            if image.width * image.height > MAX_SOURCE_PIXELS:
                return None
            image.draft("RGB", (width, width))  # JPEG: decode at reduced scale
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            if image.width > width:
                height = max(1, round(image.height * width / image.width))
                image = image.resize((width, height), Image.LANCZOS)
            out = BytesIO()
            image.save(out, format="WEBP", quality=80, method=4)
            return out.getvalue()
    except (Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        return None


def _fetch_source(image_url: str) -> Optional[bytes]:
    from tenacity import stop_after_attempt

    from app.core.fetcher import fetch_url

    try:
        response = fetch_url.retry_with(stop=stop_after_attempt(2), reraise=True)(
            image_url,
            timeout=10,
            max_bytes=MAX_SOURCE_BYTES,
            accept="image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8",
        )
    except Exception as exc:  # unsafe URL, too large, network or HTTP error
        logger.info("thumbnail source unavailable (%s)", type(exc).__name__)
        return None
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not content_type.startswith("image/") or "svg" in content_type:
        return None
    return response.content


def thumbnail(image_url: str, width: int) -> Optional[bytes]:
    """The cached WebP for this stored image URL at this width, fetching it once if needed."""
    width = nearest_width(width)
    key = _key(image_url, width)
    directory = cache_dir()
    path = os.path.join(directory, f"{key}.webp")
    failed = os.path.join(directory, f"{key}.failed")
    with _lock_for(key):
        if os.path.exists(path):
            with open(path, "rb") as handle:
                return handle.read()
        if os.path.exists(failed) and time.time() - os.path.getmtime(failed) < FAILURE_RETRY_SECONDS:
            return None
        os.makedirs(directory, exist_ok=True)
        source = _fetch_source(image_url)
        data = resize_to_webp(source, width) if source else None
        if data is None:
            with open(failed, "w", encoding="utf-8") as handle:
                handle.write("")
            return None
        temporary = f"{path}.{threading.get_ident()}.tmp"
        with open(temporary, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
        return data
