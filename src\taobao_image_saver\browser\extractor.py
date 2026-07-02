from __future__ import annotations

from typing import Any

from taobao_image_saver.browser.models import ImageCandidate
from taobao_image_saver.browser.url_utils import (
    looks_like_product_image,
    normalize_url,
    pick_largest_from_srcset,
    strip_image_size_suffix,
)


IMAGE_ATTRS = ("src", "data-src", "data-ks-lazyload", "data-lazyload", "data-original", "data-img")

NOISE_TOKENS = (
    "avatar",
    "comment",
    "evaluate",
    "icon",
    "logo",
    "qrcode",
    "rate",
    "review",
    "seller",
    "shop-logo",
    "user",
    "评价",
    "评论",
    "头像",
    "买家秀",
    "店铺",
    "banner",
    "coupon",
    "promo",
    "service",
    "size",
    "spec",
    "尺码",
    "参数",
    "促销",
    "优惠",
    "活动",
    "服务",
)


def candidates_from_dom_payload(payload: list[dict[str, Any]], base_url: str) -> list[ImageCandidate]:
    results: list[ImageCandidate] = []
    seen: set[str] = set()
    for item in payload:
        kind = classify_image(item)
        if kind == "ignore" or _looks_too_small(item):
            continue
        urls = image_urls_from_item(item, base_url)
        for url in urls:
            if not looks_like_product_image(url):
                continue
            if _looks_like_noise_url(url):
                continue
            normalized = strip_image_size_suffix(url)
            key = f"{kind}:{normalized}"
            if key in seen:
                continue
            seen.add(key)
            results.append(ImageCandidate(url=normalized, kind=kind, source="dom"))
    return results


def image_urls_from_item(item: dict[str, Any], base_url: str) -> list[str]:
    urls: list[str] = []
    srcset = item.get("srcset") or ""
    if srcset:
        picked = pick_largest_from_srcset(srcset, base_url)
        if picked:
            urls.append(picked)

    for attr in IMAGE_ATTRS:
        value = item.get(attr) or ""
        if not value or value.startswith("data:image"):
            continue
        normalized = normalize_url(value, base_url)
        if normalized:
            urls.append(normalized)
    return urls


def classify_image(item: dict[str, Any]) -> str:
    context = " ".join(
        str(item.get(key, "")).lower()
        for key in ("className", "id", "parentClassName", "parentId", "ancestorText", "alt")
    )
    if any(token in context for token in NOISE_TOKENS):
        return "ignore"
    if any(token in context for token in ("desc", "detail", "description", "content", "rich-text")):
        return "detail"
    if any(token in context for token in ("main", "gallery", "thumb", "slider", "carousel", "pic")):
        return "main"
    if _is_large_below_fold(item):
        return "detail"
    return "other"


def _is_large_below_fold(item: dict[str, Any]) -> bool:
    top = _as_int(item.get("rectTop"))
    width = max(_as_int(item.get(key)) for key in ("naturalWidth", "clientWidth", "width"))
    height = max(_as_int(item.get(key)) for key in ("naturalHeight", "clientHeight", "height"))
    return top > 650 and width >= 360 and height >= 360


def _looks_too_small(item: dict[str, Any]) -> bool:
    widths = [_as_int(item.get(key)) for key in ("naturalWidth", "width", "clientWidth")]
    heights = [_as_int(item.get(key)) for key in ("naturalHeight", "height", "clientHeight")]
    width = max(widths)
    height = max(heights)
    if width == 0 or height == 0:
        return False
    return width < 240 or height < 240


def _looks_like_noise_url(url: str) -> bool:
    lower = url.lower()
    return any(token in lower for token in ("avatar", "icon", "logo", "qrcode", "rate", "review", "comment"))


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


DOM_IMAGE_SCRIPT = """
() => Array.from(document.images).map((img) => {
    const parent = img.parentElement;
    const ancestor = img.closest('[class], [id]');
    return {
    currentSrc: img.currentSrc || '',
    src: img.getAttribute('src') || '',
    srcset: img.getAttribute('srcset') || '',
    dataSrc: img.getAttribute('data-src') || '',
    dataKsLazyload: img.getAttribute('data-ks-lazyload') || '',
    dataLazyload: img.getAttribute('data-lazyload') || '',
    dataOriginal: img.getAttribute('data-original') || '',
    dataImg: img.getAttribute('data-img') || '',
    className: img.className || '',
    id: img.id || '',
    parentClassName: parent ? parent.className || '' : '',
    parentId: parent ? parent.id || '' : '',
    ancestorText: ancestor ? `${ancestor.className || ''} ${ancestor.id || ''}` : '',
    alt: img.getAttribute('alt') || '',
    width: img.getAttribute('width') || '',
    height: img.getAttribute('height') || '',
    clientWidth: img.clientWidth || 0,
    clientHeight: img.clientHeight || 0,
    naturalWidth: img.naturalWidth || 0,
    naturalHeight: img.naturalHeight || 0,
    rectTop: Math.round(img.getBoundingClientRect().top + window.scrollY),
  };
})
"""


def normalize_dom_payload_keys(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    key_map = {
        "currentSrc": "src",
        "dataSrc": "data-src",
        "dataKsLazyload": "data-ks-lazyload",
        "dataLazyload": "data-lazyload",
        "dataOriginal": "data-original",
        "dataImg": "data-img",
    }
    for item in payload:
        normalized = dict(item)
        for source, target in key_map.items():
            if source in item:
                normalized[target] = item[source]
        mapped.append(normalized)
    return mapped
