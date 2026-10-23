"""Background update checking, downloading and user prompts."""

import shutil
import sys

from PyQt6.QtCore import QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox
from loguru import logger

from utils.updater import (
    APP_VERSION,
    UpdateCancelled,
    check_for_update,
    download_update,
    extract_update,
    update_staging_dir,
)


class UpdateCheckWorker(QThread):
    """Query GitHub Releases without blocking the GUI thread."""

    checked = pyqtSignal(dict)

    def run(self):
        self.checked.emit(check_for_update())


class UpdateDownloadWorker(QThread):
    """Download and unpack the portable update package in the background."""

    progress = pyqtSignal(int, int)
    ready = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, asset_url: str, asset_digest: str = "", parent=None):
        super().__init__(parent)
        self.asset_url = asset_url
        self.asset_digest = asset_digest
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        staging = update_staging_dir()
        try:
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
            archive = download_update(
                self.asset_url,
                staging / "update.zip",
                self.asset_digest,
                progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=lambda: self._cancelled,
            )
            source = extract_update(archive, staging / "extracted")
            self.ready.emit(str(source))
        except UpdateCancelled:
            shutil.rmtree(staging, ignore_errors=True)
            self.cancelled.emit()
        except Exception as exc:
            logger.error(f"下载更新失败: {exc}")
            shutil.rmtree(staging, ignore_errors=True)
            self.failed.emit(str(exc))


def prompt_update(parent, result: dict, silent: bool = False):
    """Show the update prompt and return ``install``, ``browser`` or ``None``."""
    status = result.get("status")
    if status == "update":
        version = result.get("version", "")
        logger.info(f"发现新版本: v{version}（当前 v{APP_VERSION}）")
        can_install = getattr(sys, "frozen", False) and bool(result.get("asset_url"))
        box = QMessageBox(parent)
        box.setWindowTitle("发现新版本")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"发现新版本 v{version}（当前 v{APP_VERSION}）。")
        box.setInformativeText(
            "点击“立即更新”会自动下载、替换文件并重启程序，本地 data 数据会保留。"
            if can_install
            else "是否打开发布页面查看？"
        )
        install_button = (
            box.addButton("立即更新", QMessageBox.ButtonRole.AcceptRole)
            if can_install
            else None
        )
        open_button = box.addButton("打开发布页", QMessageBox.ButtonRole.ActionRole)
        box.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if install_button is not None and clicked is install_button:
            return "install"
        if clicked is open_button:
            QDesktopServices.openUrl(QUrl(result.get("url", "")))
            return "browser"
        return None
    if status == "latest":
        logger.info(f"检查更新: 当前已是最新版本 v{APP_VERSION}")
        if not silent:
            QMessageBox.information(
                parent, "检查更新", f"当前已是最新版本（v{APP_VERSION}）。"
            )
    else:
        message = result.get("message", "未知错误")
        logger.warning(f"检查更新失败: {message}")
        if not silent:
            QMessageBox.warning(parent, "检查更新", f"检查更新失败：{message}")
    return None
