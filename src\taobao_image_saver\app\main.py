from __future__ import annotations

import logging
import subprocess
import sys
import traceback
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import QThread, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from taobao_image_saver.app.config import CrawlConfig
from taobao_image_saver.app.worker import CrawlWorker, default_output_dir


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("淘宝商品高清图保存助手")
        self.resize(960, 700)
        self.worker: CrawlWorker | None = None
        self.thread: QThread | None = None
        self.is_paused = False

        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("例如：防晒衣、键盘、收纳盒")

        self.max_products_input = QSpinBox()
        self.max_products_input.setRange(1, 100)
        self.max_products_input.setValue(3)

        self.delay_min_input = QDoubleSpinBox()
        self.delay_min_input.setRange(0.5, 120.0)
        self.delay_min_input.setSingleStep(0.5)
        self.delay_min_input.setValue(6.0)
        self.delay_min_input.setSuffix(" 秒")

        self.delay_max_input = QDoubleSpinBox()
        self.delay_max_input.setRange(0.5, 120.0)
        self.delay_max_input.setSingleStep(0.5)
        self.delay_max_input.setValue(12.0)
        self.delay_max_input.setSuffix(" 秒")

        self.scroll_rounds_input = QSpinBox()
        self.scroll_rounds_input.setRange(1, 30)
        self.scroll_rounds_input.setValue(5)

        default_browser = _default_browser_path()
        self.browser_input = QLineEdit(str(default_browser) if default_browser else "")
        self.browser_input.setPlaceholderText("选择 chrome.exe 或 msedge.exe")
        self.browser_button = QPushButton("选择浏览器")
        self.browser_button.clicked.connect(self.choose_browser)

        self.output_input = QLineEdit(str(default_output_dir()))
        self.browse_button = QPushButton("选择目录")
        self.browse_button.clicked.connect(self.choose_output_dir)

        self.main_images_checkbox = QCheckBox("保存主图")
        self.main_images_checkbox.setChecked(True)
        self.detail_images_checkbox = QCheckBox("详情页补角度图")
        self.detail_images_checkbox.setChecked(True)

        self.status_label = QLabel("待开始")
        self.counter_label = QLabel("已处理 0 / 成功 0 / 失败 0")
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        self.login_prepare_button = QPushButton("登录/验证准备")
        self.start_button = QPushButton("开始自动浏览保存")
        self.open_search_button = QPushButton("仅打开搜索页")
        self.pause_button = QPushButton("暂停")
        self.stop_button = QPushButton("停止")
        self.open_output_button = QPushButton("打开保存目录")

        self.login_prepare_button.clicked.connect(self.open_login_browser)
        self.start_button.clicked.connect(self.start_task)
        self.open_search_button.clicked.connect(self.open_search_page)
        self.pause_button.clicked.connect(self.toggle_pause)
        self.stop_button.clicked.connect(self.stop_task)
        self.open_output_button.clicked.connect(self.open_output_dir)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)

        self._build_layout()

    def _build_layout(self) -> None:
        form = QFormLayout()
        form.addRow("关键词", self.keyword_input)
        form.addRow("最大商品数", self.max_products_input)
        form.addRow("最小操作间隔", self.delay_min_input)
        form.addRow("最大操作间隔", self.delay_max_input)
        form.addRow("每页滚动次数", self.scroll_rounds_input)

        browser_row = QHBoxLayout()
        browser_row.addWidget(self.browser_input)
        browser_row.addWidget(self.browser_button)
        form.addRow("浏览器程序", browser_row)

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_input)
        output_row.addWidget(self.browse_button)
        form.addRow("保存目录", output_row)

        image_row = QHBoxLayout()
        image_row.addWidget(self.main_images_checkbox)
        image_row.addWidget(self.detail_images_checkbox)
        image_row.addStretch()
        form.addRow("图片范围", image_row)

        buttons = QHBoxLayout()
        buttons.addWidget(self.login_prepare_button)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.open_search_button)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch()
        buttons.addWidget(self.open_output_button)

        root = QVBoxLayout()
        root.addLayout(form)
        root.addWidget(self.status_label)
        root.addWidget(self.counter_label)
        root.addLayout(buttons)
        root.addWidget(self.log_text, stretch=1)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)

    def choose_browser(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "选择浏览器程序",
            self.browser_input.text() or "C:\\Program Files",
            "浏览器程序 (*.exe);;所有文件 (*.*)",
        )
        if selected:
            self.browser_input.setText(selected)

    def choose_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择保存目录", self.output_input.text())
        if selected:
            self.output_input.setText(selected)

    def open_login_browser(self) -> None:
        try:
            config = self._config_from_ui(require_keyword=False)
            config.validate_login_settings()
        except ValueError as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return

        config.user_data_dir.mkdir(parents=True, exist_ok=True)
        url = "https://www.taobao.com/"
        subprocess.Popen(
            [
                str(config.browser_path),
                f"--user-data-dir={config.user_data_dir}",
                "--new-window",
                url,
            ],
            close_fds=True,
        )
        self.append_log("已打开登录/验证准备窗口。请在该窗口登录或完成真人验证，完成后关闭这个窗口，再点“开始自动浏览保存”。")

    def start_task(self) -> None:
        try:
            config = self._config_from_ui()
            config.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return
        if _is_profile_in_use(config.user_data_dir):
            message = "登录/验证准备窗口还在占用浏览器资料目录。请先关闭它打开的 Chrome/Edge 窗口，再开始自动浏览保存。"
            self.append_log(message)
            QMessageBox.warning(self, "请先关闭登录窗口", message)
            return

        self.log_text.clear()
        self.status_label.setText("运行中")
        self.counter_label.setText("已处理 0 / 成功 0 / 失败 0")
        self.login_prepare_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.open_search_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.pause_button.setText("暂停")
        self.is_paused = False

        thread = QThread()
        worker = CrawlWorker(config)
        self.thread = thread
        self.worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_message.connect(self.append_log)
        worker.progress_changed.connect(self.update_progress)
        worker.finished.connect(self.task_finished)
        worker.failed.connect(self.task_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self.thread_finished)
        thread.start()

    def toggle_pause(self) -> None:
        if not self.worker:
            return
        self.is_paused = not self.is_paused
        self.worker.set_paused(self.is_paused)
        self.pause_button.setText("继续" if self.is_paused else "暂停")
        self.status_label.setText("已暂停" if self.is_paused else "运行中")

    def stop_task(self) -> None:
        if self.worker:
            self.worker.stop()
            self.status_label.setText("正在停止")
            self.append_log("正在停止任务，请稍候。")

    def task_finished(self) -> None:
        self.status_label.setText("已完成")
        self._set_idle_buttons()

    def task_failed(self, message: str) -> None:
        self.status_label.setText("出错")
        self.append_log(f"错误：{message}")
        QMessageBox.critical(self, "任务失败", message)
        self._set_idle_buttons()

    def _set_idle_buttons(self) -> None:
        self.login_prepare_button.setEnabled(True)
        self.start_button.setEnabled(True)
        self.open_search_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)

    def thread_finished(self) -> None:
        self.worker = None
        self.thread = None

    def append_log(self, message: str) -> None:
        self.log_text.append(message)

    def update_progress(self, processed: int, success: int, failed: int) -> None:
        self.counter_label.setText(f"已处理 {processed} / 成功 {success} / 失败 {failed}")

    def open_output_dir(self) -> None:
        path = Path(self.output_input.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def open_search_page(self) -> None:
        try:
            config = self._config_from_ui()
            config.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return

        url = f"https://s.taobao.com/search?q={quote_plus(config.keyword)}"
        if config.browser_path:
            subprocess.Popen([str(config.browser_path), url], close_fds=True)
        else:
            QDesktopServices.openUrl(QUrl(url))
        self.append_log(f"已打开搜索页：{url}")

    def _config_from_ui(self, require_keyword: bool = True) -> CrawlConfig:
        browser_text = self.browser_input.text().strip()
        keyword = self.keyword_input.text().strip() if require_keyword else "__login_prepare__"
        return CrawlConfig(
            keyword=keyword,
            max_products=self.max_products_input.value(),
            output_dir=Path(self.output_input.text()).expanduser(),
            delay_min_seconds=self.delay_min_input.value(),
            delay_max_seconds=self.delay_max_input.value(),
            scroll_rounds=self.scroll_rounds_input.value(),
            save_main_images=self.main_images_checkbox.isChecked(),
            save_detail_images=self.detail_images_checkbox.isChecked(),
            user_data_dir=Path.cwd() / "browser-profile",
            browser_path=Path(browser_text).expanduser() if browser_text else None,
        )


def main() -> int:
    _setup_logging()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


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


def _is_profile_in_use(profile_dir: Path) -> bool:
    profile_text = str(profile_dir.resolve()).replace("'", "''")
    script = (
        "$profile = '" + profile_text + "'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { "
        "($_.Name -eq 'chrome.exe' -or $_.Name -eq 'msedge.exe') "
        "-and $_.CommandLine -like \"*--user-data-dir=$profile*\" "
        "} | Select-Object -First 1 -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _setup_logging() -> None:
    log_dir = Path.cwd() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "app.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )

    def write_uncaught_exception(exc_type, exc, tb) -> None:
        logging.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        with (log_dir / "app.log").open("a", encoding="utf-8") as handle:
            handle.write("\n=== Uncaught exception ===\n")
            handle.write("".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = write_uncaught_exception
