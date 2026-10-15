"""Actionable catalogue work queue and explicit duplicate/relisting review."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from simple_auction.services import dossier


class WorkQueueDialog(QDialog):
    def __init__(self, auctions, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ready to publish — work queue")
        self.resize(850, 600)
        self.target = None
        self.auctions = auctions
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Double-click an issue to open the lot at the affected field. Readiness is a staff checklist, not a legal determination."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        filters = QHBoxLayout()
        self.auction = QComboBox()
        self.auction.addItem("All auctions", None)
        for number in sorted(auctions):
            self.auction.addItem(str(number), number)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter lots or issues…")
        filters.addWidget(self.auction)
        filters.addWidget(self.search)
        layout.addLayout(filters)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Auction / lot", "Listing / issue"])
        self.tree.setColumnWidth(0, 150)
        self.tree.itemDoubleClicked.connect(self._open)
        self.auction.currentIndexChanged.connect(self._refresh)
        self.search.textChanged.connect(self._refresh)
        layout.addWidget(self.tree)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        open_button = buttons.addButton(
            "Open selected issue", QDialogButtonBox.ButtonRole.ActionRole
        )
        open_button.clicked.connect(lambda: self._open(self.tree.currentItem()))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self):
        self.tree.clear()
        ready, pending = 0, 0
        query = self.search.text().strip().casefold()
        selected = self.auction.currentData()
        for auction, lots in sorted(self.auctions.items()):
            if selected is not None and auction != selected:
                continue
            for lot in lots:
                issues = dossier.issues(
                    lot, bool(dossier.duplicates(lot, auction, self.auctions))
                )
                if issues:
                    pending += 1
                else:
                    ready += 1
                text = f"{auction} {lot.lot_number} {lot.title} " + " ".join(
                    label for label, _target in issues
                )
                if query and query not in text.casefold():
                    continue
                parent = QTreeWidgetItem(
                    self.tree,
                    [f"{auction} / {lot.lot_number}", lot.title or "Untitled lot"],
                )
                parent.setData(
                    0, Qt.ItemDataRole.UserRole, (auction, lot.lot_number, "title")
                )
                for label, target in issues:
                    item = QTreeWidgetItem(parent, ["Needs review", label])
                    item.setData(
                        0, Qt.ItemDataRole.UserRole, (auction, lot.lot_number, target)
                    )
                if not issues:
                    QTreeWidgetItem(
                        parent, ["Ready", "All publication checks complete"]
                    )
                parent.setExpanded(bool(issues))
        self.summary.setText(f"{ready} ready · {pending} need review")

    def _open(self, item, _column=0):
        if item is not None and (target := item.data(0, Qt.ItemDataRole.UserRole)):
            self.target = target
            self.accept()


class DuplicateDialog(QDialog):
    def __init__(self, matches, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Possible duplicate / relisting")
        self.resize(650, 420)
        self.matches = matches
        self.choice = None
        self.target = None
        self.explanation = ""
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Matching make and serial are a warning, not proof of a duplicate. Serial numbers are not globally unique. Reusing research never replaces identification, photos, or listing text; review copied evidence before approval."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.list = QListWidget()
        for auction, lot in matches:
            self.list.addItem(f"Auction {auction} · Lot {lot.lot_number} — {lot.title}")
        if matches:
            self.list.setCurrentRow(0)
        layout.addWidget(self.list)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Explanation for keeping separate / relisting…")
        layout.addWidget(self.notes)
        actions = QHBoxLayout()
        for label, choice in (
            ("Open earlier lot", "open"),
            ("Mark as relisting & reuse research", "reuse"),
            ("Keep separate", "separate"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, choice=choice: self._choose(choice)
            )
            actions.addWidget(button)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose(self, choice):
        row = self.list.currentRow()
        if row < 0:
            return
        if choice == "separate" and not self.notes.text().strip():
            QMessageBox.warning(
                self,
                "Duplicate review",
                "Record why these entries should remain separate.",
            )
            return
        self.choice = choice
        self.target = self.matches[row]
        self.explanation = self.notes.text().strip()
        self.accept()
