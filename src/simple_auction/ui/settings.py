from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from simple_auction.services import api_key, lookup, numbering
from simple_auction.services.conditions import ConditionOption, cleaned, save_file
from simple_auction.services.config import Config
from simple_auction.services.serial_links import SerialLink, is_valid
from simple_auction.ui import strings


class SettingsDialog(QDialog):
    def __init__(self, config: Config, existing: list[int], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.SETTINGS)
        self.setMinimumWidth(640)

        self.folder = QLineEdit(str(config.base_dir))
        self.photos = QLineEdit(str(config.photos_dir))

        self._suggested = numbering.next_auction(existing, config.step, config.start_at)
        self.next_number = QLineEdit(str(self._suggested))
        self.next_number.setValidator(QIntValidator(1, 99_999_000, self.next_number))
        self.next_number.setFixedWidth(140)
        next_row = QHBoxLayout()
        next_row.addWidget(self.next_number)
        next_row.addStretch(1)

        edit_table = QPushButton(strings.EDIT_SERIAL_TABLE)
        edit_table.clicked.connect(self._edit_serial_table)
        table_row = QHBoxLayout()
        table_row.addWidget(edit_table)
        table_row.addStretch(1)

        # Links under the Serial # field: one row per link, name + URL.
        self.links = QTableWidget(0, 2)
        self.links.setObjectName("linksTable")
        self.links.setHorizontalHeaderLabels([strings.LINK_NAME, strings.LINK_URL])
        self.links.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.links.horizontalHeader().setStretchLastSection(True)
        self.links.verticalHeader().hide()
        self.links.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.links.setFixedHeight(130)
        for link in config.serial_links:
            self._add_link_row(link.name, link.url)
        add_link = QPushButton(strings.ADD_LINK)
        add_link.clicked.connect(self._new_link)
        remove_link = QPushButton(strings.REMOVE_LINK)
        remove_link.clicked.connect(self._remove_links)
        links_hint = QLabel(strings.LINKS_HINT)
        links_hint.setObjectName("hint")
        links_row = QHBoxLayout()
        links_row.addWidget(links_hint, 1)
        links_row.addWidget(add_link)
        links_row.addWidget(remove_link)

        # Conditions: name + the sentence added to the description. Row order
        # is the dropdown order; the first is the default for new lots.
        self.conditions_table = QTableWidget(0, 2)
        self.conditions_table.setObjectName("linksTable")
        self.conditions_table.setHorizontalHeaderLabels(
            [strings.CONDITION_NAME, strings.CONDITION_NOTE]
        )
        self.conditions_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.conditions_table.horizontalHeader().setStretchLastSection(True)
        self.conditions_table.verticalHeader().hide()
        self.conditions_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.conditions_table.setFixedHeight(160)
        self._original_conditions = list(config.conditions)
        for option in config.conditions:
            self._add_condition_row(option.name, option.note)
        self._conditions_path = config.conditions_path
        add_condition = QPushButton(strings.ADD_LINK)
        add_condition.clicked.connect(self._new_condition)
        remove_condition = QPushButton(strings.REMOVE_LINK)
        remove_condition.clicked.connect(self._remove_conditions)
        up = QPushButton(strings.MOVE_UP)
        up.clicked.connect(lambda: self._move_condition(-1))
        down = QPushButton(strings.MOVE_DOWN)
        down.clicked.connect(lambda: self._move_condition(1))
        conditions_hint = QLabel(strings.CONDITIONS_HINT)
        conditions_hint.setObjectName("hint")
        open_file = QPushButton(strings.OPEN_CONDITIONS_FILE)
        open_file.setToolTip(strings.OPEN_CONDITIONS_FILE_TIP)
        open_file.clicked.connect(self._open_conditions_file)
        conditions_row = QHBoxLayout()
        conditions_row.addWidget(conditions_hint, 1)
        conditions_row.addWidget(open_file)
        for button in (up, down, add_condition, remove_condition):
            conditions_row.addWidget(button)

        # Gemini API key: typed here, saved to the Keychain, never shown again.
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.forget_key = QPushButton(strings.FORGET_KEY)
        self.forget_key.clicked.connect(self._forget_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        key_row.addWidget(self.forget_key)
        self._refresh_key_state()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.addWidget(QLabel(strings.AUCTIONS_FOLDER))
        layout.addLayout(self._folder_row(self.folder, strings.PICK_FOLDER))
        layout.addSpacing(10)
        layout.addWidget(QLabel(strings.PHOTOS_FOLDER))
        layout.addLayout(self._folder_row(self.photos, strings.PICK_PHOTOS_FOLDER))
        layout.addSpacing(10)
        layout.addWidget(QLabel(strings.NEXT_AUCTION))
        layout.addLayout(next_row)
        layout.addSpacing(10)
        layout.addWidget(QLabel(strings.SERIAL_TABLE))
        layout.addLayout(table_row)
        layout.addSpacing(10)
        layout.addWidget(QLabel(strings.SERIAL_LINKS))
        layout.addWidget(self.links)
        layout.addLayout(links_row)
        layout.addSpacing(10)
        layout.addWidget(QLabel(strings.CONDITIONS))
        layout.addWidget(self.conditions_table)
        layout.addLayout(conditions_row)
        layout.addSpacing(10)
        layout.addWidget(QLabel(strings.API_KEY))
        layout.addLayout(key_row)
        layout.addSpacing(14)
        layout.addWidget(buttons)

    def base_dir(self) -> Path:
        return Path(self.folder.text()).expanduser()

    def photos_dir(self) -> Path:
        return Path(self.photos.text()).expanduser()

    def next_auction(self) -> int:
        text = self.next_number.text().strip()
        return int(text) if text.isdigit() else self._suggested

    def new_api_key(self) -> str | None:
        """A key typed in, or None to keep the current one."""
        return self.key.text().strip() or None

    def _refresh_key_state(self) -> None:
        saved = api_key.saved() is not None
        self.key.setPlaceholderText(
            strings.API_KEY_SAVED if saved else strings.API_KEY_PLACEHOLDER
        )
        self.forget_key.setEnabled(saved)

    def _forget_key(self) -> None:
        api_key.forget()
        self.key.clear()
        self._refresh_key_state()

    def serial_links(self) -> list[SerialLink]:
        """The rows that make a usable link (name + http(s) URL)."""
        rows = []
        for r in range(self.links.rowCount()):
            name, url = (self.links.item(r, c) for c in (0, 1))
            link = SerialLink(
                name.text().strip() if name else "", url.text().strip() if url else ""
            )
            if is_valid(link):
                rows.append(link)
        return rows

    def _add_link_row(self, name: str, url: str) -> int:
        row = self.links.rowCount()
        self.links.insertRow(row)
        self.links.setItem(row, 0, QTableWidgetItem(name))
        self.links.setItem(row, 1, QTableWidgetItem(url))
        return row

    def _new_link(self) -> None:
        row = self._add_link_row("", "https://")
        self.links.setCurrentCell(row, 0)
        self.links.editItem(self.links.item(row, 0))

    def _remove_links(self) -> None:
        for row in sorted(
            {i.row() for i in self.links.selectedIndexes()}, reverse=True
        ):
            self.links.removeRow(row)

    def original_conditions(self) -> list[ConditionOption]:
        return list(self._original_conditions)

    def _open_conditions_file(self) -> None:
        """Open conditions.yaml in the default text editor (or show it in the
        folder if no app is set up to open .yaml files)."""
        path = self._conditions_path
        if not path.exists():
            save_file(path, self._original_conditions)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def conditions(self) -> list[ConditionOption]:
        """The condition rows, in order (blank and repeated names dropped)."""
        table = self.conditions_table
        rows = []
        for r in range(table.rowCount()):
            name, note = (table.item(r, c) for c in (0, 1))
            rows.append(
                ConditionOption(
                    name.text() if name else "", note.text() if note else ""
                )
            )
        return cleaned(rows)

    def _add_condition_row(self, name: str, note: str) -> int:
        table = self.conditions_table
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(name))
        table.setItem(row, 1, QTableWidgetItem(note))
        return row

    def _new_condition(self) -> None:
        row = self._add_condition_row("", "")
        self.conditions_table.setCurrentCell(row, 0)
        self.conditions_table.editItem(self.conditions_table.item(row, 0))

    def _remove_conditions(self) -> None:
        table = self.conditions_table
        for row in sorted({i.row() for i in table.selectedIndexes()}, reverse=True):
            table.removeRow(row)

    def _move_condition(self, step: int) -> None:
        table = self.conditions_table
        row = table.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < table.rowCount():
            return
        for col in (0, 1):
            a, b = table.takeItem(row, col), table.takeItem(target, col)
            table.setItem(row, col, b)
            table.setItem(target, col, a)
        table.setCurrentCell(target, table.currentColumn())

    def _folder_row(self, field: QLineEdit, title: str) -> QHBoxLayout:
        browse = QPushButton(strings.BROWSE)
        browse.clicked.connect(lambda: self._browse(field, title))
        row = QHBoxLayout()
        row.addWidget(field, 1)
        row.addWidget(browse)
        return row

    def _browse(self, field: QLineEdit, title: str) -> None:
        chosen = QFileDialog.getExistingDirectory(self, title, field.text())
        if chosen:
            field.setText(chosen)

    def _edit_serial_table(self) -> None:
        path = lookup.table_path(Config(base_dir=self.base_dir()).data_dir)
        lookup.ensure_table(path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
