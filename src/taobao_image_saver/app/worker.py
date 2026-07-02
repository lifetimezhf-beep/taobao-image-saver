from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from taobao_image_saver.app.config import CrawlConfig
from taobao_image_saver.browser.taobao import TaobaoCrawler


class CrawlWorker(QObject):
    log_message = Signal(str)
    progress_changed = Signal(int, int, int)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, config: CrawlConfig) -> None:
        super().__init__()
        self.config = config
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            asyncio.run(self._run_async())
            self.finished.emit()
        except Exception as exc:
            logging.exception("Crawl worker failed")
            self._write_crash_log(exc)
            self.failed.emit(str(exc))

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.pause_event.set()
        else:
            self.pause_event.clear()

    async def _run_async(self) -> None:
        crawler = TaobaoCrawler(
            config=self.config,
            log=self.log_message.emit,
            stop_event=self.stop_event,
            pause_event=self.pause_event,
        )
        await crawler.run(self.progress_changed.emit)

    def _write_crash_log(self, exc: Exception) -> None:
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "app.log").open("a", encoding="utf-8") as handle:
            handle.write("\n=== Crawl worker failed ===\n")
            handle.write(f"{exc}\n")
            handle.write(traceback.format_exc())


def default_output_dir() -> Path:
    return Path.cwd() / "output"
