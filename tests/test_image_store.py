import asyncio

from taobao_image_saver.browser.models import ImageCandidate, ProductPageData
from taobao_image_saver.storage.image_store import ImageStore


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.ok = True
        self._content = content

    async def body(self) -> bytes:
        return self._content


class FakeRequestContext:
    async def get(self, url: str, timeout: int = 30_000) -> FakeResponse:
        if "same" in url:
            return FakeResponse(b"same-content")
        return FakeResponse(url.encode("utf-8"))


def test_image_store_deduplicates_and_writes_metadata(tmp_path) -> None:
    async def run() -> None:
        product = ProductPageData(
            title="测试商品",
            url="https://item.taobao.com/item.htm?id=1",
            price="12.00",
            shop_name="测试店",
            images=[
                ImageCandidate("https://img.alicdn.com/same.jpg", "main"),
                ImageCandidate("https://img.alicdn.com/same-copy.jpg", "main"),
                ImageCandidate("https://img.alicdn.com/detail.webp", "detail"),
            ],
        )

        metadata = await ImageStore(tmp_path).save_product(FakeRequestContext(), product)

        assert metadata.title == "测试商品"
        assert len(metadata.images) == 2
        assert (tmp_path / "测试商品" / "metadata.json").exists()
        assert (tmp_path / "测试商品" / "images" / "main_001.jpg").exists()
        assert (tmp_path / "测试商品" / "images" / "detail_001.webp").exists()

    asyncio.run(run())

