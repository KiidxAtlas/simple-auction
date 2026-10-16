"""Short, non-blocking messages that float above the bottom of a window."""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from simple_auction.ui import theme

DEFAULT_MS = 4000
UNDO_MS = 8000
MAX_WIDTH = 560
MARGIN = 24
ACTION_WIDTH = 84  # room kept at the right of the text for the action button


class Toast(QLabel):
    """One message at a time; a new message replaces the current one.

    A message may carry one action (e.g. Undo). Without an action the toast
    never steals clicks from what's underneath.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.action = QPushButton(self)
        self.action.setObjectName("toastAction")
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.hide()
        self.action.clicked.connect(self._run_action)
        self._callback: Callable[[], object] | None = None
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._expire)
        parent.installEventFilter(self)

    def show_message(
        self,
        text: str,
        ms: int = DEFAULT_MS,
        action: tuple[str, Callable[[], object]] | None = None,
    ) -> None:
        self.setText(text)
        self._callback = action[1] if action else None
        has_action = action is not None
        if action:
            self.action.setText(action[0])
        self.action.setVisible(has_action)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, not has_action
        )
        theme.repolish(self, action=has_action)
        self._place()
        self.show()
        self.raise_()
        self._timer.start(ms)

    def _expire(self) -> None:
        self._callback = None  # lets go of whatever the action kept
        self.hide()

    def _run_action(self) -> None:
        callback, self._callback = self._callback, None
        self._timer.stop()
        self.hide()
        if callback is not None:
            callback()

    def _place(self) -> None:
        parent = self.parentWidget()
        extra = ACTION_WIDTH if self._callback is not None else 0
        natural = self.fontMetrics().horizontalAdvance(self.text()) + 40 + extra
        width = min(natural, MAX_WIDTH, parent.width() - 2 * MARGIN)
        self.setFixedWidth(max(width, 120 + extra))
        self.setFixedHeight(max(self.heightForWidth(self.width()), 40))
        self.move(
            (parent.width() - self.width()) // 2,
            parent.height() - self.height() - MARGIN,
        )
        self.action.setGeometry(
            self.width() - ACTION_WIDTH - 8, 6, ACTION_WIDTH, self.height() - 12
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False
