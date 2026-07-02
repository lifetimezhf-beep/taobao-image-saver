from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductLink:
    title: str
    url: str


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    kind: str
    source: str = "dom"


@dataclass
class ProductPageData:
    title: str
    url: str
    price: str = ""
    shop_name: str = ""
    images: list[ImageCandidate] | None = None
    error: str = ""

    def image_list(self) -> list[ImageCandidate]:
        return self.images or []

