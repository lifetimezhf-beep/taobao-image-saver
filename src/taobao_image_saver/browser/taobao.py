from __future__ import annotations

import asyncio
import random
import subprocess
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


MAIN_IMAGES_BEFORE_DETAIL = 2
MAX_MAIN_CANDIDATES_PER_PRODUCT = 8
MAX_DETAIL_CANDIDATES_PER_PRODUCT = 40


class ManualCheckRequired(RuntimeError):
    def __init__(self, url: str) -> None:
        super().__init__("页面需要真人验证，已切换到普通浏览器窗口。请完成验证后重新开始任务。")
        self.url = url


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

        async with async_playwright() as playwright:
            browser_path = self.config.browser_path or _default_browser_path()
            if not browser_path:
                raise RuntimeError("没有找到可用浏览器。请在界面里选择 chrome.exe 或 msedge.exe。")

            self.config.user_data_dir.mkdir(parents=True, exist_ok=True)
            self.log(f"正在启动浏览器：{browser_path}")
            self.log(f"登录资料目录：{self.config.user_data_dir.resolve()}")

            try:
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.config.user_data_dir),
                    executable_path=str(browser_path),
                    headless=False,
                    viewport={"width": 1440, "height": 950},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    args=["--start-maximized"],
                )
            except Exception as exc:
                if _is_browser_closed_error(str(exc)):
                    raise RuntimeError(
                        "浏览器启动后立刻关闭。通常是登录准备窗口还没关闭，或者同一个 browser-profile 正被 Chrome/Edge 占用。"
                        "请关闭工具打开的浏览器窗口后再开始。"
                    ) from exc
                raise

            context.on("response", self._remember_image_response)
            page = context.pages[0] if context.pages else await context.new_page()
            manual_url: str | None = None

            try:
                links = await self._collect_search_links(page)
                self.log(f"找到 {len(links)} 个候选商品。")
                if not links:
                    self.log("没有找到商品链接。请确认已经登录，或手动处理页面提示后重试。")
                    progress(0, 0, 0)
                    return

                processed = success = failed = 0
                for link in links[: self.config.max_products]:
                    if self.stop_event.is_set():
                        self.log("任务已停止。")
                        break
                    await self._wait_if_paused()
                    processed += 1

                    self.log(f"打开商品：{link.title or link.url}")
                    product = await self._capture_product(context, link)
                    try:
                        metadata = await store.save_product(context.request, product)
                    except Exception as exc:
                        failed += 1
                        self.log(f"保存失败：{exc}")
                        progress(processed, success, failed)
                        await self._polite_delay()
                        continue

                    if metadata.error:
                        failed += 1
                        self.log(f"保存完成但有问题：{metadata.error}")
                    else:
                        success += 1
                        self.log(f"已保存 {len(metadata.images)} 张图片。")
                    progress(processed, success, failed)
                    await self._polite_delay()
            except ManualCheckRequired as exc:
                manual_url = exc.url
                self.log("检测到真人验证。自动任务已暂停，准备切换到普通浏览器窗口。")
            except Exception as exc:
                if _is_browser_closed_error(str(exc)):
                    self.log("浏览器窗口已关闭，任务已停止。")
                    return
                raise
            finally:
                try:
                    await context.close()
                except Exception:
                    pass
                self.log("任务结束。")

            if manual_url:
                _open_regular_browser(browser_path, self.config.user_data_dir, manual_url)
                self.log("已打开普通浏览器验证窗口。请完成验证并关闭该窗口，然后重新点击“开始自动浏览保存”。")
                return

    async def _collect_search_links(self, page: Page) -> list[ProductLink]:
        search_url = f"https://s.taobao.com/search?q={quote_plus(self.config.keyword)}"
        self.log(f"打开搜索页：{search_url}")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
        await self._maybe_stop_for_manual_check(page)
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
            title = (item.get("title") or "").splitlines()[0][:80]
            links.append(ProductLink(title=title, url=canonical))
        return links

    async def _capture_product(self, context: BrowserContext, link: ProductLink) -> ProductPageData:
        page: Page | None = None
        try:
            page = await context.new_page()
            page.on("response", self._remember_image_response)
            await page.goto(link.url, wait_until="domcontentloaded", timeout=60_000)
            await self._maybe_stop_for_manual_check(page)
            await self._scroll_page(page, max(self.config.scroll_rounds, 6))
            title = await _safe_text(page, "h1, [class*=title], [class*=Title]", link.title or "商品")
            price = await _safe_text(page, "[class*=price], [class*=Price]", "")
            shop_name = await _safe_text(page, "[class*=shop], [class*=Shop], [class*=seller]", "")
            images = await self._extract_images(page)
            selected = self._select_product_images(images)
            return ProductPageData(
                title=title or link.title or "商品",
                url=page.url,
                price=price,
                shop_name=shop_name,
                images=selected,
            )
        except ManualCheckRequired:
            raise
        except Exception as exc:
            return ProductPageData(title=link.title or "商品", url=link.url, error=str(exc), images=[])
        finally:
            if page and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass

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

    def _select_product_images(self, images: list[ImageCandidate]) -> list[ImageCandidate]:
        main = [item for item in images if item.kind == "main"][:MAX_MAIN_CANDIDATES_PER_PRODUCT]
        detail = [item for item in images if item.kind == "detail"][:MAX_DETAIL_CANDIDATES_PER_PRODUCT]

        selected: list[ImageCandidate] = []
        if self.config.save_main_images:
            selected.extend(main[:MAIN_IMAGES_BEFORE_DETAIL])
        if self.config.save_detail_images:
            selected.extend(detail)
        if self.config.save_main_images:
            selected.extend(main[MAIN_IMAGES_BEFORE_DETAIL:])
        return selected

    async def _scroll_page(self, page: Page, rounds: int) -> None:
        for _ in range(rounds):
            if self.stop_event.is_set():
                return
            await self._wait_if_paused()
            await self._maybe_stop_for_manual_check(page)
            await page.mouse.wheel(0, random.randint(550, 950))
            await page.wait_for_timeout(random.randint(900, 1600))

    async def _polite_delay(self) -> None:
        delay = random.uniform(self.config.delay_min_seconds, self.config.delay_max_seconds)
        await asyncio.sleep(delay)

    async def _wait_if_paused(self) -> None:
        while self.pause_event.is_set() and not self.stop_event.is_set():
            await asyncio.sleep(0.3)

    async def _maybe_stop_for_manual_check(self, page: Page) -> None:
        if await _needs_manual_check(page):
            raise ManualCheckRequired(page.url)

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


async def _needs_manual_check(page: Page) -> bool:
    url = page.url.lower()
    title = (await page.title()).lower()
    if any(token in url for token in ("login.taobao.com", "login.htm", "passport", "captcha", "verify")):
        return True
    if any(token in title for token in ("登录", "验证码", "安全验证", "身份验证", "滑块")):
        return True

    return await page.evaluate(
        """
        () => {
          const visible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const box = el.getBoundingClientRect();
            return style.visibility !== 'hidden'
              && style.display !== 'none'
              && box.width > 120
              && box.height > 80;
          };
          const selectors = [
            '#login-form',
            '.login-box',
            '.fm-login',
            '[class*="captcha"]',
            '[id*="captcha"]',
            '[class*="nc-container"]',
            '[id*="nc_"]',
            '[class*="verify"]',
            '[id*="verify"]'
          ];
          return selectors.some((selector) =>
            Array.from(document.querySelectorAll(selector)).some(visible)
          );
        }
        """
    )


def _is_product_page_url(url: str) -> bool:
    lower = url.lower()
    return (
        "item.taobao.com/item.htm" in lower
        or "detail.tmall.com/item.htm" in lower
        or "detail.tmall.hk/" in lower
    )


def _is_browser_closed_error(message: str) -> bool:
    return "target page, context or browser has been closed" in (message or "").lower()


def _open_regular_browser(browser_path: Path, user_data_dir: Path, url: str) -> None:
    subprocess.Popen(
        [
            str(browser_path),
            f"--user-data-dir={user_data_dir}",
            "--new-window",
            url,
        ],
        close_fds=True,
    )


def _default_browser_path() -> Path | None:
    for raw_path in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ):
        path = Path(raw_path)
        if path.exists():
            return path
    return None
