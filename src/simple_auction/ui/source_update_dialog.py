"""Check for Updates when running from source: pull new commits, restart."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from simple_auction import __version__
from simple_auction.services import source_update
from simple_auction.services.source_update import SourceStatus, SourceUpdateError
from simple_auction.ui import strings, theme
from simple_auction.ui.update_dialog import keep_until_finished

log = logging.getLogger(__name__)


class SourceCheckThread(QThread):
    """git fetch + compare, off the UI thread (it touches the network)."""

    checked = Signal(object, str)  # SourceStatus | None, error message

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root

    def run(self) -> None:
        try:
            self.checked.emit(source_update.check(self._root), "")
        except SourceUpdateError as e:
            log.warning("Update check failed: %s", e)
            self.checked.emit(None, str(e))
        except Exception as e:  # never leave the window stuck on "Checking…"
            log.exception("Update check failed")
            self.checked.emit(None, f"{type(e).__name__}: {e}")


class SourceApplyThread(QThread):
    applied = Signal(str)  # error message, or "" on success

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root

    def run(self) -> None:
        try:
            source_update.apply(self._root)
            self.applied.emit("")
        except SourceUpdateError as e:
            log.warning("Update failed: %s", e)
            self.applied.emit(str(e))
        except Exception as e:
            log.exception("Update failed")
            self.applied.emit(f"{type(e).__name__}: {e}")


class SourceUpdateDialog(QDialog):
    restart_requested = Signal()

    def __init__(self, root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.UPDATES_TITLE)
        self.resize(520, 420)
        self.setModal(True)
        self._root = root
        self._threads: list[QThread] = []
        self._update_btn: QPushButton | None = None

        title = QLabel(strings.UPDATES_TITLE)
        title.setObjectName("emptyTitle")
        subtitle = QLabel(strings.SOURCE_UPDATES_CURRENT.format(version=__version__))
        subtitle.setObjectName("hint")

        content = QWidget()
        self._content = QVBoxLayout(content)
        self._content.setContentsMargins(0, 0, 0, 0)

        self._close_btn = QPushButton(strings.UPDATES_CLOSE)
        self._close_btn.clicked.connect(self.reject)
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

        self._message(strings.UPDATES_CHECKING)
        self._start(SourceCheckThread(root), "checked", self._on_checked)

    # -- states -------------------------------------------------------------

    def _clear(self) -> None:
        while self._content.count():
            item = self._content.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().deleteLater()

    def _message(self, text: str) -> None:
        self._clear()
        label = QLabel(text)
        label.setObjectName("hint")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        self._content.addWidget(label, 1)

    def _card(self, heading: str, body: str) -> QVBoxLayout:
        self._clear()
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)
        title = QLabel(heading)
        title.setObjectName("cardTitle")
        text = QLabel(body)
        text.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(text)
        self._content.addWidget(card, 1)
        return layout

    def _on_checked(self, status: SourceStatus | None, error: str) -> None:
        if status is None:
            self._card(strings.UPDATES_FAILED_TITLE, error)
            return
        if not status.behind:
            self._card(strings.UPDATES_UP_TO_DATE, strings.SOURCE_UP_TO_DATE)
            return
        layout = self._card(
            strings.SOURCE_AVAILABLE.format(
                changes=strings.count(status.behind, "change")
            ),
            strings.SOURCE_AVAILABLE_BODY,
        )
        changes = QListWidget()
        changes.setObjectName("photos")
        changes.addItems([f"• {c}" for c in status.changes])
        layout.addWidget(changes, 1)
        if status.local_changes:
            note = QLabel(strings.SOURCE_LOCAL_CHANGES)
            note.setObjectName("hint")
            note.setWordWrap(True)
            layout.addWidget(note)
        self._update_btn = QPushButton(strings.SOURCE_UPDATE_BUTTON)
        self._update_btn.setObjectName("primary")
        self._update_btn.clicked.connect(self._apply)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._update_btn)
        layout.addLayout(row)

    def _apply(self) -> None:
        if self._update_btn is not None:
            self._update_btn.setEnabled(False)
            self._update_btn.setText(strings.SOURCE_UPDATING)
        self._close_btn.setEnabled(False)
        self._start(SourceApplyThread(self._root), "applied", self._on_applied)

    def _on_applied(self, error: str) -> None:
        self._close_btn.setEnabled(True)
        if error:
            self._card(
                strings.SOURCE_FAILED_TITLE, strings.SOURCE_FAILED.format(error=error)
            )
            return
        self.accept()
        self.restart_requested.emit()

    # -- threads ------------------------------------------------------------

    def _start(self, thread: QThread, signal: str, slot) -> None:
        getattr(thread, signal).connect(slot)
        self._threads.append(thread)
        thread.start()

    def done(self, result: int) -> None:
        # A thread still waiting on git outlives the dialog; see update_dialog.
        for thread in self._threads:
            if thread.isRunning():
                for name in ("checked", "applied"):
                    signal = getattr(thread, name, None)
                    if signal is not None:
                        signal.disconnect()
                keep_until_finished(thread)
        self._threads.clear()
        super().done(result)
