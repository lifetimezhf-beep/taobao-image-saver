from taobao_image_saver.app.config import CrawlConfig
from taobao_image_saver.browser.models import ImageCandidate
from taobao_image_saver.browser.taobao import TaobaoCrawler


def test_select_product_images_uses_detail_candidates_after_first_main_images(tmp_path) -> None:
    config = CrawlConfig(
        keyword="防晒衣",
        max_products=1,
        output_dir=tmp_path,
        save_main_images=True,
        save_detail_images=True,
    )
    crawler = TaobaoCrawler(config=config, log=lambda _: None, stop_event=None, pause_event=None)
    images = [
        *(ImageCandidate(f"https://img.alicdn.com/main_{index}.jpg", "main") for index in range(8)),
        *(ImageCandidate(f"https://img.alicdn.com/detail_{index}.jpg", "detail") for index in range(8)),
        ImageCandidate("https://img.alicdn.com/logo.jpg", "other"),
    ]

    selected = crawler._select_product_images(images)

    assert [item.kind for item in selected[:5]] == ["main", "main", "detail", "detail", "detail"]
