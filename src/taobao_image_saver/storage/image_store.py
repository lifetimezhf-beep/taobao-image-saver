from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

from taobao_image_saver.browser.models import ImageCandidate, ProductPageData
from taobao_image_saver.browser.url_utils import strip_image_size_suffix
from taobao_image_saver.storage.file_names import unique_dir
from taobao_image_saver.storage.metadata import ProductMetadata, SavedImage, write_metadata


class ImageStore:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def save_product(self, request_context, product: ProductPageData) -> ProductMetadata:
        product_dir = unique_dir(self.output_dir, product.title or "商品")
        image_dir = product_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)

        metadata = ProductMetadata(
            title=product.title,
            url=product.url,
            price=product.price,
            shop_name=product.shop_name,
            error=product.error,
        )

        seen_urls: set[str] = set()
        seen_hashes: set[str] = set()
        counters = {"main": 0, "detail": 0, "other": 0}

        for candidate in product.image_list():
            normalized_url = strip_image_size_suffix(candidate.url)
            if not normalized_url or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)

            try:
                response = await request_context.get(normalized_url, timeout=30_000)
                if not response.ok:
                    continue
                content = await response.body()
            except Exception:
                continue

            digest = hashlib.sha256(content).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)

            kind = candidate.kind if candidate.kind in counters else "other"
            counters[kind] += 1
            suffix = _guess_suffix(normalized_url)
            file_name = f"{kind}_{counters[kind]:03d}{suffix}"
            target = image_dir / file_name
            target.write_bytes(content)
            metadata.images.append(
                SavedImage(
                    kind=kind,
                    file=str(target.relative_to(product_dir)).replace("\\", "/"),
                    url=normalized_url,
                    sha256=digest,
                    bytes=len(content),
                )
            )

        if not metadata.images and not metadata.error:
            metadata.error = "未找到可保存的商品图片。"

        write_metadata(product_dir / "metadata.json", metadata)
        return metadata


def _guess_suffix(url: str) -> str:
    path = urlparse(url).path.lower()
    for suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
        if suffix in path:
            return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"

