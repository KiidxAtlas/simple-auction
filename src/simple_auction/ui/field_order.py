"""A reorderable list of fields with a checkbox each (included or not)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from simple_auction.ui import strings
from simple_auction.ui.list_editor import ListEditor

KEY = Qt.ItemDataRole.UserRole


class FieldOrderList(QWidget):
    """Tick fields to include them; drag or use the arrows to order them.

    `fixed` keys are always included (no checkbox), e.g. the user's own title
    wording, which marks where generated text goes before and after.
    """

    changed = Signal()

    def __init__(self, accessible_name: str, fixed: dict[str, str] | None = None):
        super().__init__()
        self._fixed = fixed or {}
        self.list = QListWidget()
        self.list.setObjectName("editorList")
        self.list.setAccessibleName(accessible_name)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setMinimumHeight(300)
        self.list.itemChanged.connect(lambda _item: self.changed.emit())
        self.list.model().rowsMoved.connect(self._moved)
        self.list.currentRowChanged.connect(self._update_buttons)

        self.move_up = ListEditor._tool_button("up", strings.FIELD_MOVE_UP)
        self.move_up.clicked.connect(lambda: self.move(-1))
        self.move_down = ListEditor._tool_button("down", strings.FIELD_MOVE_DOWN)
        self.move_down.clicked.connect(lambda: self.move(1))
        hint = QLabel(strings.FIELD_ORDER_HINT)
        hint.setObjectName("fieldHint")
        hint.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addWidget(hint, 1)
        buttons.addWidget(self.move_up)
        buttons.addWidget(self.move_down)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)
        self._update_buttons()

    # -- contents -----------------------------------------------------------

    def add(self, key: str, label: str, checked: bool) -> None:
        item = QListWidgetItem()
        item.setData(KEY, key)
        self.list.blockSignals(True)
        self.list.addItem(item)
        if key in self._fixed:
            item.setText(self._fixed[key])
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
        else:
            item.setText(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
        self.list.blockSignals(False)
        self._update_buttons()

    def field_keys(self) -> list[str]:
        return [self.list.item(r).data(KEY) for r in range(self.list.count())]

    def included(self) -> list[str]:
        """Ticked (and fixed) keys, in order."""
        return [
            item.data(KEY)
            for r in range(self.list.count())
            if (item := self.list.item(r)).data(KEY) in self._fixed
            or item.checkState() == Qt.CheckState.Checked
        ]

    def item(self, key: str) -> QListWidgetItem | None:
        for r in range(self.list.count()):
            if self.list.item(r).data(KEY) == key:
                return self.list.item(r)
        return None

    def set_label(self, key: str, label: str) -> None:
        if (item := self.item(key)) is not None and item.text() != label:
            self.list.blockSignals(True)
            item.setText(label)
            self.list.blockSignals(False)

    def set_checked(self, key: str, checked: bool) -> None:
        if (item := self.item(key)) is not None and key not in self._fixed:
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def remove(self, key: str) -> None:
        if (item := self.item(key)) is not None:
            self.list.takeItem(self.list.row(item))
            self._update_buttons()
            self.changed.emit()

    def move(self, step: int) -> None:
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)
        self.changed.emit()

    # -- internals ----------------------------------------------------------

    def _moved(self, *_args) -> None:
        self._update_buttons()
        self.changed.emit()

    def _update_buttons(self, *_args) -> None:
        row = self.list.currentRow()
        self.move_up.setEnabled(row > 0)
        self.move_down.setEnabled(0 <= row < self.list.count() - 1)
