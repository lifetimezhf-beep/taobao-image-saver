from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

from taobao_image_saver.browser.models import ImageCandidate, ProductPageData
from taobao_image_saver.browser.url_utils import strip_image_size_suffix
from taobao_image_saver.storage.file_names import unique_dir
from taobao_image_saver.storage.metadata import ProductMetadata, SavedImage, write_metadata


MAX_SAVED_IMAGES_PER_PRODUCT = 5
MIN_TARGET_IMAGES_PER_PRODUCT = 3
MIN_IMAGE_BYTES = 38_000
MIN_IMAGE_SIDE = 500
MIN_PRODUCT_PHOTO_SCORE = 70


@dataclass(frozen=True)
class DownloadedCandidate:
    candidate: ImageCandidate
    url: str
    content: bytes
    digest: str
    score: float


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

        downloaded = await self._download_candidates(request_context, product)
        counters = {"main": 0, "detail": 0}

        for item in _rank_candidates(downloaded)[:MAX_SAVED_IMAGES_PER_PRODUCT]:
            kind = item.candidate.kind
            counters[kind] += 1
            suffix = _guess_suffix(item.url)
            file_name = f"{kind}_{counters[kind]:03d}{suffix}"
            target = image_dir / file_name
            target.write_bytes(item.content)
            metadata.images.append(
                SavedImage(
                    kind=kind,
                    file=str(target.relative_to(product_dir)).replace("\\", "/"),
                    url=item.url,
                    sha256=item.digest,
                    bytes=len(item.content),
                )
            )

        if not metadata.images and not metadata.error:
            metadata.error = "未找到可保存的服装角度图。"
        elif len(metadata.images) < MIN_TARGET_IMAGES_PER_PRODUCT and not metadata.error:
            metadata.error = f"只找到 {len(metadata.images)} 张通过筛选的服装角度图。"

        write_metadata(product_dir / "metadata.json", metadata)
        return metadata

    async def _download_candidates(self, request_context, product: ProductPageData) -> list[DownloadedCandidate]:
        seen_urls: set[str] = set()
        seen_hashes: set[str] = set()
        downloaded: list[DownloadedCandidate] = []

        for candidate in product.image_list():
            if candidate.kind not in {"main", "detail"}:
                continue
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

            score = _product_photo_score(content, candidate.kind, normalized_url)
            if score < MIN_PRODUCT_PHOTO_SCORE:
                continue
            downloaded.append(
                DownloadedCandidate(
                    candidate=candidate,
                    url=normalized_url,
                    content=content,
                    digest=digest,
                    score=score,
                )
            )
        return downloaded


def _rank_candidates(candidates: list[DownloadedCandidate]) -> list[DownloadedCandidate]:
    main = sorted((item for item in candidates if item.candidate.kind == "main"), key=lambda item: item.score, reverse=True)
    detail = sorted((item for item in candidates if item.candidate.kind == "detail"), key=lambda item: item.score, reverse=True)

    ranked: list[DownloadedCandidate] = []
    ranked.extend(main[:2])
    ranked.extend(detail[:4])
    ranked.extend(main[2:])
    ranked.extend(detail[4:])

    deduped: list[DownloadedCandidate] = []
    seen: set[str] = set()
    for item in ranked:
        if item.digest in seen:
            continue
        seen.add(item.digest)
        deduped.append(item)
    return deduped


def _guess_suffix(url: str) -> str:
    path = urlparse(url).path.lower()
    for suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
        if suffix in path:
            return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def _product_photo_score(content: bytes, kind: str, url: str = "") -> float:
    if _looks_like_platform_asset_url(url):
        return 0
    if len(content) < MIN_IMAGE_BYTES:
        return 0
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE:
                return 0
            aspect = height / width
            if aspect < 0.65 or aspect > 2.4:
                return 0

            thumb = image.convert("RGB").resize((160, 160))
            colors = len(thumb.resize((80, 80)).getcolors(maxcolors=1_000_000) or [])
            stat = ImageStat.Stat(thumb)
            brightness = sum(stat.mean) / 3
            saturation = ImageStat.Stat(thumb.convert("HSV")).mean[1]
            edge_density = _edge_density(thumb)
            center_edge_density = _edge_density(thumb.crop((42, 24, 118, 140)))
            if _looks_like_collage_or_certificate(thumb, url):
                return 0

            if colors < 800:
                return 0
            if colors < 1_400 and brightness > 185:
                return 0

            score = 50.0
            if 1.12 <= aspect <= 1.9:
                score += 28
            elif 0.9 <= aspect <= 1.12:
                score += 4
            else:
                score -= 15

            if len(content) > 75_000:
                score += 10
            if colors > 3_000:
                score += 8
            if 18 <= saturation <= 90:
                score += 8
            if 0.12 <= center_edge_density <= 0.28:
                score += 10

            # Text-heavy posters, parameter cards, and fabric-tech diagrams usually have
            # dense edges spread across the frame, or very bright low-saturation layouts.
            if edge_density > 0.235 and kind == "main":
                score -= 22
            if brightness > 190 and saturation < 35:
                score -= 25
            if kind == "detail":
                score += 6
            return max(score, 0)
    except (UnidentifiedImageError, OSError, ValueError):
        return 0


def _looks_like_platform_asset_url(url: str) -> bool:
    lower = url.lower()
    return any(
        token in lower
        for token in (
            "-tps-",
            "/tps/",
            "alicdn.com/tfs/",
            "600000000",
            "certificate",
            "license",
        )
    )


def _looks_like_collage_or_certificate(image: Image.Image, url: str) -> bool:
    lower_url = url.lower()
    if lower_url.endswith(".png") and ("tps" in lower_url or "600000000" in lower_url):
        return True

    small = image.convert("RGB").resize((160, 160))
    pixels = list(small.getdata())
    white_fraction = sum(1 for r, g, b in pixels if r > 238 and g > 238 and b > 238) / len(pixels)
    blue_fraction = sum(1 for r, g, b in pixels if b > r + 30 and b > g + 20 and b > 120) / len(pixels)
    red_fraction = sum(1 for r, g, b in pixels if r > 155 and r > g + 28 and r > b + 28) / len(pixels)

    internal_white_rows = _internal_white_lines(small, axis="row")
    internal_white_cols = _internal_white_lines(small, axis="col")

    # Product collage/group sheets usually have white gutters splitting several
    # small panels. Single model photos may have white margins, but rarely both
    # internal row and column gutters.
    if white_fraction > 0.28 and internal_white_rows >= 2 and internal_white_cols >= 2:
        return True
    if white_fraction > 0.42 and internal_white_rows + internal_white_cols >= 7:
        return True

    # Business licenses/certification badges are often PNG-like, circular,
    # white/red/blue official graphics rather than clothing photos.
    if white_fraction > 0.30 and red_fraction > 0.05 and blue_fraction > 0.10:
        return True
    return False


def _internal_white_lines(image: Image.Image, axis: str) -> int:
    count = 0
    for index in range(24, 136):
        if axis == "row":
            line = [image.getpixel((x, index)) for x in range(160)]
        else:
            line = [image.getpixel((index, y)) for y in range(160)]
        white_ratio = sum(1 for r, g, b in line if r > 242 and g > 242 and b > 242) / 160
        if white_ratio > 0.78:
            count += 1
    return count


def _edge_density(image: Image.Image) -> float:
    gray = image.convert("L").filter(ImageFilter.FIND_EDGES)
    values = list(gray.getdata())
    return sum(1 for value in values if value > 35) / len(values)
