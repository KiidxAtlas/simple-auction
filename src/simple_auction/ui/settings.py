from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from simple_auction.services import api_key, lookup, numbering
from simple_auction.services.conditions import ConditionOption, cleaned, save_file
from simple_auction.services.config import Config
from simple_auction.services.serial_links import SerialLink, is_valid
from simple_auction.ui import strings, theme
from simple_auction.ui.network_settings import NetworkSettings


class SettingsDialog(QDialog):
    def __init__(self, config: Config, existing: list[int], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.SETTINGS)
        self.setObjectName("settingsDialog")
        self.setMinimumWidth(640)

        self.network = NetworkSettings(config.sharing, self)

        self.folder = QLineEdit(str(config.base_dir))
        self.photos = QLineEdit(str(config.photos_dir))

        self.dark_mode_toggle = QCheckBox(strings.DARK_MODE)
        self.dark_mode_toggle.setChecked(
            theme.colors() == theme.DARK
            if config.dark_mode is None
            else config.dark_mode
        )
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
        self.links.setColumnWidth(0, 210)
        self.links.horizontalHeader().setStretchLastSection(True)
        self.links.verticalHeader().hide()
        self.links.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.links.setMinimumHeight(140)
        self.links.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        self.links.verticalHeader().setDefaultSectionSize(38)
        self.links.setWordWrap(False)
        self.links.setAccessibleName("Serial number links")
        for link in config.serial_links:
            self._add_link_row(link.name, link.url)
        add_link = QPushButton("Add link")
        add_link.clicked.connect(self._new_link)
        self.remove_link = QPushButton("Remove selected")
        remove_link = self.remove_link
        remove_link.setEnabled(False)
        self.links.itemSelectionChanged.connect(
            lambda: remove_link.setEnabled(bool(self.links.selectedIndexes()))
        )
        remove_link.clicked.connect(self._remove_links)
        links_hint = QLabel("Double-click a cell to edit. " + strings.LINKS_HINT)
        links_hint.setObjectName("hint")
        links_row = QHBoxLayout()
        links_hint.setWordWrap(True)
        links_row.addWidget(add_link)
        links_row.addWidget(remove_link)
        links_row.addStretch(1)

        # Conditions: name + the sentence added to the description. Row order
        # is the dropdown order.
        self.conditions_table = QTableWidget(0, 2)
        self.conditions_table.setObjectName("linksTable")
        self.conditions_table.setHorizontalHeaderLabels(
            [strings.CONDITION_NAME, strings.CONDITION_NOTE]
        )
        self.conditions_table.setColumnWidth(0, 210)
        self.conditions_table.horizontalHeader().setStretchLastSection(True)
        self.conditions_table.verticalHeader().hide()
        self.conditions_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.conditions_table.setMinimumHeight(320)
        self.conditions_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        self.conditions_table.setAccessibleName("Auction conditions")
        self.conditions_table.verticalHeader().setMinimumSectionSize(44)
        self.conditions_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.conditions_table.setWordWrap(True)
        self._original_conditions = list(config.conditions)
        for option in config.conditions:
            self._add_condition_row(option.name, option.note)
        self._conditions_path = config.conditions_path
        add_condition = QPushButton("Add condition")
        add_condition.clicked.connect(self._new_condition)
        self.remove_condition = QPushButton("Remove selected")
        remove_condition = self.remove_condition
        remove_condition.clicked.connect(self._remove_conditions)
        self.move_up = QPushButton("Move up")
        up = self.move_up
        up.clicked.connect(lambda: self._move_condition(-1))
        self.move_down = QPushButton("Move down")
        down = self.move_down
        down.clicked.connect(lambda: self._move_condition(1))
        self.conditions_table.itemSelectionChanged.connect(
            self._update_condition_actions
        )
        self.conditions_table.currentCellChanged.connect(self._update_condition_actions)
        self.conditions_table.model().rowsRemoved.connect(
            self._update_condition_actions
        )
        self._update_condition_actions()
        conditions_hint = QLabel(
            "Double-click a cell to edit. " + strings.CONDITIONS_HINT
        )
        conditions_hint.setObjectName("hint")
        open_file = QPushButton(strings.OPEN_CONDITIONS_FILE)
        open_file.setToolTip(strings.OPEN_CONDITIONS_FILE_TIP)
        open_file.clicked.connect(self._open_conditions_file)
        conditions_row = QHBoxLayout()
        conditions_hint.setWordWrap(True)
        for button in (add_condition, up, down, remove_condition):
            conditions_row.addWidget(button)
        conditions_row.addStretch(1)
        conditions_footer = QHBoxLayout()
        conditions_footer.addWidget(conditions_hint, 1)
        conditions_footer.addWidget(open_file)

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

        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.setDocumentMode(True)

        general = QWidget()
        general.setObjectName("scrollBody")
        general_layout = QVBoxLayout(general)
        general_layout.setSpacing(14)
        appearance = self._section("Appearance")
        appearance.layout().addWidget(self.dark_mode_toggle)
        general_layout.addWidget(appearance)
        general_layout.addWidget(self.network)
        folders = self._section("Folders")
        folders.layout().addWidget(QLabel(strings.AUCTIONS_FOLDER))
        folders.layout().addLayout(self._folder_row(self.folder, strings.PICK_FOLDER))
        folders.layout().addSpacing(6)
        folders.layout().addWidget(QLabel(strings.PHOTOS_FOLDER))
        folders.layout().addLayout(
            self._folder_row(self.photos, strings.PICK_PHOTOS_FOLDER)
        )
        general_layout.addWidget(folders)
        serial_table = self._section("Serial number lookup")
        serial_table.layout().addLayout(table_row)
        general_layout.addWidget(serial_table)
        research = self._section("Research")
        research.layout().addWidget(QLabel(strings.API_KEY))
        research.layout().addLayout(key_row)
        general_layout.addWidget(research)
        general_layout.addStretch(1)

        auction = QWidget()
        auction.setObjectName("scrollBody")
        auction_layout = QVBoxLayout(auction)
        auction_layout.setSpacing(14)
        numbering_section = self._section("Auction numbering")
        next_row.insertWidget(0, QLabel(strings.NEXT_AUCTION))
        numbering_section.layout().addLayout(next_row)
        auction_layout.addWidget(numbering_section)
        links = self._section(strings.SERIAL_LINKS.rstrip(":"))
        links.layout().addLayout(links_row)
        links.layout().addWidget(self.links, 1)
        links.layout().addWidget(links_hint)
        links.setMinimumHeight(links.layout().minimumSize().height())
        auction_layout.addWidget(links, 1)
        conditions = self._section(strings.CONDITIONS.rstrip(":"))
        conditions.layout().addLayout(conditions_row)
        conditions.layout().addWidget(self.conditions_table, 1)
        conditions.layout().addLayout(conditions_footer)
        conditions.setMinimumHeight(conditions.layout().minimumSize().height())
        auction_layout.addWidget(conditions, 3)
        self.tabs.addTab(self._scroll(auction), "Auction setup")
        self.tabs.addTab(self._scroll(general), "General")

        outer = QVBoxLayout(self)
        outer.addWidget(self.tabs, 1)
        outer.addWidget(buttons)
        available = self.screen().availableGeometry()
        self.resize(min(980, available.width() - 60), min(940, available.height() - 60))

    @staticmethod
    def _section(title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("settingsSection")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("settingsSectionTitle")
        layout.addWidget(heading)
        return frame

    @staticmethod
    def _scroll(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def accept(self):
        if self.network.validate():
            super().accept()
        else:
            self.tabs.setCurrentIndex(1)

    def sharing(self):
        return self.network.value()

    def dark_mode(self) -> bool:
        return self.dark_mode_toggle.isChecked()

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

    def _update_condition_actions(self, *_args) -> None:
        table = self.conditions_table
        selected = {i.row() for i in table.selectedIndexes()}
        row = table.currentRow()
        single = len(selected) == 1 and row in selected
        self.remove_condition.setEnabled(bool(selected))
        self.move_up.setEnabled(single and row > 0)
        self.move_down.setEnabled(single and row < table.rowCount() - 1)

    def _move_condition(self, step: int) -> None:
        table = self.conditions_table
        row = table.currentRow()
        target = row + step
        selected = {i.row() for i in table.selectedIndexes()}
        if (
            len(selected) != 1
            or row not in selected
            or not 0 <= target < table.rowCount()
        ):
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
