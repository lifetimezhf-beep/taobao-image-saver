from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SavedImage:
    kind: str
    file: str
    url: str
    sha256: str
    bytes: int


@dataclass
class ProductMetadata:
    title: str
    url: str
    price: str = ""
    shop_name: str = ""
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    images: list[SavedImage] = field(default_factory=list)
    error: str = ""


def write_metadata(path: Path, metadata: ProductMetadata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(metadata), ensure_ascii=False, indent=2), encoding="utf-8")

