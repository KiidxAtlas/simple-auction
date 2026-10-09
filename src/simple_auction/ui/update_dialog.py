"""Check for Updates dialog."""

from __future__ import annotations

import logging
import platform
import subprocess
import webbrowser
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from simple_auction.services.updates import (
    UpdateCheckError,
    UpdateInfo,
    can_install_update_windows,
    check_for_updates,
    download_update,
    get_current_version,
    get_releases_page_url,
    launch_windows_installer,
    update_staging_path,
)
from simple_auction.ui import strings, theme

_LOG = logging.getLogger(__name__)
# Network threads outlive a closed dialog until their request finishes;
# destroying a running QThread would crash Qt, so they're kept here.
_DETACHED_THREADS: set[QThread] = set()


def keep_until_finished(thread: QThread) -> None:
    """Hold a still-running network thread until it ends on its own."""
    thread.setParent(None)
    _DETACHED_THREADS.add(thread)
    thread.finished.connect(lambda: _DETACHED_THREADS.discard(thread))


class UpdateCheckThread(QThread):
    """Background thread for checking updates."""

    checkComplete = Signal(object, str)  # UpdateInfo | None, why it failed

    def run(self) -> None:
        try:
            self.checkComplete.emit(check_for_updates(timeout=10), "")
        except UpdateCheckError as exc:
            self.checkComplete.emit(None, str(exc))
        except Exception as exc:  # noqa: BLE001 - never leave it stuck on "Checking…"
            _LOG.exception("Update check failed")
            self.checkComplete.emit(None, f"{type(exc).__name__}: {exc}")


class UpdateDownloadThread(QThread):
    """Background thread for downloading update artifacts."""

    downloadComplete = Signal(bool, str, str)  # success, path, system
    downloadProgress = Signal(int, int)  # downloaded bytes, total bytes or 0

    def __init__(
        self, url: str, dest_path: Path, system: str, sha256: str, parent=None
    ) -> None:
        super().__init__(parent)
        self._url = url
        self._dest_path = dest_path
        self._system = system
        self._sha256 = sha256

    def run(self) -> None:
        try:
            success = download_update(
                self._url,
                self._dest_path,
                expected_sha256=self._sha256,
                progress_cb=lambda done, total: self.downloadProgress.emit(
                    done, total or 0
                ),
            )
            self.downloadComplete.emit(success, str(self._dest_path), self._system)
        except (OSError, RuntimeError, ValueError) as exc:
            _LOG.error("Update download thread error: %s", exc)
            self.downloadComplete.emit(False, str(self._dest_path), self._system)


class UpdateDialog(QDialog):
    """Shows whether an update is available and installs it."""

    def __init__(
        self, parent: QWidget | None = None, update_info: UpdateInfo | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.UPDATES_TITLE)
        self.resize(560, 440)
        self.setMinimumSize(460, 320)
        self.setModal(True)

        self._update_info = update_info
        self._check_thread: UpdateCheckThread | None = None
        self._download_thread: UpdateDownloadThread | None = None
        self._download_progress: QProgressDialog | None = None
        self._download_btn: QPushButton | None = None

        title = QLabel(strings.UPDATES_TITLE)
        title.setObjectName("emptyTitle")
        subtitle = QLabel(strings.UPDATES_CURRENT.format(version=get_current_version()))
        subtitle.setObjectName("hint")

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(theme.SPACING)

        self._close_btn = QPushButton(strings.UPDATES_CLOSE)
        self._close_btn.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(theme.SPACING)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(content, 1)
        layout.addLayout(buttons)

        if update_info is None:
            self._show_checking()
        else:
            self._show_result(update_info)

    # -- states -------------------------------------------------------------

    def _clear_content(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().deleteLater()

    def _show_checking(self) -> None:
        status = QLabel(strings.UPDATES_CHECKING)
        status.setObjectName("hint")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_layout.addWidget(status, 1)
        self._check_thread = UpdateCheckThread()
        self._check_thread.checkComplete.connect(self._on_check_complete)
        self._check_thread.start()

    def _on_check_complete(self, info: UpdateInfo | None, error: str = "") -> None:
        self._update_info = info
        self._clear_content()
        self._show_result(info, error)

    def _show_result(self, info: UpdateInfo | None, error: str = "") -> None:
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 18)
        card_layout.setSpacing(10)

        heading = QLabel()
        heading.setObjectName("cardTitle")
        message = QLabel()
        message.setWordWrap(True)
        card_layout.addWidget(heading)
        card_layout.addWidget(message)

        if info is None:
            heading.setText(strings.UPDATES_FAILED_TITLE)
            message.setText(error or strings.UPDATES_FAILED)
        elif not info.is_newer:
            heading.setText(strings.UPDATES_UP_TO_DATE)
            message.setText(strings.UPDATES_LATEST.format(version=info.version))
        else:
            heading.setText(strings.UPDATES_AVAILABLE.format(version=info.version))
            message.setText(strings.UPDATES_AVAILABLE_BODY)
            if info.release_notes:
                notes = QTextBrowser()
                notes.setObjectName("transcript")
                notes.setOpenExternalLinks(True)
                notes.setMarkdown(info.release_notes)
                card_layout.addWidget(notes, 1)

            page = QPushButton(strings.UPDATES_RELEASE_PAGE)
            page.clicked.connect(lambda: webbrowser.open(get_releases_page_url()))
            self._download_btn = QPushButton(strings.UPDATES_INSTALL)
            self._download_btn.setObjectName("primary")
            self._download_btn.clicked.connect(lambda: self._download_and_install(info))
            if not info.sha256:
                self._download_btn.setEnabled(False)
                self._download_btn.setToolTip(strings.UPDATES_NO_CHECKSUM_TIP)
            actions = QHBoxLayout()
            actions.addStretch(1)
            actions.addWidget(page)
            actions.addWidget(self._download_btn)
            card_layout.addLayout(actions)

        self._content_layout.addWidget(card, 1)

    # -- download and install -----------------------------------------------

    def _download_and_install(self, info: UpdateInfo) -> None:
        if not info.sha256:
            QMessageBox.warning(
                self, strings.UPDATES_NOT_VERIFIED_TITLE, strings.UPDATES_NOT_VERIFIED
            )
            return

        system = platform.system()
        download_path = update_staging_path(info.version, system)
        self._set_download_busy(True)

        if self._download_progress is None:
            self._download_progress = QProgressDialog(self)
        self._download_progress.setWindowTitle(strings.UPDATES_DOWNLOADING_TITLE)
        self._download_progress.setLabelText(
            strings.UPDATES_DOWNLOADING.format(version=info.version)
        )
        self._download_progress.setCancelButton(None)
        self._download_progress.setRange(0, 0)
        self._download_progress.setMinimumDuration(0)
        self._download_progress.setModal(True)
        self._download_progress.show()

        self._download_thread = UpdateDownloadThread(
            info.url, download_path, system, info.sha256, parent=self
        )
        self._download_thread.downloadProgress.connect(self._on_download_progress)
        self._download_thread.downloadComplete.connect(self._on_download_complete)
        self._download_thread.start()

    def _on_download_progress(self, bytes_done: int, total: int) -> None:
        if self._download_progress is None:
            return
        if total <= 0:
            self._download_progress.setRange(0, 0)
            return
        self._download_progress.setRange(0, total)
        self._download_progress.setValue(min(bytes_done, total))
        percent = int(bytes_done * 100 / total)
        self._download_progress.setLabelText(
            strings.UPDATES_PERCENT.format(percent=percent)
        )

    def _on_download_complete(self, success: bool, path: str, system: str) -> None:
        if self._download_progress is not None:
            self._download_progress.hide()
            self._download_progress.deleteLater()
            self._download_progress = None
        self._set_download_busy(False)
        download_path = Path(path)

        if not success:
            QMessageBox.critical(
                self,
                strings.UPDATES_DOWNLOAD_FAILED_TITLE,
                strings.UPDATES_DOWNLOAD_FAILED,
            )
            return

        if system == "Windows" and can_install_update_windows():
            if launch_windows_installer(download_path):
                # The installer closes this app, replaces it and offers to relaunch.
                self.accept()
                QCoreApplication.quit()
                return
            _LOG.warning(
                "Windows installer launch failed; falling back to manual install"
            )

        QMessageBox.information(
            self,
            strings.UPDATES_READY_TITLE,
            strings.UPDATES_READY.format(path=download_path),
        )
        try:
            if system == "Windows":
                subprocess.Popen(["explorer", f"/select,{download_path}"])
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            _LOG.warning("Could not open the staged update: %s", exc)

    def _set_download_busy(self, busy: bool) -> None:
        if self._download_btn is not None:
            self._download_btn.setEnabled(not busy)
            self._download_btn.setText(
                strings.UPDATES_DOWNLOADING_BTN if busy else strings.UPDATES_INSTALL
            )
        self._close_btn.setEnabled(not busy)

    # -- lifetime -----------------------------------------------------------

    def done(self, result: int) -> None:
        # accept()/reject() hide the dialog without a closeEvent.
        self._detach_network_threads()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._detach_network_threads()
        super().closeEvent(event)

    def _detach_network_threads(self) -> None:
        """Let in-flight network threads finish after the dialog closes.

        A thread blocked in a network request can't be stopped, and
        destroying a running QThread is fatal in Qt, so disconnect it from
        this dialog and keep it alive until it finishes.
        """
        for attr in ("_check_thread", "_download_thread"):
            thread = getattr(self, attr, None)
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    thread.requestInterruption()
                    if isinstance(thread, UpdateCheckThread):
                        thread.checkComplete.disconnect()
                    else:
                        thread.downloadProgress.disconnect()
                        thread.downloadComplete.disconnect()
                    keep_until_finished(thread)
            except RuntimeError:
                pass  # already deleted by Qt
            setattr(self, attr, None)
