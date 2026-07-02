import asyncio
from io import BytesIO

from PIL import Image

from taobao_image_saver.browser.models import ImageCandidate, ProductPageData
from taobao_image_saver.storage.image_store import ImageStore, _product_photo_score


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.ok = True
        self._content = content

    async def body(self) -> bytes:
        return self._content


class FakeRequestContext:
    async def get(self, url: str, timeout: int = 30_000) -> FakeResponse:
        if "same" in url:
            return FakeResponse(_image_bytes((120, 150, 180)))
        return FakeResponse(_image_bytes((180, 120, 90)))


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


def _image_bytes(color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (900, 1200), color)
    pixels = image.load()
    for y in range(1200):
        for x in range(900):
            pixels[x, y] = (
                (color[0] + x // 5 + y // 7) % 255,
                (color[1] + x // 9 + y // 4) % 255,
                (color[2] + x // 6 + y // 8) % 255,
            )
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def test_product_photo_score_rejects_platform_tps_assets() -> None:
    content = _image_bytes((130, 160, 190))

    score = _product_photo_score(
        content,
        "detail",
        "https://img.alicdn.com/imgextra/i3/O1CN010KJqyD1euRzc5UDlf_!!6000000003931-2-tps-1228-1228.png",
    )

    assert score == 0


def test_product_photo_score_rejects_collage_group_image() -> None:
    image = Image.new("RGB", (900, 900), "white")
    colors = [(90, 120, 140), (150, 170, 160), (180, 150, 120), (110, 130, 180)]
    boxes = [(40, 40, 400, 400), (500, 40, 860, 400), (40, 500, 400, 860), (500, 500, 860, 860)]
    for color, box in zip(colors, boxes):
        panel = Image.open(BytesIO(_image_bytes(color))).resize((box[2] - box[0], box[3] - box[1]))
        image.paste(panel, box)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)

    assert _product_photo_score(buffer.getvalue(), "main", "https://img.alicdn.com/group.jpg") == 0
