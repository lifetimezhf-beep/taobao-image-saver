from __future__ import annotations

import sys
from pathlib import Path

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
        self.resize(820, 620)
        self.worker: CrawlWorker | None = None
        self.thread: QThread | None = None
        self.is_paused = False

        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("例如：猫窝、键盘、收纳盒")

        self.max_products_input = QSpinBox()
        self.max_products_input.setRange(1, 100)
        self.max_products_input.setValue(3)

        self.delay_min_input = QDoubleSpinBox()
        self.delay_min_input.setRange(0.5, 120.0)
        self.delay_min_input.setSingleStep(0.5)
        self.delay_min_input.setValue(2.5)
        self.delay_min_input.setSuffix(" 秒")

        self.delay_max_input = QDoubleSpinBox()
        self.delay_max_input.setRange(0.5, 120.0)
        self.delay_max_input.setSingleStep(0.5)
        self.delay_max_input.setValue(5.0)
        self.delay_max_input.setSuffix(" 秒")

        self.scroll_rounds_input = QSpinBox()
        self.scroll_rounds_input.setRange(1, 30)
        self.scroll_rounds_input.setValue(5)

        self.output_input = QLineEdit(str(default_output_dir()))
        self.browse_button = QPushButton("选择目录")
        self.browse_button.clicked.connect(self.choose_output_dir)

        self.main_images_checkbox = QCheckBox("保存主图")
        self.main_images_checkbox.setChecked(True)
        self.detail_images_checkbox = QCheckBox("保存详情图")
        self.detail_images_checkbox.setChecked(True)

        self.status_label = QLabel("待开始")
        self.counter_label = QLabel("已处理 0 / 成功 0 / 失败 0")
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        self.start_button = QPushButton("开始")
        self.pause_button = QPushButton("暂停")
        self.stop_button = QPushButton("停止")
        self.open_output_button = QPushButton("打开保存目录")

        self.start_button.clicked.connect(self.start_task)
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
        buttons.addWidget(self.start_button)
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

    def choose_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择保存目录", self.output_input.text())
        if selected:
            self.output_input.setText(selected)

    def start_task(self) -> None:
        try:
            config = self._config_from_ui()
            config.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return

        self.log_text.clear()
        self.status_label.setText("运行中")
        self.counter_label.setText("已处理 0 / 成功 0 / 失败 0")
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.pause_button.setText("暂停")
        self.is_paused = False

        self.thread = QThread()
        self.worker = CrawlWorker(config)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log_message.connect(self.append_log)
        self.worker.progress_changed.connect(self.update_progress)
        self.worker.finished.connect(self.task_finished)
        self.worker.failed.connect(self.task_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

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
        self._reset_buttons()

    def task_failed(self, message: str) -> None:
        self.status_label.setText("出错")
        self.append_log(f"错误：{message}")
        QMessageBox.critical(self, "任务失败", message)
        self._reset_buttons()

    def _reset_buttons(self) -> None:
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
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

    def _config_from_ui(self) -> CrawlConfig:
        return CrawlConfig(
            keyword=self.keyword_input.text().strip(),
            max_products=self.max_products_input.value(),
            output_dir=Path(self.output_input.text()).expanduser(),
            delay_min_seconds=self.delay_min_input.value(),
            delay_max_seconds=self.delay_max_input.value(),
            scroll_rounds=self.scroll_rounds_input.value(),
            save_main_images=self.main_images_checkbox.isChecked(),
            save_detail_images=self.detail_images_checkbox.isChecked(),
            user_data_dir=Path.cwd() / "browser-user-data",
        )


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()

