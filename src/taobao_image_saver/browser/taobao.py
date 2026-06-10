from __future__ import annotations

import asyncio
import random
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import BrowserContext, Page, async_playwright

from taobao_image_saver.app.config import CrawlConfig
from taobao_image_saver.browser.extractor import (
    DOM_IMAGE_SCRIPT,
    candidates_from_dom_payload,
    normalize_dom_payload_keys,
)
from taobao_image_saver.browser.models import ImageCandidate, ProductLink, ProductPageData
from taobao_image_saver.browser.url_utils import canonical_product_url, looks_like_product_image, normalize_url
from taobao_image_saver.storage.image_store import ImageStore


class TaobaoCrawler:
    def __init__(self, config: CrawlConfig, log, stop_event, pause_event) -> None:
        self.config = config
        self.log = log
        self.stop_event = stop_event
        self.pause_event = pause_event
        self.network_images: set[str] = set()

    async def run(self, progress) -> None:
        self.config.validate()
        store = ImageStore(self.config.output_dir)
        user_data_dir = Path(self.config.user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                str(user_data_dir),
                headless=False,
                viewport={"width": 1366, "height": 900},
                locale="zh-CN",
            )
            context.on("response", self._remember_image_response)
            page = context.pages[0] if context.pages else await context.new_page()

            try:
                links = await self._collect_search_links(page)
                self.log(f"找到 {len(links)} 个候选商品。")
                processed = success = failed = 0

                for link in links[: self.config.max_products]:
                    if self.stop_event.is_set():
                        self.log("任务已停止。")
                        break
                    await self._wait_if_paused()
                    processed += 1

                    self.log(f"打开商品：{link.title or link.url}")
                    product = await self._capture_product(context, link)
                    metadata = await store.save_product(context.request, product)
                    if metadata.error:
                        failed += 1
                        self.log(f"保存完成但有问题：{metadata.error}")
                    else:
                        success += 1
                        self.log(f"已保存 {len(metadata.images)} 张图片。")
                    progress(processed, success, failed)
                    await self._polite_delay()
            finally:
                await context.close()

    async def _collect_search_links(self, page: Page) -> list[ProductLink]:
        search_url = f"https://s.taobao.com/search?q={quote_plus(self.config.keyword)}"
        self.log(f"打开搜索页：{search_url}")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
        await self._maybe_wait_for_manual_check(page)
        await self._scroll_page(page, self.config.scroll_rounds)

        raw_links = await page.eval_on_selector_all(
            "a[href]",
            """anchors => anchors.map(a => ({
                href: a.href,
                title: (a.innerText || a.getAttribute('title') || '').trim()
            }))""",
        )
        links: list[ProductLink] = []
        seen: set[str] = set()
        for item in raw_links:
            href = normalize_url(item.get("href", ""), page.url)
            if not _is_product_page_url(href):
                continue
            canonical = canonical_product_url(href)
            if canonical in seen:
                continue
            seen.add(canonical)
            links.append(ProductLink(title=(item.get("title") or "").splitlines()[0][:80], url=canonical))
        return links

    async def _capture_product(self, context: BrowserContext, link: ProductLink) -> ProductPageData:
        page = await context.new_page()
        page.on("response", self._remember_image_response)
        try:
            await page.goto(link.url, wait_until="domcontentloaded", timeout=60_000)
            await self._maybe_wait_for_manual_check(page)
            await self._scroll_page(page, self.config.scroll_rounds)
            title = await _safe_text(page, "h1, [class*=title], [class*=Title]", link.title or "商品")
            price = await _safe_text(page, "[class*=price], [class*=Price]", "")
            shop_name = await _safe_text(page, "[class*=shop], [class*=Shop], [class*=seller]", "")
            images = await self._extract_images(page)
            selected = [
                item
                for item in images
                if (item.kind == "main" and self.config.save_main_images)
                or (item.kind == "detail" and self.config.save_detail_images)
                or item.kind == "other"
            ]
            return ProductPageData(
                title=title or link.title or "商品",
                url=page.url,
                price=price,
                shop_name=shop_name,
                images=selected,
            )
        except Exception as exc:
            return ProductPageData(title=link.title or "商品", url=link.url, error=str(exc), images=[])
        finally:
            await page.close()

    async def _extract_images(self, page: Page) -> list[ImageCandidate]:
        payload = await page.evaluate(DOM_IMAGE_SCRIPT)
        candidates = candidates_from_dom_payload(normalize_dom_payload_keys(payload), page.url)
        seen = {candidate.url for candidate in candidates}
        for url in sorted(self.network_images):
            if url in seen or not looks_like_product_image(url):
                continue
            candidates.append(ImageCandidate(url=url, kind="other", source="network"))
            seen.add(url)
        return candidates

    async def _scroll_page(self, page: Page, rounds: int) -> None:
        for _ in range(rounds):
            if self.stop_event.is_set():
                return
            await self._wait_if_paused()
            await page.mouse.wheel(0, random.randint(550, 950))
            await page.wait_for_timeout(random.randint(800, 1400))

    async def _polite_delay(self) -> None:
        delay = random.uniform(self.config.delay_min_seconds, self.config.delay_max_seconds)
        await asyncio.sleep(delay)

    async def _wait_if_paused(self) -> None:
        while self.pause_event.is_set() and not self.stop_event.is_set():
            await asyncio.sleep(0.3)

    async def _maybe_wait_for_manual_check(self, page: Page) -> None:
        url = page.url.lower()
        title = (await page.title()).lower()
        if any(token in url or token in title for token in ("login", "captcha", "verify", "安全", "登录")):
            self.log("页面需要登录或安全验证，请在浏览器中手动处理；工具将等待 60 秒。")
            await page.wait_for_timeout(60_000)

    def _remember_image_response(self, response) -> None:
        try:
            url = response.url
            content_type = response.headers.get("content-type", "")
            if "image/" in content_type and looks_like_product_image(url):
                self.network_images.add(url)
        except Exception:
            return


async def _safe_text(page: Page, selector: str, fallback: str) -> str:
    try:
        value = await page.locator(selector).first.inner_text(timeout=3_000)
        return " ".join(value.split())[:160]
    except Exception:
        return fallback


def _is_product_page_url(url: str) -> bool:
    lower = url.lower()
    return (
        "item.taobao.com/item.htm" in lower
        or "detail.tmall.com/item.htm" in lower
        or "detail.tmall.hk/" in lower
    )

