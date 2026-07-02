from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


def normalize_url(raw_url: str, base_url: str = "https://www.taobao.com/") -> str:
    value = (raw_url or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    return urljoin(base_url, value)


def strip_image_size_suffix(url: str) -> str:
    """Remove common Taobao image resize suffixes while keeping query strings."""
    parsed = urlparse(url)
    path = re.sub(r"_(\d+x\d+(?:q\d+)?|sum|q\d+|webp)(?:\.[a-zA-Z0-9]+)?$", "", parsed.path)
    return urlunparse(parsed._replace(path=path))


def pick_largest_from_srcset(srcset: str, base_url: str = "https://www.taobao.com/") -> str:
    candidates: list[tuple[int, str]] = []
    for part in (srcset or "").split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = normalize_url(bits[0], base_url)
        width = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            width = int(bits[1][:-1] or 0)
        candidates.append((width, url))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return strip_image_size_suffix(candidates[0][1])


def looks_like_product_image(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    if not any(ext in path for ext in IMAGE_EXTENSIONS):
        return False
    return any(token in host for token in ("alicdn.com", "taobaocdn.com", "tbcdn.cn", "taobao.com"))


def canonical_product_url(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    keep: dict[str, str] = {}
    if "id" in query:
        keep["id"] = query["id"]
    cleaned_query = urlencode(keep)
    return urlunparse(parsed._replace(query=cleaned_query, fragment=""))
