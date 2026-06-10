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


def candidates_from_dom_payload(payload: list[dict[str, Any]], base_url: str) -> list[ImageCandidate]:
    results: list[ImageCandidate] = []
    seen: set[str] = set()
    for item in payload:
        kind = classify_image(item)
        urls = image_urls_from_item(item, base_url)
        for url in urls:
            if not looks_like_product_image(url):
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
        for key in ("className", "id", "parentClassName", "parentId", "ancestorText")
    )
    if any(token in context for token in ("desc", "detail", "description", "content", "rich-text")):
        return "detail"
    if any(token in context for token in ("main", "gallery", "thumb", "slider", "carousel", "pic")):
        return "main"
    return "other"


DOM_IMAGE_SCRIPT = """
() => Array.from(document.images).map((img) => {
  const parent = img.parentElement;
  const ancestor = img.closest('[class], [id]');
  return {
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
  };
})
"""


def normalize_dom_payload_keys(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    key_map = {
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

