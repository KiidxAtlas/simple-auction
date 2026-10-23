"""Explicit, occurrence-by-occurrence auction spelling review."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from simple_auction.services.network import NetworkError


class AuctionSpellcheckDialog(QDialog):
    def __init__(self, auction, review, save, parent=None):
        super().__init__(parent)
        self.review, self.save = review, save
        self.setWindowTitle(f"Spell check — Auction {auction}")
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Review titles and descriptions offline. Each Replace saves one change immediately.\nClose keeps saved changes; Skip leaves this occurrence unchanged."
            )
        )
        self.location = QLabel()
        self.location.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.location)
        self.context = QPlainTextEdit()
        self.context.setReadOnly(True)
        layout.addWidget(self.context)
        layout.addWidget(QLabel("Suggestion or your own replacement:"))
        self.suggestions = QComboBox()
        self.suggestions.setEditable(True)
        layout.addWidget(self.suggestions)
        actions = QHBoxLayout()
        self.replace_button = QPushButton("Replace")
        self.skip_button = QPushButton("Skip")
        self.add_button = QPushButton("Add to dictionary")
        self.close_button = QPushButton("Close")
        for button in (
            self.replace_button,
            self.skip_button,
            self.add_button,
            self.close_button,
        ):
            button.setAutoDefault(False)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.replace_button.clicked.connect(self._replace)
        self.skip_button.clicked.connect(self._skip)
        self.add_button.clicked.connect(self._add)
        self.close_button.clicked.connect(self.accept)
        self._refresh()

    def _refresh(self):
        issue = self.review.current()
        active = issue is not None
        for widget in (
            self.replace_button,
            self.skip_button,
            self.add_button,
            self.suggestions,
        ):
            widget.setEnabled(active)
        self.suggestions.clear()
        if not active:
            self.location.setText(
                f"Review complete. {self.review.saved} replacement(s) saved."
            )
            self.context.clear()
            return
        self.location.setText(
            f"Lot {issue.number} · {'Title' if issue.field == 'title' else 'Description'} · {issue.word}"
        )
        self.context.setPlainText(getattr(self.review.lots[issue.number], issue.field))
        # QTextCursor uses UTF-16; service offsets are Python character offsets.
        text = self.context.toPlainText()
        cursor = self.context.textCursor()
        cursor.setPosition(len(text[: issue.start].encode("utf-16-le")) // 2)
        cursor.setPosition(
            len(text[: issue.end].encode("utf-16-le")) // 2, cursor.MoveMode.KeepAnchor
        )
        self.context.setTextCursor(cursor)
        self.suggestions.addItems(self.review.checker.suggest(issue.word))

    def _replace(self):
        try:
            self.review.replace(self.suggestions.currentText(), self.save)
        except (OSError, ValueError, NetworkError) as error:
            QMessageBox.warning(self, "Replacement not saved", str(error))
            return
        self._refresh()

    def _skip(self):
        self.review.skip()
        self._refresh()

    def _add(self):
        try:
            self.review.add()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Spelling dictionary", str(error))
            return
        self._refresh()
