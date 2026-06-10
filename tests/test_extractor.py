from taobao_image_saver.browser.extractor import candidates_from_dom_payload


def test_candidates_from_dom_payload_extracts_lazy_main_and_detail_images() -> None:
    payload = [
        {
            "data-src": "//img.alicdn.com/main_800x800.jpg",
            "className": "main-gallery-image",
        },
        {
            "src": "https://img.alicdn.com/detail.jpg_790x10000.jpg",
            "parentClassName": "desc-content",
        },
        {
            "src": "https://example.com/noise.jpg",
            "className": "avatar",
        },
    ]

    candidates = candidates_from_dom_payload(payload, "https://item.taobao.com/item.htm?id=1")

    assert [(item.kind, item.url) for item in candidates] == [
        ("main", "https://img.alicdn.com/main"),
        ("detail", "https://img.alicdn.com/detail.jpg"),
    ]

