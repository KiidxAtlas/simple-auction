"""Confirm columns from a Proxibid Winning Bidders CSV before importing."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from simple_auction.services import shipping
from simple_auction.services.importer import Sheet


class ShippingImportDialog(QDialog):
    def __init__(self, path: Path, sheet: Sheet, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Proxibid shipping orders")
        self.resize(880, 540)
        self._path = path
        self._sheet = sheet
        self.batch: shipping.Batch | None = None
        layout = QVBoxLayout(self)
        heading = QLabel("Review your buyers")
        heading.setObjectName("emptyTitle")
        layout.addWidget(heading)
        note = QLabel(
            f"{path.name}\nEach buyer's lots have been combined. Check the names and shipping addresses below."
        )
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        note.setObjectName("hint")
        layout.addWidget(note)
        basic = QGridLayout()
        self.auction = QLineEdit(path.stem)
        self.auction.setPlaceholderText("Auction name")
        self.country = QLineEdit("US")
        self.country.setMaxLength(2)
        self.country.setMaximumWidth(75)
        basic.addWidget(QLabel("Save auction as"), 0, 0)
        basic.addWidget(self.auction, 0, 1)
        basic.addWidget(QLabel("Country if blank"), 0, 2)
        basic.addWidget(self.country, 0, 3)
        basic.setColumnStretch(1, 1)
        layout.addLayout(basic)
        self.mapping_button = QPushButton("Adjust CSV columns")
        self.mapping_button.setObjectName("link")
        self.mapping_button.setCheckable(True)
        layout.addWidget(self.mapping_button)
        self.mapping_panel = QScrollArea()
        self.mapping_panel.setWidgetResizable(True)
        self.mapping_panel.setMaximumHeight(240)
        self.mapping_panel.setMinimumHeight(220)
        column_body = QWidget()
        grid = QGridLayout(column_body)
        self.columns: dict[str, QComboBox] = {}
        guessed = shipping.guess_mapping(sheet.headers)
        for i, (key, label) in enumerate(shipping.FIELDS.items()):
            combo = QComboBox()
            combo.addItem("Not in report", None)
            for col, header in enumerate(sheet.headers):
                combo.addItem(header or f"Column {col + 1}", col)
            combo.setCurrentIndex(0 if guessed[key] is None else guessed[key] + 1)
            self.columns[key] = combo
            row, column = divmod(i, 2)
            grid.addWidget(QLabel(label), row, column * 2)
            grid.addWidget(combo, row, column * 2 + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.mapping_panel.setWidget(column_body)
        self.mapping_panel.hide()
        self.mapping_button.toggled.connect(self.mapping_panel.setVisible)
        layout.addWidget(self.mapping_panel)
        preview_label = QLabel("Shipping addresses · first 20 buyers")
        preview_label.setObjectName("cardTitle")
        layout.addWidget(preview_label)
        self.preview = QTableWidget(0, 6)
        self.preview.setObjectName("linksTable")
        self.preview.setHorizontalHeaderLabels(
            ["Buyer", "Lots", "Address", "City / state", "Postal code", "Country"]
        )
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.verticalHeader().hide()
        self.preview.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.preview.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.preview, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import buyers")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.auction.textChanged.connect(self._refresh)
        self.country.textChanged.connect(self._refresh)
        for combo in self.columns.values():
            combo.currentIndexChanged.connect(self._refresh)
        self._refresh()
        self.mapping_button.setChecked(self.batch is None)

    def _refresh(self):
        self.batch = None
        try:
            self.batch = shipping.build_batch(
                self._sheet,
                {k: c.currentData() for k, c in self.columns.items()},
                self.auction.text(),
                self._path.name,
                self.country.text().strip(),
            )
            self.summary.setText(
                f"{len(self.batch.buyers)} buyers · {sum(len(b.lots) for b in self.batch.buyers)} lots. You can correct addresses after importing."
            )
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
                f"Import {len(self.batch.buyers)} buyers"
            )
        except shipping.ShippingError as e:
            self.summary.setText(str(e))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.batch is not None
        )
        buyers = self.batch.buyers[:20] if self.batch else []
        self.preview.setRowCount(len(buyers))
        for row, buyer in enumerate(buyers):
            values = [
                buyer.name,
                ", ".join(buyer.lots),
                f"{buyer.address1} {buyer.address2}",
                f"{buyer.city}, {buyer.state}",
                buyer.zip,
                buyer.country,
            ]
            for col, value in enumerate(values):
                self.preview.setItem(row, col, QTableWidgetItem(value))
