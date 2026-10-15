"""Owner filtering and PDF export for consignor review, never editing lots."""

from pathlib import Path

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from simple_auction.models import Lot
from simple_auction.services import review_sheet


class ReviewSheetDialog(QDialog):
    def __init__(self, auction_no: int, lots: list[Lot], parent=None):
        super().__init__(parent)
        self.auction_no = auction_no
        self.lots = list(lots)
        self.exported_path = None
        self.setWindowTitle(f"Auction {auction_no} — Consignor review sheets")
        self.resize(800, 700)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Select an owner, review the draft, then export a PDF to send to the consignor. These sheets do not change catalogue data."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.owner_combo = QComboBox()
        self.owner_combo.addItem("All owners (grouped)", None)
        for owner in review_sheet.owners(self.lots):
            self.owner_combo.addItem(owner or "Unassigned", owner)
        self.owner_combo.currentIndexChanged.connect(self._refresh)
        layout.addWidget(self.owner_combo)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setOpenLinks(False)
        layout.addWidget(self.preview, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.export_button = QPushButton("Export review PDF…")
        self.export_button.clicked.connect(self._export)
        layout.addWidget(self.export_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self):
        owner = self.owner_combo.currentData()
        groups = review_sheet.grouped_lots(self.lots, owner)
        count = sum(len(lots) for _, lots in groups)
        self.export_button.setEnabled(bool(count))
        self.summary.setText(f"{count} lots · {len(groups)} owner groups")
        if not count:
            self.preview.setPlainText("No lots available for review.")
            return
        document = review_sheet.build_document(
            self.auction_no, self.lots, owner=owner, screen_font=self.font()
        )
        document.setParent(self.preview)
        # QTextEdit disposes its previously owned document in setDocument().
        self.preview.setDocument(document)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and hasattr(self, "preview"):
            self._refresh()

    def _export(self):
        name, _ = QFileDialog.getSaveFileName(
            self,
            "New consignor review PDF",
            f"auction-{self.auction_no}-review.pdf",
            "PDF (*.pdf)",
        )
        if not name:
            return
        try:
            path = review_sheet.export_pdf(
                self.auction_no,
                self.lots,
                Path(name),
                owner=self.owner_combo.currentData(),
            )
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "PDF not exported", str(e))
            return
        self.exported_path = path
        self.summary.setText(f"Review PDF saved: {path}")
