"""Import an old auction spreadsheet: pick columns, check a preview, import."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from simple_auction.models import Lot
from simple_auction.services import importer
from simple_auction.ui import strings, theme

PREVIEW_ROWS = 50

# Field -> label in the column picker, in display order.
FIELD_LABELS = {
    "lot_number": strings.IMPORT_LOT,
    "title": strings.TITLE,
    "desc": strings.DESC,
    "serial": strings.SERIAL,
    "condition": strings.CONDITION,
    "year": strings.YEAR,
    "make": strings.MAKE,
    "model": strings.MODEL,
    "owner": strings.OWNER,
    "book_no": strings.BOOK_NO,
}

PREVIEW_COLUMNS = [
    ("lot_number", strings.IMPORT_LOT),
    ("title", strings.TITLE),
    ("serial", strings.SERIAL),
    ("condition", strings.CONDITION),
    ("year", strings.YEAR),
    ("owner", strings.OWNER),
    ("desc", strings.DESC),
]


class ImportDialog(QDialog):
    def __init__(
        self,
        path: Path,
        sheet: importer.Sheet,
        existing_auctions: list[int],
        lots_in_auction: Callable[[int], set[int]],
        suggested_auction: int,
        step: int,
        condition_names: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.IMPORT_TITLE)
        self.resize(860, 640)
        self._sheet = sheet
        self._existing = set(existing_auctions)
        self._lots_in_auction = lots_in_auction
        self._step = step
        self._condition_names = condition_names or []
        self._lots: list[Lot] = []

        heading = QLabel(strings.IMPORT_HEADING.format(name=path.name))
        heading.setObjectName("emptyTitle")
        rows_label = QLabel(strings.IMPORT_ROWS.format(n=len(sheet.rows)))
        rows_label.setObjectName("hint")

        # Auction number, guessed from the lot numbers or the file name.
        mapping = importer.guess_mapping(sheet.headers)
        numbers = importer.lot_numbers(sheet, mapping["lot_number"])
        guess = importer.guess_auction_number(path, numbers, step)
        self.auction = QLineEdit(str(guess or suggested_auction))
        self.auction.setValidator(QIntValidator(1, 99_999_000, self.auction))
        self.auction.setFixedWidth(140)
        self.auction.textChanged.connect(self._refresh)
        self.auction_note = QLabel()
        self.auction_note.setObjectName("hint")
        self.auction_note.setWordWrap(True)
        auction_row = QHBoxLayout()
        auction_row.addWidget(QLabel(strings.IMPORT_AUCTION))
        auction_row.addWidget(self.auction)
        auction_row.addWidget(self.auction_note, 1)

        self.renumber = QCheckBox(strings.IMPORT_RENUMBER)
        self.renumber.setChecked(
            not numbers or not importer.lots_in_range(numbers, guess or 0, step)
        )
        self.renumber.toggled.connect(self._refresh)

        # One dropdown per field: which spreadsheet column fills it.
        self.columns: dict[str, QComboBox] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACING)
        grid.setVerticalSpacing(6)
        choices = [strings.IMPORT_SKIP] + [
            h or strings.IMPORT_UNNAMED.format(n=i + 1)
            for i, h in enumerate(sheet.headers)
        ]
        for i, (name, label) in enumerate(FIELD_LABELS.items()):
            combo = QComboBox()
            combo.addItems(choices)
            column = mapping.get(name)
            combo.setCurrentIndex(0 if column is None else column + 1)
            combo.currentIndexChanged.connect(self._refresh)
            self.columns[name] = combo
            row, col = divmod(i, 2)
            grid.addWidget(QLabel(label), row, col * 2)
            grid.addWidget(combo, row, col * 2 + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.preview = QTableWidget(0, len(PREVIEW_COLUMNS))
        self.preview.setObjectName("linksTable")
        self.preview.setHorizontalHeaderLabels([label for _, label in PREVIEW_COLUMNS])
        self.preview.verticalHeader().hide()
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.summary = QLabel()

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            strings.IMPORT_BUTTON
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        columns_title = QLabel(strings.IMPORT_COLUMNS)
        columns_title.setObjectName("cardTitle")
        preview_title = QLabel(strings.IMPORT_PREVIEW)
        preview_title.setObjectName("cardTitle")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(heading)
        layout.addWidget(rows_label)
        layout.addSpacing(4)
        layout.addLayout(auction_row)
        layout.addWidget(self.renumber)
        layout.addSpacing(6)
        layout.addWidget(columns_title)
        layout.addLayout(grid)
        layout.addSpacing(6)
        layout.addWidget(preview_title)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.summary)
        layout.addWidget(self.buttons)

        self._refresh()

    # -- results ------------------------------------------------------------

    def auction_no(self) -> int:
        text = self.auction.text().strip()
        return int(text) if text.isdigit() else 0

    def lots(self) -> list[Lot]:
        return list(self._lots)

    # -- internals ----------------------------------------------------------

    def _mapping(self) -> dict[str, int | None]:
        return {
            name: (combo.currentIndex() - 1 if combo.currentIndex() > 0 else None)
            for name, combo in self.columns.items()
        }

    def _refresh(self) -> None:
        auction = self.auction_no()
        mapping = self._mapping()
        no_lot_column = mapping["lot_number"] is None
        self.renumber.setEnabled(not no_lot_column)
        self._lots = (
            importer.build_lots(
                self._sheet,
                mapping,
                auction,
                renumber=self.renumber.isChecked() or no_lot_column,
                step=self._step,
                conditions=self._condition_names,
            )
            if auction
            else []
        )

        exists = auction in self._existing
        self.auction_note.setText(
            strings.IMPORT_MERGE_NOTE.format(n=auction) if exists else ""
        )
        already = self._lots_in_auction(auction) if exists else set()
        new = [lot for lot in self._lots if lot.lot_number not in already]
        skipped = len(self._sheet.rows) - len(self._lots)
        summary = strings.IMPORT_SUMMARY.format(
            lots=strings.count(len(new), "lot"), n=auction
        )
        if len(new) < len(self._lots):
            summary += " " + strings.IMPORT_ALREADY.format(
                lots=strings.count(len(self._lots) - len(new), "lot")
            )
        if skipped:
            summary += " " + strings.IMPORT_SKIPPED.format(
                rows=strings.count(skipped, "row")
            )
        self.summary.setText(summary)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(new))
        self._fill_preview()

    def _fill_preview(self) -> None:
        shown = self._lots[:PREVIEW_ROWS]
        self.preview.setRowCount(len(shown))
        for r, lot in enumerate(shown):
            for c, (name, _) in enumerate(PREVIEW_COLUMNS):
                value = getattr(lot, name)
                text = "" if value is None else str(value)
                if name == "desc":
                    text = " ".join(text.split())[:80]
                self.preview.setItem(r, c, QTableWidgetItem(text))
