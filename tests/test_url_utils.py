from taobao_image_saver.browser.url_utils import (
    canonical_product_url,
    normalize_url,
    pick_largest_from_srcset,
    strip_image_size_suffix,
)


def test_normalize_protocol_relative_url() -> None:
    assert normalize_url("//img.alicdn.com/a.jpg") == "https://img.alicdn.com/a.jpg"


def test_pick_largest_from_srcset() -> None:
    srcset = "//img.alicdn.com/a_100x100.jpg 100w, //img.alicdn.com/a_800x800.jpg 800w"
    assert pick_largest_from_srcset(srcset) == "https://img.alicdn.com/a"


def test_strip_image_size_suffix_keeps_query() -> None:
    assert strip_image_size_suffix("https://img.alicdn.com/a.jpg_430x430q90.jpg?x=1") == (
        "https://img.alicdn.com/a.jpg?x=1"
    )


def test_canonical_product_url_keeps_item_id_only() -> None:
    url = "https://item.taobao.com/item.htm?id=123&spm=abc#frag"
    assert canonical_product_url(url) == "https://item.taobao.com/item.htm?id=123"

