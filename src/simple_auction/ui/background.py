"""Run blocking catalogue work off Qt's GUI thread without changing callers."""

import logging
from collections.abc import Callable

from PySide6.QtCore import QEvent, QEventLoop, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

from simple_auction.services import image

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


class PhotoFixThread(QThread):
    """Brings saved lot photos up to the ProxiBid standard without blocking the UI."""

    fixed = Signal(int)  # how many photos were rewritten

    def __init__(self, photos_dir) -> None:
        super().__init__()
        self.photos_dir = photos_dir

    def run(self) -> None:
        try:
            self.fixed.emit(image.fix_library(self.photos_dir))
        except Exception:
            log.exception("Fixing saved photos failed")


class _Progress(QProgressDialog):
    # A file commit cannot safely be interrupted by closing its progress dialog.
    def reject(self) -> None:
        pass

    def closeEvent(self, event) -> None:
        event.ignore()


_E = QEvent.Type
_INPUT_EVENTS = frozenset(
    {
        _E.KeyPress,
        _E.KeyRelease,
        _E.ShortcutOverride,
        _E.Shortcut,
        _E.InputMethod,
        _E.MouseButtonPress,
        _E.MouseButtonRelease,
        _E.MouseButtonDblClick,
        _E.Wheel,
        _E.ContextMenu,
        _E.TouchBegin,
        _E.TouchUpdate,
        _E.TouchEnd,
        _E.TabletPress,
        _E.TabletRelease,
        _E.DragEnter,
        _E.DragMove,
        _E.Drop,
    }
)


class _InputBlocker(QObject):
    """Swallows user input app-wide. Unlike disabling the window, this leaves
    widgets looking the same (no flash on every autosave) and keeps keyboard
    focus where it is, so the field being typed in doesn't finish editing."""

    def eventFilter(self, _obj, event) -> bool:
        return event.type() in _INPUT_EVENTS


def run_io[T](parent: QWidget, label: str, operation: Callable[[], T]) -> T:
    """Keep painting/timers alive, but block edits until a consistent result.

    The worker never touches widgets. Callers retain synchronous success/failure
    semantics for save-before-navigation. Fast operations don't flash a dialog.
    """
    progress = _Progress(label, "", 0, 0, parent)
    progress.setCancelButton(None)
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    # Block input immediately, even before the delayed progress window is shown.
    app = QApplication.instance()
    blocker = _InputBlocker()
    app.installEventFilter(blocker)
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
        # QProgressDialog has its own delayed-show timer. hide() doesn't stop
        # it, and deleteLater() can be deferred by a following dialog.exec().
        # Reset before returning so completed work cannot reappear as a modal
        # loading window over the next dialog.
        progress.reset()
        progress.hide()
        progress.deleteLater()
        app.removeEventFilter(blocker)
