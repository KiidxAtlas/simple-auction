"""A native single-line editor with a separately scrollable horizontal view."""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOptionFrame,
)

from simple_auction.ui.wheel_guard import forward_wheel_to_scroll_area


class ScrollableLineEdit(QScrollArea):
    """Keep QLineEdit's editing/undo API, without using its caret to pan text."""

    def __init__(self, edit: QLineEdit, parent=None):
        super().__init__(parent)
        self.edit = edit
        self._syncing = True
        self._wheel_remainder = 0.0
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusProxy(edit)
        self.setWidget(edit)
        self.setToolTip(
            "Scroll sideways, use Shift + mouse wheel, or drag the scrollbar to read a long title."
        )
        edit.installEventFilter(self)
        edit.textChanged.connect(self._sync_size)
        edit.cursorPositionChanged.connect(self._show_cursor)
        self._syncing = False
        self._sync_size()

    def sizeHint(self):
        return QSize(self.edit.sizeHint().width(), self.minimumHeight())

    def minimumSizeHint(self):
        return QSize(0, self.minimumHeight())

    def _sync_size(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            option = QStyleOptionFrame()
            self.edit.initStyleOption(option)
            metrics = self.edit.fontMetrics()
            margins = self.edit.textMargins()
            content = QSize(
                metrics.horizontalAdvance(self.edit.displayText())
                + margins.left()
                + margins.right()
                + 4,
                metrics.height() + margins.top() + margins.bottom() + 2,
            )
            natural = self.edit.style().sizeFromContents(
                QStyle.ContentsType.CT_LineEdit, option, content, self.edit
            )
            width = max(self.viewport().width(), natural.width())
            height = self.edit.sizeHint().height()
            self.edit.resize(width, height)
            bar_height = (
                self.horizontalScrollBar().sizeHint().height()
                if natural.width() > self.viewport().width()
                else 0
            )
            self.setFixedHeight(height + bar_height)
            self.updateGeometry()
        finally:
            self._syncing = False

    def _show_cursor(self):
        if not self._syncing:
            if self.edit.cursorPosition() == 0:
                self.horizontalScrollBar().setValue(0)
            else:
                cursor = self.edit.cursorRect()
                self.ensureVisible(cursor.center().x(), cursor.center().y(), 8, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "edit"):
            self._sync_size()

    def eventFilter(self, obj, event):
        if obj is self.edit:
            if event.type() == QEvent.Type.KeyPress:
                # Home/End still pan when the caret is already at that endpoint.
                if event.key() == Qt.Key.Key_Home:
                    self.horizontalScrollBar().setValue(0)
                elif event.key() == Qt.Key.Key_End:
                    self.horizontalScrollBar().setValue(
                        self.horizontalScrollBar().maximum()
                    )
            if event.type() == QEvent.Type.Wheel:
                self.wheelEvent(event)
                return True
            if event.type() in (
                QEvent.Type.FontChange,
                QEvent.Type.StyleChange,
                QEvent.Type.ContentsRectChange,
            ):
                self._sync_size()
        return super().eventFilter(obj, event)

    def wheelEvent(self, event):
        pixels, angle = event.pixelDelta(), event.angleDelta()
        shifted = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        direction = pixels if not pixels.isNull() else angle
        horizontal = (shifted and bool(direction.y())) or abs(direction.x()) > abs(
            direction.y()
        )
        if not horizontal:
            forward_wheel_to_scroll_area(self, event)
            return
        pixel_delta = (
            pixels.y() if shifted and abs(pixels.y()) > abs(pixels.x()) else pixels.x()
        )
        angle_delta = (
            angle.y() if shifted and abs(angle.y()) > abs(angle.x()) else angle.x()
        )
        bar = self.horizontalScrollBar()
        amount = (
            pixel_delta
            if pixel_delta
            else angle_delta / 120 * bar.singleStep() * QApplication.wheelScrollLines()
        )
        self._wheel_remainder += amount
        movement = int(self._wheel_remainder)
        self._wheel_remainder -= movement
        bar.setValue(bar.value() - movement)
        event.accept()
