from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from taobao_image_saver.browser.taobao import _installed_chrome_path


async def open_login_browser(user_data_dir: Path = Path("browser-user-data")) -> None:
    user_data_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        launch_options = {
            "headless": False,
            "viewport": {"width": 1366, "height": 900},
            "locale": "zh-CN",
            "chromium_sandbox": True,
        }
        chrome_path = _installed_chrome_path()
        if chrome_path:
            launch_options["executable_path"] = str(chrome_path)
        context = await playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            **launch_options,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        print("淘宝登录浏览器已打开。请完成登录；完成后可以手动关闭浏览器窗口。")
        await page.goto("https://login.taobao.com/", wait_until="domcontentloaded", timeout=60_000)
        while context.pages:
            if page.is_closed():
                page = await context.new_page()
                await page.goto("https://login.taobao.com/", wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(1)


def main() -> None:
    asyncio.run(open_login_browser())


if __name__ == "__main__":
    main()
