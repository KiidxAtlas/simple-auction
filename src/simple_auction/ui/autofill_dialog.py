"""Review research auto-fill suggestions before they go into the lot."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from simple_auction.models import Lot
from simple_auction.services.research import AUTOFILL_FIELDS, MAX_PHOTOS
from simple_auction.services.title_layout import (
    CUSTOM_PREFIX,
    CustomField,
    is_custom_key,
)
from simple_auction.ui import strings


def current_value(lot: Lot, key: str) -> str:
    """The lot's value for an auto-fill key (a Lot attribute or custom key)."""
    if is_custom_key(key):
        return lot.custom.get(key[len(CUSTOM_PREFIX) :], "")
    value = getattr(lot, key)
    return "" if value is None else str(value)


class AutofillDialog(QDialog):
    """One row per suggestion: tick it, adjust the text, then Fill.

    Empty fields start ticked; replacements always start unticked. Current
    values and reference photos are shown for an explicit review decision.
    """

    def __init__(
        self,
        suggestions: dict[str, str],
        lot: Lot,
        custom_fields: list[CustomField],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.AUTOFILL_TITLE)
        self.setObjectName("settingsDialog")
        self.setMinimumWidth(560)
        labels = {key: label for key, label, _hint in AUTOFILL_FIELDS}
        labels |= {f.key: f.label for f in custom_fields}
        self.rows: dict[str, tuple[QCheckBox, QLineEdit]] = {}

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        row = 0
        for key, label in labels.items():
            if key not in suggestions:
                continue
            current = current_value(lot, key).strip()
            suggested = suggestions[key]
            same = current.casefold() == suggested.casefold()
            check = QCheckBox(label)
            check.setChecked(not current)
            check.setEnabled(not same)
            edit = QLineEdit(suggested)
            if key in {name for name, _label, _hint in AUTOFILL_FIELDS}:
                edit.setProperty("spellcheck", False)
            edit.setAccessibleName(label)
            edit.setCursorPosition(0)
            edit.textEdited.connect(lambda _t, c=check: c.setChecked(True))
            grid.addWidget(check, row, 0)
            grid.addWidget(edit, row, 1)
            row += 1
            if current:
                note = QLabel(
                    strings.AUTOFILL_SAME
                    if same
                    else strings.AUTOFILL_REPLACES.format(value=current)
                )
                note.setObjectName("fieldHint")
                note.setWordWrap(True)
                grid.addWidget(note, row, 1)
                row += 1
            grid.setRowMinimumHeight(row, 8)
            row += 1
            self.rows[key] = (check, edit)

        body = QWidget()
        body.setObjectName("scrollBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 20, 8)
        intro = QLabel(strings.AUTOFILL_INTRO)
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        body_layout.addWidget(intro)
        body_layout.addSpacing(10)
        warning = QLabel(
            "AI suggestions are unverified. Check markings against the photos; "
            "O/0, I/1 and S/5 can be ambiguous. Leave uncertain fields unselected. "
            "Only explicitly selected values will be applied."
        )
        warning.setWordWrap(True)
        body_layout.addWidget(warning)
        for path in lot.photos[:MAX_PHOTOS]:
            photo = QLabel()
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                photo.setText(f"Photo unavailable: {path.name}")
            else:
                photo.setPixmap(
                    pixmap.scaled(
                        480,
                        200,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            photo.setAccessibleName(f"Reference photo: {path.name}")
            body_layout.addWidget(photo)
        body_layout.addLayout(grid)
        body_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.fill_button = buttons.addButton(
            strings.AUTOFILL_APPLY, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.fill_button.setObjectName("primary")
        self.fill_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QFrame()
        footer.setObjectName("settingsFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(20, 12, 20, 12)
        footer_layout.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(scroll, 1)
        layout.addWidget(footer)
        self.resize(620, min(140 + 64 * len(self.rows), 640))

    def selected(self) -> dict[str, str]:
        """The ticked suggestions, as edited: {key: value}."""
        return {
            key: edit.text().strip()
            for key, (check, edit) in self.rows.items()
            if check.isChecked() and check.isEnabled() and edit.text().strip()
        }
