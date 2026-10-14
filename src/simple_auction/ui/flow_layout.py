"""A layout that places widgets left to right and wraps them onto new rows."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._visible():
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def _visible(self) -> list[QLayoutItem]:
        return [
            item
            for item in self._items
            if item.widget() is None or not item.widget().isHidden()
        ]

    def _arrange(self, rect: QRect, *, move: bool) -> int:
        """Lay items out in rows (each vertically centered); returns the height."""
        margins = self.contentsMargins()
        area = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        gap = self.spacing()
        rows: list[list[tuple[QLayoutItem, QSize]]] = [[]]
        x = area.x()
        for item in self._visible():
            hint = item.sizeHint()
            hint.setWidth(min(hint.width(), max(area.width(), 0)))
            if rows[-1] and x + hint.width() > area.right() + 1:
                rows.append([])
                x = area.x()
            rows[-1].append((item, hint))
            x += hint.width() + gap
        y = area.y()
        for row in rows:
            height = max((hint.height() for _item, hint in row), default=0)
            x = area.x()
            for item, hint in row:
                if move:
                    top = y + (height - hint.height()) // 2
                    item.setGeometry(QRect(QPoint(x, top), hint))
                x += hint.width() + gap
            y += height + gap
        return max(0, y - gap - area.y()) + margins.top() + margins.bottom()
