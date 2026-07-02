from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CrawlConfig:
    keyword: str
    max_products: int
    output_dir: Path
    delay_min_seconds: float = 6.0
    delay_max_seconds: float = 12.0
    scroll_rounds: int = 5
    save_main_images: bool = True
    save_detail_images: bool = True
    user_data_dir: Path = Path("browser-profile")
    browser_path: Path | None = None

    def validate(self) -> None:
        if not self.keyword.strip():
            raise ValueError("请输入关键词。")
        if self.max_products < 1:
            raise ValueError("最大商品数必须大于 0。")
        if self.delay_min_seconds < 0 or self.delay_max_seconds < 0:
            raise ValueError("操作间隔不能小于 0。")
        if self.delay_min_seconds > self.delay_max_seconds:
            raise ValueError("最小间隔不能大于最大间隔。")
        if self.scroll_rounds < 1:
            raise ValueError("滚动次数必须大于 0。")
        if self.browser_path and not self.browser_path.exists():
            raise ValueError(f"浏览器程序不存在：{self.browser_path}")

    def validate_login_settings(self) -> None:
        if not self.browser_path:
            raise ValueError("请先选择浏览器程序。")
        if not self.browser_path.exists():
            raise ValueError(f"浏览器程序不存在：{self.browser_path}")
