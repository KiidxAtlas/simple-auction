"""Short, non-blocking messages that float above the bottom of a window."""

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel, QWidget

DEFAULT_MS = 4000
MAX_WIDTH = 560
MARGIN = 24


class Toast(QLabel):
    """One message at a time; a new message replaces the current one."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Never steal clicks from what's underneath.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        parent.installEventFilter(self)

    def show_message(self, text: str, ms: int = DEFAULT_MS) -> None:
        self.setText(text)
        self._place()
        self.show()
        self.raise_()
        self._timer.start(ms)

    def _place(self) -> None:
        parent = self.parentWidget()
        natural = self.fontMetrics().horizontalAdvance(self.text()) + 40
        width = min(natural, MAX_WIDTH, parent.width() - 2 * MARGIN)
        self.setFixedWidth(max(width, 120))
        self.setFixedHeight(self.heightForWidth(self.width()))
        self.move(
            (parent.width() - self.width()) // 2,
            parent.height() - self.height() - MARGIN,
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False
