"""Edit a short ordered list of records: a list on the left, the selected
record's fields on the right, with add / remove / reorder buttons."""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from simple_auction.ui import theme

ROLE = Qt.ItemDataRole.UserRole
# Side by side from this width; list above the fields when narrower.
SIDE_BY_SIDE_WIDTH = 540


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    placeholder: str = ""
    multiline: bool = False
    hint: str = ""


class ListEditor(QWidget):
    changed = Signal()

    def __init__(
        self,
        fields: list[Field],
        *,
        noun: str,
        add_label: str,
        empty_text: str,
        new_values: dict[str, str] | Callable[[], dict[str, str]] | None = None,
        accessible_name: str = "",
    ) -> None:
        super().__init__()
        self._fields = fields
        self._noun = noun
        self._new_values = new_values or {}
        self._loading = False

        self.list = QListWidget()
        self.list.setObjectName("editorList")
        self.list.setAccessibleName(accessible_name or noun)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setMinimumHeight(160)
        self.list.currentRowChanged.connect(self._show_current)
        self.list.model().rowsMoved.connect(self._update_buttons)

        self.add_button = QPushButton(add_label)
        theme.set_icon(self.add_button, "plus")
        self.add_button.clicked.connect(self.add)
        self.move_up = self._tool_button("up", f"Move {noun} up")
        self.move_up.clicked.connect(lambda: self.move(-1))
        self.move_down = self._tool_button("down", f"Move {noun} down")
        self.move_down.clicked.connect(lambda: self.move(1))
        self.remove_button = self._tool_button("trash", f"Remove {noun}")
        self.remove_button.clicked.connect(self.remove_current)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addWidget(self.add_button)
        buttons.addStretch(1)
        for button in (self.move_up, self.move_down, self.remove_button):
            buttons.addWidget(button)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self.list, 1)
        left.addLayout(buttons)

        # The selected record's fields, or a hint when nothing is selected.
        self.inputs: dict[str, QLineEdit | QPlainTextEdit] = {}
        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(6)
        for i, field in enumerate(fields):
            if i:
                form_layout.addSpacing(8)
            label = QLabel(field.label)
            label.setObjectName("fieldLabel")
            # Long labels wrap rather than widening the page on wide fonts.
            label.setWordWrap(True)
            if field.multiline:
                edit = QPlainTextEdit()
                edit.setTabChangesFocus(True)
                edit.setMinimumHeight(110)
                edit.textChanged.connect(self._store)
            else:
                edit = QLineEdit()
                edit.textChanged.connect(self._store)
            if field.key == "url":
                edit.setProperty("spellcheck", False)
            edit.setPlaceholderText(field.placeholder)
            edit.setAccessibleName(field.label)
            label.setBuddy(edit)
            self.inputs[field.key] = edit
            form_layout.addWidget(label)
            form_layout.addWidget(edit, 1 if field.multiline else 0)
            if field.hint:
                hint = QLabel(field.hint)
                hint.setObjectName("fieldHint")
                hint.setWordWrap(True)
                form_layout.addWidget(hint)
        if not any(f.multiline for f in fields):
            form_layout.addStretch(1)
        empty = QLabel(empty_text)
        empty.setObjectName("hint")
        empty.setWordWrap(True)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = QStackedWidget()
        self.detail.addWidget(empty)
        self.detail.addWidget(form)
        panel = QFrame()
        panel.setObjectName("editorPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 12, 14, 14)
        panel_layout.addWidget(self.detail)

        self.body = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(14)
        self.body.addLayout(left, 2)
        self.body.addWidget(panel, 3)
        self._update_buttons()

    @staticmethod
    def _tool_button(icon: str, tip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("iconButton")
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        theme.set_icon(button, icon)
        return button

    # -- data ---------------------------------------------------------------

    def rows(self) -> list[dict[str, str]]:
        return [dict(self.list.item(r).data(ROLE)) for r in range(self.list.count())]

    def add_row(self, values: dict[str, str]) -> None:
        """Add a record; keys other than the edited fields (e.g. an id) are kept."""
        item = QListWidgetItem()
        item.setData(
            ROLE, {**values, **{f.key: values.get(f.key, "") for f in self._fields}}
        )
        self._label(item)
        self.list.addItem(item)
        self._update_buttons()

    def select_first(self) -> None:
        """Show the first record's fields (instead of an empty form)."""
        if self.list.count():
            self.list.setCurrentRow(0)

    def add(self) -> None:
        new = self._new_values
        self.add_row(new() if callable(new) else new)
        self.list.setCurrentRow(self.list.count() - 1)
        first = self.inputs[self._fields[0].key]
        first.setFocus()
        self.changed.emit()

    def remove_current(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        self.list.takeItem(row)
        self._show_current(self.list.currentRow())
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

    def _label(self, item: QListWidgetItem) -> None:
        values = item.data(ROLE)
        name = values.get(self._fields[0].key, "").strip()
        item.setText(name or f"New {self._noun}")
        font = item.font()
        font.setItalic(not name)
        item.setFont(font)
        detail = values.get(self._fields[1].key, "") if len(self._fields) > 1 else ""
        item.setToolTip(detail)

    def _show_current(self, row: int) -> None:
        item = self.list.item(row) if row >= 0 else None
        self.detail.setCurrentIndex(1 if item else 0)
        self._loading = True
        for key, edit in self.inputs.items():
            text = item.data(ROLE).get(key, "") if item else ""
            if isinstance(edit, QPlainTextEdit):
                edit.setPlainText(text)
            else:
                edit.setText(text)
                edit.setCursorPosition(0)
        self._loading = False
        self._update_buttons()

    def _store(self, *_args) -> None:
        item = self.list.currentItem()
        if self._loading or item is None:
            return
        values = dict(item.data(ROLE))
        for key, edit in self.inputs.items():
            values[key] = (
                edit.toPlainText() if isinstance(edit, QPlainTextEdit) else edit.text()
            )
        item.setData(ROLE, values)
        self._label(item)
        self.changed.emit()

    def _update_buttons(self, *_args) -> None:
        row = self.list.currentRow()
        selected = row >= 0
        self.remove_button.setEnabled(selected)
        self.move_up.setEnabled(selected and row > 0)
        self.move_down.setEnabled(selected and row < self.list.count() - 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.body.setDirection(
            QBoxLayout.Direction.LeftToRight
            if self.width() >= SIDE_BY_SIDE_WIDTH
            else QBoxLayout.Direction.TopToBottom
        )
