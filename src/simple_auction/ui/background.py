"""Run blocking catalogue work off Qt's GUI thread without changing callers."""

import logging
from collections.abc import Callable

from PySide6.QtCore import QEventLoop, Qt, QThread, QTimer
from PySide6.QtWidgets import QProgressDialog, QWidget

log = logging.getLogger(__name__)


class _Worker(QThread):
    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation
        self.result = None
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            self.result = self.operation()
        except Exception as e:
            log.exception("Catalogue operation failed")
            self.error = e


class _Progress(QProgressDialog):
    # A file commit cannot safely be interrupted by closing its progress dialog.
    def reject(self) -> None:
        pass

    def closeEvent(self, event) -> None:
        event.ignore()


def run_io[T](parent: QWidget, label: str, operation: Callable[[], T]) -> T:
    """Keep painting/timers alive, but block edits until a consistent result.

    The worker never touches widgets. Callers retain synchronous success/failure
    semantics for save-before-navigation. Fast operations don't flash a dialog.
    """
    progress = _Progress(label, "", 0, 0, parent)
    progress.setCancelButton(None)
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    # Block input immediately, even before the delayed progress window is shown.
    enabled = parent.isEnabled()
    parent.setEnabled(False)
    worker = _Worker(operation)
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    show_timer = QTimer()
    show_timer.setSingleShot(True)
    show_timer.timeout.connect(progress.show)
    show_timer.start(250)
    try:
        worker.start()
        loop.exec()
        worker.wait()
        if worker.error is not None:
            raise worker.error
        return worker.result
    finally:
        show_timer.stop()
        progress.hide()
        progress.deleteLater()
        parent.setEnabled(enabled)
