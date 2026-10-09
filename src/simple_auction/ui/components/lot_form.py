from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QIcon,
    QIntValidator,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from simple_auction.constants import TITLE_MAX_LENGTH
from simple_auction.models import Lot
from simple_auction.services.conditions import DEFAULT_CONDITIONS, ConditionOption
from simple_auction.services.listing import (
    condition_desc,
    condition_title,
    find_option,
    make_model_desc,
    prefixed_title,
    title_prefix,
    untrimmed_title_length,
)
from simple_auction.services.lookup import LookupResult
from simple_auction.services.serial_links import SerialLink, build_url
from simple_auction.ui import strings, theme


def _field(label: str, widget: QWidget, aside: QWidget | None = None) -> QWidget:
    """A small label stacked above its input, with an optional note at the right."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    text = QLabel(label)
    text.setObjectName("fieldLabel")
    text.setBuddy(widget)
    label_row = QHBoxLayout()
    label_row.addWidget(text, 1)
    if aside is not None:
        label_row.addWidget(aside)
    layout.addLayout(label_row)
    layout.addWidget(widget)
    return box


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 18, 20, 20)
    layout.setSpacing(14)
    heading = QLabel(title)
    heading.setObjectName("cardTitle")
    layout.addWidget(heading)
    return card, layout


class LotForm(QWidget):
    changed = Signal()  # the user edited something; autosave soon
    save_now = Signal()  # Cmd/Ctrl+S: save without waiting
    export_requested = Signal()
    new_auction_requested = Signal()
    serial_lookup_requested = Signal(str)
    research_toggled = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._lot: Lot | None = None
        self._looked_up = ""  # last serial sent for lookup
        self._auction_no: int | None = None
        self._photos: list[Path] = []
        self._dirty = False
        self._loading = False
        self._has_links = False
        # The make/model last written into the title and description, so a
        # later edit replaces it instead of adding another copy.
        self._applied_title_fields = ("", "", "")  # make, model, serial
        # Condition choices from Settings, and the condition whose text is
        # currently in the title/description (so changing it replaces that).
        self._conditions: list[ConditionOption] = list(DEFAULT_CONDITIONS)
        self._applied_condition = ""

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty())
        self.stack.addWidget(self._build_editor())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        for field in (
            self.serial,
            self.year,
            self.make,
            self.model,
            self.title,
            self.owner,
            self.book_no,
        ):
            field.textChanged.connect(self._mark_dirty)
        self.desc.textChanged.connect(self._mark_dirty)
        self.condition.currentIndexChanged.connect(self._mark_dirty)

        save = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        save.activated.connect(self.save_now)

    # -- building -----------------------------------------------------------

    def _build_empty(self) -> QWidget:
        page = QWidget()
        page.setObjectName("content")
        title = QLabel(strings.EMPTY_TITLE)
        title.setObjectName("emptyTitle")
        body = QLabel(strings.EMPTY_BODY)
        body.setObjectName("hint")
        create = QPushButton(strings.CREATE_NEW)
        create.setObjectName("primary")
        create.clicked.connect(self.new_auction_requested)

        layout = QVBoxLayout(page)
        layout.addStretch(1)
        for w in (title, body):
            layout.addWidget(w, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(10)
        layout.addWidget(create, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        return page

    def _build_editor(self) -> QWidget:
        # Header: lot title on the left, actions on the right.
        self.heading = QLabel()
        self.heading.setObjectName("lotTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("subtitle")
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.heading)
        titles.addWidget(self.subtitle)

        export = QPushButton(strings.EXPORT)
        export.setToolTip(strings.EXPORT_TIP)
        export.clicked.connect(self.export_requested)
        self.research_btn = QPushButton(strings.RESEARCH)
        self.research_btn.setCheckable(True)
        self.research_btn.setToolTip(strings.RESEARCH_TIP)
        self.research_btn.toggled.connect(self.research_toggled)
        self.save_state = QLabel()
        self.save_state.setObjectName("saveState")

        header = QHBoxLayout()
        header.setSpacing(theme.SPACING)
        header.addLayout(titles, 1)
        header.addWidget(self.save_state, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(export, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.research_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # Item card.
        self.serial = QLineEdit()
        self.serial.setPlaceholderText(strings.SERIAL_PLACEHOLDER)
        self.year = QLineEdit()
        self.year.setPlaceholderText(strings.YEAR_PLACEHOLDER)
        self.year.setValidator(QIntValidator(0, 9999, self.year))
        self.year.setMaxLength(4)
        self.serial.editingFinished.connect(self._on_serial_done)
        self.condition = QComboBox()
        self.condition.setPlaceholderText(strings.PICK_CONDITION)
        self.condition.activated.connect(self._apply_condition)
        self.make = QLineEdit()
        self.make.setPlaceholderText(strings.MAKE_PLACEHOLDER)
        self.make.editingFinished.connect(self._apply_title_fields)
        self.model = QLineEdit()
        self.model.setPlaceholderText(strings.MODEL_PLACEHOLDER)
        self.model.editingFinished.connect(self._apply_title_fields)
        self.lookup_hint = QLabel()
        self.lookup_hint.setObjectName("hint")
        self.lookup_hint.setWordWrap(True)
        self.lookup_row = QWidget()
        lookup_layout = QHBoxLayout(self.lookup_row)
        lookup_layout.setContentsMargins(0, 0, 0, 0)
        lookup_layout.addWidget(self.lookup_hint, 1)
        self._links_layout = QHBoxLayout()
        self._links_layout.setSpacing(4)
        lookup_layout.addLayout(self._links_layout)
        self.lookup_row.hide()
        self.title = QLineEdit()
        self.title.setPlaceholderText(strings.TITLE_PLACEHOLDER)
        self.title.setMaxLength(TITLE_MAX_LENGTH)
        self.title.editingFinished.connect(self._apply_condition)
        self.title_count = QLabel()
        self.title_count.setObjectName("charCount")
        self.title.textChanged.connect(self._update_title_count)
        self.condition.currentIndexChanged.connect(self._update_title_count)
        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText(strings.DESC_PLACEHOLDER)
        self.desc.setMinimumHeight(130)
        self.desc.setTabChangesFocus(True)

        item_card, item_layout = _card(strings.ITEM_CARD)
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACING)
        grid.setVerticalSpacing(14)
        grid.addWidget(_field(strings.SERIAL, self.serial), 0, 0)
        grid.addWidget(_field(strings.YEAR, self.year), 0, 1)
        grid.addWidget(_field(strings.CONDITION, self.condition), 0, 2)
        grid.addWidget(self.lookup_row, 1, 0, 1, 3)
        grid.addWidget(_field(strings.MAKE, self.make), 2, 0)
        grid.addWidget(_field(strings.MODEL, self.model), 2, 1, 1, 2)
        grid.addWidget(_field(strings.TITLE, self.title, self.title_count), 3, 0, 1, 3)
        grid.addWidget(_field(strings.DESC, self.desc), 4, 0, 1, 3)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)
        item_layout.addLayout(grid)

        # Consignment card.
        self.owner = QLineEdit()
        self.owner.setPlaceholderText(strings.OWNER_PLACEHOLDER)
        self.book_no = QLineEdit()
        self.book_no.setPlaceholderText(strings.BOOK_PLACEHOLDER)
        owner_card, owner_layout = _card(strings.CONSIGNMENT_CARD)
        owner_grid = QGridLayout()
        owner_grid.setHorizontalSpacing(theme.SPACING)
        owner_grid.addWidget(_field(strings.OWNER, self.owner), 0, 0)
        owner_grid.addWidget(_field(strings.BOOK_NO, self.book_no), 0, 1)
        owner_grid.setColumnStretch(0, 3)
        owner_grid.setColumnStretch(1, 2)
        owner_layout.addLayout(owner_grid)

        # Photos card.
        photos_card, photos_layout = _card(strings.PHOTOS_CARD)
        add_photos = QPushButton(strings.ADD_PHOTOS)
        add_photos.clicked.connect(self._pick_photos)
        self.photos_hint = QLabel()
        self.photos_hint.setObjectName("hint")
        photo_bar = QHBoxLayout()
        photo_bar.addWidget(self.photos_hint, 1)
        photo_bar.addWidget(add_photos)
        self.photo_list = QListWidget()
        self.photo_list.setObjectName("photos")
        self.photo_list.setViewMode(QListView.ViewMode.IconMode)
        self.photo_list.setFlow(QListView.Flow.LeftToRight)
        self.photo_list.setWrapping(False)
        self.photo_list.setMovement(QListView.Movement.Static)
        self.photo_list.setSpacing(4)
        self.photo_list.setIconSize(QSize(theme.THUMB_SIZE, theme.THUMB_SIZE))
        self.photo_list.setFixedHeight(theme.THUMB_SIZE + 48)
        self.photo_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.photo_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            remove = QShortcut(QKeySequence(key), self.photo_list)
            remove.setContext(Qt.ShortcutContext.WidgetShortcut)
            remove.activated.connect(self._remove_selected_photo)
        photos_layout.addLayout(photo_bar)
        photos_layout.addWidget(self.photo_list)

        # Scrollable, centered column.
        column = QWidget()
        column.setMaximumWidth(theme.CONTENT_MAX_WIDTH)
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(16)
        col_layout.addLayout(header)
        col_layout.addSpacing(4)
        col_layout.addWidget(item_card)
        col_layout.addWidget(owner_card)
        col_layout.addWidget(photos_card)
        col_layout.addStretch(1)

        body = QWidget()
        body.setObjectName("scrollBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(32, 28, 32, 28)
        body_layout.addStretch(0)
        body_layout.addWidget(column, 1)
        body_layout.addStretch(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        return scroll

    # -- public -------------------------------------------------------------

    def clear(self) -> None:
        """Back to the empty state."""
        self._lot = None
        self._auction_no = None
        self._photos = []
        self._dirty = False
        self.stack.setCurrentIndex(0)

    def load(self, lot: Lot, auction_no: int) -> None:
        """Lot -> widgets."""
        self._loading = True
        self._lot = lot
        self._auction_no = auction_no
        self._photos = list(lot.photos)
        self.heading.setText(strings.LOT_HEADING.format(n=lot.lot_number))
        self.subtitle.setText(strings.LOT_SUBTITLE.format(n=auction_no))
        self.serial.setText(lot.serial)
        self._fill_conditions(lot.condition)
        self._applied_condition = lot.condition
        self.title.setText(lot.title)
        self.desc.setPlainText(lot.desc)
        self.owner.setText(lot.owner)
        self.book_no.setText(lot.book_no)
        self.year.setText("" if lot.year is None else str(lot.year))
        self.make.setText(lot.make)
        self.model.setText(lot.model)
        self._applied_title_fields = (lot.make, lot.model, lot.serial)
        self._looked_up = lot.serial
        self.lookup_hint.clear()
        self._update_lookup_row()
        self._update_title_count()
        self._refresh_photos()
        self.stack.setCurrentIndex(1)
        self._loading = False
        self._dirty = False
        self.set_save_state("saved", strings.ALL_SAVED)
        # May add the condition text to an older lot; that counts as an edit.
        self._apply_condition()

    def current_lot(self) -> Lot | None:
        """The lot as currently shown in the fields, or None if none is open."""
        return self.collect() if self._lot is not None else None

    def set_research_checked(self, checked: bool) -> None:
        self.research_btn.blockSignals(True)
        self.research_btn.setChecked(checked)
        self.research_btn.blockSignals(False)

    def is_dirty(self) -> bool:
        return self._dirty and self._lot is not None

    def mark_saved(self) -> None:
        self._dirty = False
        self.set_save_state("saved", strings.ALL_SAVED)

    def set_photos(self, photos: list[Path]) -> None:
        """Swap in the saved photo paths without counting it as an edit."""
        self._photos = list(photos)
        self._refresh_photos()

    def set_save_state(self, state: str, text: str) -> None:
        """state is "saved", "pending" or "error" (styled in styles.qss)."""
        self.save_state.setText(text)
        self.save_state.setProperty("state", state)
        self.save_state.style().unpolish(self.save_state)
        self.save_state.style().polish(self.save_state)

    def show_lookup(self, results: list[LookupResult] | None) -> None:
        """Show a serial lookup result; fill year (and title if empty) on one match.

        None means there's no serial table to check, so only the link shows.
        """
        if results is None:
            text = ""
        elif len(results) == 1:
            hit = results[0]
            self.year.setText(str(hit.year))
            if not self.make.text().strip() and hit.maker:
                self.make.setText(hit.maker)
            if not self.model.text().strip() and hit.model:
                self.model.setText(hit.model)
            self._apply_title_fields()
            text = strings.LOOKUP_FOUND.format(title=hit.title, year=hit.year)
        elif results:
            matches = ", ".join(f"{r.title} ({r.year})" for r in results)
            text = strings.LOOKUP_SEVERAL.format(matches=matches)
        else:
            text = strings.LOOKUP_NONE
        self.lookup_hint.setText(text)
        self._update_lookup_row()

    def set_conditions(self, options: list[ConditionOption]) -> None:
        """The condition choices (from Settings). An open lot keeps its
        condition and picks up any new wording for it."""
        self._conditions = list(options)
        self._fill_conditions(self._condition() if self._lot else "")
        if self._lot is not None:
            self._apply_condition()

    def set_serial_links(self, links: list[SerialLink]) -> None:
        """The links shown under Serial # (from Settings)."""
        while self._links_layout.count():
            widget = self._links_layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        for link in links:
            button = QPushButton(strings.SERIAL_LINK.format(name=link.name))
            button.setObjectName("link")
            button.setToolTip(strings.SERIAL_LINK_TIP.format(name=link.name))
            button.clicked.connect(lambda _=False, link=link: self._open_link(link))
            self._links_layout.addWidget(button)
        self._has_links = bool(links)
        self._update_lookup_row()

    def collect(self) -> Lot:
        """Widgets -> Lot."""
        assert self._lot is not None
        year = self.year.text().strip()
        return Lot(
            lot_number=self._lot.lot_number,
            serial=self.serial.text().strip(),
            condition=self._condition(),
            title=self.title.text().strip(),
            desc=self.desc.toPlainText().strip(),
            owner=self.owner.text().strip(),
            book_no=self.book_no.text().strip(),
            year=int(year) if year.isdigit() else None,
            photos=list(self._photos),
            make=self.make.text().strip(),
            model=self.model.text().strip(),
        )

    # -- internals ----------------------------------------------------------

    def _condition(self) -> str:
        return self.condition.currentText().strip()

    def _known_conditions(self) -> list[str]:
        """Names whose suffix/sentence may be in the text and can be replaced."""
        return [o.name for o in self._conditions] + [self._applied_condition]

    def _fill_conditions(self, current: str) -> None:
        """Put the configured conditions in the dropdown and select `current`.
        A condition no longer in Settings is kept as an extra choice."""
        names = [o.name for o in self._conditions]
        self.condition.blockSignals(True)
        self.condition.clear()
        self.condition.addItems(names)
        match = next((n for n in names if n.lower() == current.lower()), None)
        if current and match is None:
            self.condition.addItem(current)
            match = current
        self.condition.setCurrentIndex(self.condition.findText(match) if match else -1)
        self.condition.blockSignals(False)

    def _mark_dirty(self) -> None:
        if self._loading or self._lot is None:
            return
        self._dirty = True
        self.set_save_state("pending", strings.SAVING)
        self.changed.emit()

    def _update_title_count(self) -> None:
        """e.g. "87/100", red when the condition suffix would trim the title."""
        n = untrimmed_title_length(
            self.title.text(), self._condition(), self._known_conditions()
        )
        self.title_count.setText(f"{min(n, TITLE_MAX_LENGTH)}/{TITLE_MAX_LENGTH}")
        over = n > TITLE_MAX_LENGTH
        self.title_count.setToolTip(strings.TITLE_TRIMMED if over else "")
        if self.title_count.property("over") != over:
            self.title_count.setProperty("over", over)
            self.title_count.style().unpolish(self.title_count)
            self.title_count.style().polish(self.title_count)

    def _apply_condition(self) -> None:
        """Keep the title suffix and description sentence in sync with condition.

        Runs when a condition is picked, when the title is finished, and on load,
        so the text shows up immediately rather than on save.
        """
        condition = self._condition()
        if not condition:
            # Nothing picked yet (e.g. an imported lot): leave the text alone.
            self._applied_condition = ""
            return
        known = self._known_conditions()
        title = condition_title(self.title.text(), condition, known)
        if title != self.title.text():
            self.title.setText(title)
        option = find_option(self._conditions, condition)
        # A condition that's been removed from Settings has no sentence to
        # write, so the description is left as it is.
        if option is not None or not condition:
            note = option.note if option else ""
            desc = condition_desc(self.desc.toPlainText(), condition, note, known)
            if desc != self.desc.toPlainText():
                self.desc.setPlainText(desc)
        self._applied_condition = condition

    def _apply_title_fields(self) -> None:
        """Start the title with make, model and serial (the condition ends
        it), and put make and model at the top of the description, replacing
        what was put there before. Runs when one of those fields is edited."""
        fields = (
            self.make.text().strip(),
            self.model.text().strip(),
            self.serial.text().strip(),
        )
        if fields == self._applied_title_fields:
            return
        old = self._applied_title_fields
        self._applied_title_fields = fields
        make, model, _serial = fields
        title = prefixed_title(self.title.text(), title_prefix(*old), *fields)
        if title != self.title.text():
            self.title.setText(title)
        if (make, model) != old[:2]:
            desc = make_model_desc(self.desc.toPlainText(), make, model)
            if desc != self.desc.toPlainText():
                self.desc.setPlainText(desc)
        self._apply_condition()  # re-check the title length with its suffix

    def _on_serial_done(self) -> None:
        self._apply_title_fields()
        serial = self.serial.text().strip()
        if serial == self._looked_up:
            return
        self._looked_up = serial
        self.lookup_hint.clear()
        self._update_lookup_row()
        if serial:
            self.serial_lookup_requested.emit(serial)

    def _update_lookup_row(self) -> None:
        has_serial = bool(self.serial.text().strip())
        has_content = self._has_links or bool(self.lookup_hint.text())
        self.lookup_row.setVisible(has_serial and has_content)

    def _open_link(self, link: SerialLink) -> None:
        url = build_url(
            link.url, self.serial.text(), self.title.text(), self.make.text()
        )
        QDesktopServices.openUrl(QUrl(url))

    def _pick_photos(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            strings.PICK_PHOTOS,
            "",
            "Images (*.jpg *.jpeg *.png *.heic *.webp)",
        )
        if files:
            self._photos.extend(Path(f) for f in files)
            self._refresh_photos()
            self._mark_dirty()

    def _remove_selected_photo(self) -> None:
        rows = sorted(
            (self.photo_list.row(i) for i in self.photo_list.selectedItems()),
            reverse=True,
        )
        for row in rows:
            del self._photos[row]
        if rows:
            self._refresh_photos()
            self._mark_dirty()

    def _refresh_photos(self) -> None:
        self.photo_list.clear()
        for path in self._photos:
            item = QListWidgetItem(QIcon(str(path)), path.stem)
            item.setToolTip(str(path))
            self.photo_list.addItem(item)
        self.photo_list.setVisible(bool(self._photos))
        self.photos_hint.setText(
            strings.PHOTOS_HINT if self._photos else strings.NO_PHOTOS
        )
