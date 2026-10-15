"""Editable lot evidence, comparable sales and publication review checklist."""

import base64
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from simple_auction.models import Lot
from simple_auction.services import dossier
from simple_auction.ui.flow_layout import FlowLayout


class DossierDialog(QDialog):
    def __init__(self, lot: Lot, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Lot {lot.lot_number} — Evidence & review")
        self.resize(760, 680)
        self.packet = dossier.validate(lot.dossier)
        self._attachment = ""
        self.tabs = QTabWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self._evidence_tab(lot)
        self._research_tab()
        self._comparables_tab()
        self._review_tab()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _tab(self, name):
        page = QWidget()
        layout = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, name)
        return layout

    @staticmethod
    def _hint(text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _evidence_tab(self, lot):
        layout = self._tab("Identification")
        layout.addWidget(
            self._hint(
                "Keep each source separately. Dates are estimates, not proof of legality, authenticity, or value. Conflicting dates remain visible; nothing here overwrites the lot's year."
            )
        )
        self.status = QComboBox()
        self.status.addItems(dossier.STATUSES)
        self.status.setCurrentText(self.packet["status"])
        layout.addWidget(self.status)
        self.findings = QListWidget()
        layout.addWidget(self.findings)
        self.year = QLineEdit()
        self.source = QLineEdit()
        self.checked = QLineEdit(datetime.now(UTC).date().isoformat())
        for edit in (self.year, self.source, self.checked):
            edit.setProperty("spellcheck", False)
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(90)
        self.attachment = QLabel("No supporting attachment")
        self.attachment.setWordWrap(True)
        form = QFormLayout()
        for label, widget in (
            ("Year / range", self.year),
            ("Source URL", self.source),
            ("Date checked", self.checked),
            ("Findings / uncertainty", self.notes),
            ("Supporting photo / PDF", self.attachment),
        ):
            form.addRow(label, widget)
        layout.addLayout(form)
        photo = QComboBox()
        photo.addItem("Choose an existing lot photo…", "")
        for path in lot.photos:
            photo.addItem(Path(path).name, str(path))
        photo.activated.connect(
            lambda i: (
                self._attach(Path(photo.itemData(i))) if photo.itemData(i) else None
            )
        )
        layout.addWidget(photo)
        actions = FlowLayout()
        for text, callback in (
            ("Attach photo / PDF…", self._pick_attachment),
            ("Save attachment…", self._export_attachment),
            ("Clear attachment", self._clear_attachment),
            ("New source", self._new_finding),
            ("Save source", self._save_finding),
            ("Remove source", self._remove_finding),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        # Wrap actions when larger accessibility fonts need more room.
        layout.addLayout(actions)
        self.conflict = QLabel()
        self.conflict.setWordWrap(True)
        layout.addWidget(self.conflict)
        self.findings.currentRowChanged.connect(self._select_finding)
        self._refresh_findings()

    def _refresh_findings(self):
        self.findings.clear()
        for item in self.packet["findings"]:
            self.findings.addItem(
                f"{item['year'] or 'Undated'} — {item['source_url'] or item['notes'][:70]}"
            )
        self.conflict.setText(
            "Conflicting dates: review all sources before approving."
            if dossier.conflicting_years(self.packet)
            else ""
        )

    def _new_finding(self):
        self.findings.setCurrentRow(-1)
        self.year.clear()
        self.source.clear()
        self.checked.setText(datetime.now(UTC).date().isoformat())
        self.notes.clear()
        self._clear_attachment()

    def _select_finding(self, row):
        if row < 0:
            return
        item = self.packet["findings"][row]
        self.year.setText(item["year"])
        self.source.setText(item["source_url"])
        self.checked.setText(item["checked_on"])
        self.notes.setPlainText(item["notes"])
        self._attachment = item["attachment"]
        self.attachment.setText(
            "Supporting attachment saved in packet"
            if self._attachment
            else "No supporting attachment"
        )

    def _save_finding(self):
        record = {
            "year": self.year.text().strip(),
            "source_url": self.source.text().strip(),
            "checked_on": self.checked.text().strip(),
            "notes": self.notes.toPlainText().strip(),
            "attachment": self._attachment,
        }
        if not any(record[k] for k in ("year", "source_url", "notes", "attachment")):
            return True
        packet = dossier.validate(self.packet)
        row = self.findings.currentRow()
        if row < 0:
            packet["findings"].append(record)
        else:
            packet["findings"][row] = record
        try:
            packet = dossier.validate(packet)
        except ValueError as error:
            QMessageBox.warning(self, "Evidence", str(error))
            return False
        self.packet = packet
        self._refresh_findings()
        self._new_finding()
        return True

    def _remove_finding(self):
        row = self.findings.currentRow()
        if row >= 0:
            del self.packet["findings"][row]
            self._refresh_findings()
            self._new_finding()

    def _clear_attachment(self):
        self._attachment = ""
        self.attachment.setText("No supporting attachment")

    def _pick_attachment(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Supporting photo or factory letter",
            "",
            "Evidence (*.jpg *.jpeg *.png *.webp *.pdf)",
        )
        if path:
            self._attach(Path(path))

    def _attach(self, path):
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError(
                    "Attachments must be 2 MB or smaller. Use a cropped photo or smaller PDF."
                )
            raw = path.read_bytes()
            if path.suffix.lower() == ".pdf":
                if not raw.startswith(b"%PDF-"):
                    raise ValueError("This file is not a PDF")
                mime = "application/pdf"
            else:
                import io

                from PIL import Image

                with Image.open(io.BytesIO(raw)) as image:
                    image.verify()
                mime = (
                    "image/jpeg"
                    if path.suffix.lower() in {".jpg", ".jpeg"}
                    else "image/png"
                    if path.suffix.lower() == ".png"
                    else "image/webp"
                )
            self._attachment = f"data:{mime};base64," + base64.b64encode(raw).decode(
                "ascii"
            )
            self.attachment.setText(f"{path.name} — embedded, portable with this lot")
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Attachment", str(error))

    def _export_attachment(self):
        if not self._attachment:
            return
        suffix = (
            ".pdf"
            if self._attachment.startswith("data:application/pdf;")
            else ".jpg"
            if self._attachment.startswith("data:image/jpeg;")
            else ".png"
            if self._attachment.startswith("data:image/png;")
            else ".webp"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save supporting attachment", "evidence" + suffix
        )
        if path:
            try:
                from simple_auction.services.storage import atomic_write

                atomic_write(
                    Path(path),
                    base64.b64decode(self._attachment.split(",", 1)[1], validate=True),
                )
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Attachment", str(error))

    def _research_tab(self):
        layout = self._tab("Research packet")
        layout.addWidget(
            self._hint(
                "Completed research answers are saved explicitly from Research. These are evidence for review, not automatically approved listing claims."
            )
        )
        entries = QListWidget()
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.anchorClicked.connect(
            lambda url: (
                QDesktopServices.openUrl(url)
                if dossier.safe_url(url.toString())
                else None
            )
        )
        for record in self.packet["research"]:
            entries.addItem(f"{record['checked_on']} — {record['question']}")

        def show(row):
            if row < 0:
                browser.clear()
                return
            record = self.packet["research"][row]
            browser.setPlainText(
                record["answer"]
                + "\n\nSources:\n"
                + "\n".join(f"{s['title']}: {s['url']}" for s in record["sources"])
            )

        entries.currentRowChanged.connect(show)
        layout.addWidget(entries)
        layout.addWidget(browser, 2)
        remove = QPushButton("Remove selected research record")

        def delete():
            row = entries.currentRow()
            if row >= 0:
                del self.packet["research"][row]
                entries.takeItem(row)
                browser.clear()

        remove.clicked.connect(delete)
        layout.addWidget(remove)
        self.research_question = QLineEdit()
        self.research_question.setPlaceholderText("Question for staff / consignor")
        self.research_answer = QPlainTextEdit()
        self.research_answer.setPlaceholderText(
            "Answer or staff note — leave blank for an unresolved question"
        )
        self.research_answer.setMaximumHeight(90)
        layout.addWidget(self.research_question)
        layout.addWidget(self.research_answer)
        add = QPushButton("Save question / staff note")
        layout.addWidget(add)

        def select_note(row):
            record = self.packet["research"][row] if row >= 0 else {}
            self.research_question.setText(record.get("question", ""))
            self.research_answer.setPlainText(record.get("answer", ""))

        def save_note():
            question = self.research_question.text().strip()
            answer = self.research_answer.toPlainText().strip()
            if not question and not answer:
                return True
            if not question:
                QMessageBox.warning(
                    self,
                    "Research packet",
                    "Give this question or staff note a heading.",
                )
                return False
            row = entries.currentRow()
            record = {
                "question": question,
                "answer": answer,
                "checked_on": datetime.now(UTC).date().isoformat(),
                "sources": [],
            }
            if row >= 0:
                previous = self.packet["research"][row]
                record["sources"] = previous["sources"]
                if (question, answer) == (previous["question"], previous["answer"]):
                    return True
                self.packet["research"][row] = record
                entries.item(row).setText(f"{record['checked_on']} — {question}")
            else:
                self.packet["research"].append(record)
                entries.addItem(f"{record['checked_on']} — {question}")
            entries.setCurrentRow(-1)
            select_note(-1)
            return True

        entries.currentRowChanged.connect(select_note)
        add.clicked.connect(save_note)
        self._save_research_note = save_note

    def _comparables_tab(self):
        layout = self._tab("Comparable sales")
        layout.addWidget(
            self._hint(
                "Record realized sales separately from asking prices. Price, currency and buyer's premium must be checked at the source. A few comparables are not an appraisal."
            )
        )
        self.comps = QListWidget()
        layout.addWidget(self.comps)
        self.comp_inputs = {}
        form = QFormLayout()
        for key, label in (
            ("kind", "Result type"),
            ("url", "Source URL"),
            ("sale_date", "Sale date"),
            ("price", "Price"),
            ("currency", "Currency"),
            ("premium", "Buyer's premium treatment"),
            ("condition", "Condition / configuration differences"),
            ("notes", "Notes"),
        ):
            widget = QComboBox() if key == "kind" else QLineEdit()
            if key == "kind":
                widget.addItems(["Sold", "Asking"])
            if key in {"url", "sale_date", "price", "currency"}:
                widget.setProperty("spellcheck", False)
            self.comp_inputs[key] = widget
            form.addRow(label, widget)
        layout.addLayout(form)
        actions = QHBoxLayout()
        for text, callback in (
            ("New", self._new_comp),
            ("Save comparable", self._save_comp),
            ("Remove", self._remove_comp),
            ("Open source", self._open_comp),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.comps.currentRowChanged.connect(self._select_comp)
        self._refresh_comps()

    def _refresh_comps(self):
        self.comps.clear()
        for record in self.packet["comparables"]:
            self.comps.addItem(
                f"{record['kind']} — {record['sale_date']} — {record['currency']} {record['price']}"
            )

    def _new_comp(self):
        self.comps.setCurrentRow(-1)
        for key, widget in self.comp_inputs.items():
            if key == "kind":
                widget.setCurrentIndex(0)
            else:
                widget.clear()

    def _select_comp(self, row):
        if row >= 0:
            for key, widget in self.comp_inputs.items():
                value = self.packet["comparables"][row][key]
                widget.setCurrentText(value) if key == "kind" else widget.setText(value)

    def _save_comp(self):
        record = {
            key: widget.currentText() if key == "kind" else widget.text().strip()
            for key, widget in self.comp_inputs.items()
        }
        if not any(value for key, value in record.items() if key != "kind"):
            return True
        if not record["url"] or not dossier.safe_url(record["url"]):
            QMessageBox.warning(
                self, "Comparable", "Enter an HTTP or HTTPS source URL."
            )
            return False
        row = self.comps.currentRow()
        if row < 0:
            self.packet["comparables"].append(record)
        else:
            self.packet["comparables"][row] = record
        self._refresh_comps()
        self._new_comp()
        return True

    def _remove_comp(self):
        row = self.comps.currentRow()
        if row >= 0:
            del self.packet["comparables"][row]
            self._refresh_comps()
            self._new_comp()

    def _open_comp(self):
        url = self.comp_inputs["url"].text().strip()
        if dossier.safe_url(url):
            QDesktopServices.openUrl(QUrl(url))

    def _review_tab(self):
        layout = self._tab("Publication review")
        layout.addWidget(
            self._hint(
                "These are staff attestations, not automated legal or authenticity checks. Mark a photo category reviewed only after checking coverage or documenting why it is not applicable."
            )
        )
        self.shots = {}
        for shot in dossier.SHOTS:
            box = QCheckBox(f"{shot} photo reviewed / not applicable")
            box.setChecked(shot in self.packet["required_shots"])
            self.shots[shot] = box
            layout.addWidget(box)
        self.research_complete = QCheckBox("Research complete")
        self.research_complete.setChecked(self.packet["research_complete"])
        self.approved = QCheckBox("Listing reviewed and approved")
        self.approved.setChecked(self.packet["review_approved"])
        layout.addWidget(self.research_complete)
        layout.addWidget(self.approved)
        form = QFormLayout()
        self.duplicate_notes = QLineEdit(self.packet["duplicate_notes"])
        self.relisted_from = QLineEdit(self.packet["relisted_from"])
        self.relisted_from.setProperty("spellcheck", False)
        form.addRow("Duplicate explanation", self.duplicate_notes)
        form.addRow("Relisted from auction / lot", self.relisted_from)
        layout.addLayout(form)
        layout.addStretch()

    def accept(self):
        # Final Save also commits pending source/comparable/note edits.
        if (
            not self._save_finding()
            or not self._save_comp()
            or not self._save_research_note()
        ):
            return
        self.packet.update(
            status=self.status.currentText(),
            required_shots=[s for s, box in self.shots.items() if box.isChecked()],
            research_complete=self.research_complete.isChecked(),
            review_approved=self.approved.isChecked(),
            duplicate_notes=self.duplicate_notes.text().strip(),
            relisted_from=self.relisted_from.text().strip(),
        )
        try:
            self.packet = dossier.validate(self.packet)
        except ValueError as error:
            QMessageBox.warning(self, "Research packet", str(error))
            return
        super().accept()
