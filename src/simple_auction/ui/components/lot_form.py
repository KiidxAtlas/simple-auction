import math
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QIntValidator,
    QKeySequence,
    QPalette,
    QShortcut,
)
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from simple_auction.constants import TITLE_MAX_LENGTH
from simple_auction.models import Lot
from simple_auction.services.conditions import DEFAULT_CONDITIONS, ConditionOption
from simple_auction.services.listing import (
    condition_desc,
    find_option,
)
from simple_auction.services.lookup import LookupResult
from simple_auction.services.serial_links import SerialLink, build_url
from simple_auction.services.title_layout import (
    CA_LEGALITY,
    CUSTOM_PREFIX,
    DEFAULT_DESC_FIELDS,
    DEFAULT_FIELDS,
    GUN_TYPES,
    CustomField,
    desc_lines,
    is_custom_key,
    labels,
    prefixes,
    update_desc,
    update_title,
    validate,
    validate_desc,
)
from simple_auction.ui import strings, theme
from simple_auction.ui.flow_layout import FlowLayout

PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".heic", ".webp")
PHOTO_GRID = QSize(theme.THUMB_SIZE + 16, theme.THUMB_SIZE + 30)
PHOTO_MAX_ROWS = 3


def _field(
    label: str,
    widget: QWidget,
    aside: QWidget | None = None,
    *,
    buddy: QWidget | None = None,
    auto_tip: str = "",
) -> QWidget:
    """A small label stacked above its input, with an optional note at the right.

    `auto_tip` adds an "Auto-filled" badge explaining what the app writes there.
    """
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    text = QLabel(label)
    text.setObjectName("fieldLabel")
    text.setBuddy(buddy or widget)
    label_row = QHBoxLayout()
    label_row.setSpacing(8)
    label_row.addWidget(text)
    if auto_tip:
        badge = QLabel(strings.AUTO_BADGE)
        badge.setObjectName("autoBadge")
        badge.setToolTip(auto_tip)
        label_row.addWidget(badge)
    label_row.addStretch(1)
    if aside is not None:
        label_row.addWidget(aside)
    layout.addLayout(label_row)
    # Any extra height goes to the input (e.g. a growing description).
    layout.addWidget(widget, 1)
    return box


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 16, 18, 18)
    layout.setSpacing(12)
    heading = QLabel(title)
    heading.setObjectName("cardTitle")
    layout.addWidget(heading)
    return card, layout


class _FieldGrid(QWidget):
    """Fields in as many equal columns as fit (up to `max_columns`), so short
    fields sit side by side instead of each taking a row, and inputs are
    never squeezed below a readable width."""

    def __init__(self, items: list[tuple[QWidget, bool]], max_columns: int = 2) -> None:
        """items: (widget, full_width) in reading order."""
        super().__init__()
        self._items = items
        self._max_columns = max_columns
        self._columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(theme.SPACING + 2)
        self.grid.setVerticalSpacing(12)
        # Our minimum is the one-column width (see minimumSizeHint), so the
        # grid can be narrowed below several columns' width and then reflow.
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._place(max_columns)

    def minimumSizeHint(self) -> QSize:
        width = max(
            (
                w.minimumSizeHint().width()
                for w, _full in self._items
                if not w.isHidden()
            ),
            default=0,
        )
        return QSize(width, self.grid.minimumSize().height())

    def _place(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        for widget, _full in self._items:
            self.grid.removeWidget(widget)
        row = col = 0
        for widget, full in self._items:
            if full or columns == 1:
                if col:
                    row, col = row + 1, 0
                self.grid.addWidget(
                    widget, row, 0, 1, columns, Qt.AlignmentFlag.AlignTop
                )
                row += 1
            else:
                self.grid.addWidget(widget, row, col, Qt.AlignmentFlag.AlignTop)
                col += 1
                if col == columns:
                    row, col = row + 1, 0
        for c in range(self._max_columns):
            self.grid.setColumnStretch(c, int(c < columns))
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        spacing = self.grid.horizontalSpacing()
        fit = (self.width() + spacing) // (theme.FIELD_MIN_WIDTH + spacing)
        self._place(max(1, min(self._max_columns, fit)))


def _icon_button(name: str, tip: str) -> QPushButton:
    button = QPushButton()
    button.setObjectName("iconButton")
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    theme.set_icon(button, name)
    return button


class _BlankAsNone(QStyledItemDelegate):
    """Shows an empty dropdown choice as a muted "None" in the open list; the
    choice itself (and so the field once picked) stays empty."""

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        if not option.text:
            option.text = strings.NONE_CHOICE
            option.palette.setColor(
                QPalette.ColorRole.Text, QColor(theme.colors().muted)
            )


class _PhotoDrop(QFrame):
    """The photos area: accepts image files dragged from Explorer/Finder."""

    dropped = Signal(list)  # list[Path]

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("photoDrop")
        self.setAcceptDrops(True)

    @staticmethod
    def _images(event) -> list[Path]:
        return [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile().lower().endswith(PHOTO_SUFFIXES)
        ]

    def dragEnterEvent(self, event) -> None:
        if self.isEnabled() and self._images(event):
            event.acceptProposedAction()
            theme.repolish(self, state="dragging")
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        theme.repolish(self, state=None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        theme.repolish(self, state=None)
        if images := self._images(event):
            event.acceptProposedAction()
            self.dropped.emit(images)
        else:
            event.ignore()


class LotForm(QWidget):
    changed = Signal()  # the user edited something; autosave soon
    save_now = Signal()  # Cmd/Ctrl+S: save without waiting
    export_requested = Signal()
    new_auction_requested = Signal()
    new_lot_requested = Signal()  # add a lot to the open lot's auction
    import_requested = Signal()
    delete_requested = Signal()  # delete the open lot
    step_requested = Signal(int)  # -1 previous lot, +1 next lot
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
        self._link_buttons: list[tuple[QPushButton, SerialLink]] = []
        self._title_fields = list(DEFAULT_FIELDS)
        self._applied_title_lot = Lot(0)
        # Condition choices from Settings, and the condition whose text is
        # currently in the title/description (so changing it replaces that).
        self._conditions: list[ConditionOption] = list(DEFAULT_CONDITIONS)
        self._applied_condition = ""
        # Custom fields from Settings, their line edits by field id, and the
        # text written before each one's value in the title (now and as last
        # applied to the title, so a changed prefix replaces the old one).
        self._custom_fields: list[CustomField] = []
        self._custom_inputs: dict[str, QLineEdit] = {}
        self._prefixes: dict[str, str] = {}
        self._applied_prefixes: dict[str, str] = {}
        # Fields written as "Label: value" lines at the top of the description,
        # and the lines/labels last written (so changes replace them).
        self._desc_fields = list(DEFAULT_DESC_FIELDS)
        self._applied_desc_lines: list[str] | None = []
        self._applied_desc_labels: list[str] = []

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty())
        self.stack.addWidget(self._build_editor())
        # Below this the editor would have to squeeze its fields; the
        # window's panels give way instead.
        self.setMinimumWidth(theme.EDITOR_MIN_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        for field in (
            self.serial,
            self.year,
            self.make,
            self.model,
            self.caliber,
            self.barrel_length,
            self.title,
            self.owner,
            self.book_no,
        ):
            field.textChanged.connect(self._mark_dirty)
        self.gun_type.currentTextChanged.connect(self._mark_dirty)
        self.desc.textChanged.connect(self._mark_dirty)
        self.condition.currentIndexChanged.connect(self._mark_dirty)
        self.ca_legality.currentIndexChanged.connect(self._mark_dirty)
        self.c_and_r.toggled.connect(self._mark_dirty)
        # The counter also reflects condition, CA legality and C&R in the title.
        self.ca_legality.currentIndexChanged.connect(self._update_title_count)
        self.c_and_r.toggled.connect(self._update_title_count)

        save = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        save.activated.connect(self.save_now)
        for keys, step in (("Ctrl+PgUp", -1), ("Ctrl+PgDown", 1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda step=step: self._step(step))
        new_lot = QShortcut(QKeySequence(QKeySequence.StandardKey.New), self)
        new_lot.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        new_lot.activated.connect(self._new_lot)

    # -- building -----------------------------------------------------------

    def _build_empty(self) -> QWidget:
        page = QWidget()
        page.setObjectName("content")
        badge = QFrame()
        badge.setObjectName("emptyIcon")
        badge.setFixedSize(56, 56)
        badge_icon = QLabel()
        badge_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.set_icon(badge_icon, "book", "accent", QSize(26, 26))
        QVBoxLayout(badge).addWidget(badge_icon)
        title = QLabel(strings.EMPTY_TITLE)
        title.setObjectName("emptyTitle")
        body = QLabel(strings.EMPTY_BODY)
        body.setObjectName("hint")
        create = QPushButton(strings.CREATE_NEW)
        create.setObjectName("primary")
        theme.set_icon(create, "plus", "accent_text")
        create.clicked.connect(self.new_auction_requested)
        import_btn = QPushButton(strings.EMPTY_IMPORT)
        theme.set_icon(import_btn, "import")
        import_btn.clicked.connect(self.import_requested)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        buttons.addWidget(create)
        buttons.addWidget(import_btn)
        buttons.addStretch(1)

        layout = QVBoxLayout(page)
        layout.addStretch(1)
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(12)
        for w in (title, body):
            layout.addWidget(w, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(14)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

    def _build_header(self) -> QBoxLayout:
        """Breadcrumb, save state and lot title; lot actions at the right
        (or on their own row below the title when the editor is narrow)."""
        self.subtitle = QLabel()
        self.subtitle.setObjectName("breadcrumb")
        self.save_state = QLabel()
        self.save_state.setObjectName("saveState")
        # Long save errors wrap instead of widening the header.
        self.save_state.setWordWrap(True)
        self._crumbs = QHBoxLayout()
        self._crumbs.setSpacing(12)
        self._crumbs.addWidget(self.subtitle)
        self._crumbs.addWidget(self.save_state, 1)
        self.heading = QLabel()
        self.heading.setObjectName("lotTitle")
        self.heading.setWordWrap(True)
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addLayout(self._crumbs)
        titles.addWidget(self.heading)

        self.prev_btn = _icon_button("prev", strings.PREV_LOT_TIP)
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.next_btn = _icon_button("next", strings.NEXT_LOT_TIP)
        self.next_btn.clicked.connect(lambda: self._step(1))
        self.new_lot_btn = QPushButton(strings.NEW_LOT)
        self.new_lot_btn.setToolTip(strings.NEW_LOT_TIP)
        theme.set_icon(self.new_lot_btn, "plus")
        self.new_lot_btn.clicked.connect(self._new_lot)
        self.research_btn = QPushButton(strings.RESEARCH)
        self.research_btn.setCheckable(True)
        self.research_btn.setToolTip(strings.RESEARCH_TIP)
        theme.set_icon(self.research_btn, "sparkle")
        self.research_btn.toggled.connect(self.research_toggled)
        self.more_btn = _icon_button("more", strings.MORE_TIP)
        more = QMenu(self.more_btn)
        self.export_action = more.addAction(strings.EXPORT_AUCTION_N.format(n=""))
        self.export_action.setToolTip(strings.EXPORT_TIP)
        theme.set_icon(self.export_action, "export")
        self.export_action.triggered.connect(self.export_requested)
        more.addSeparator()
        delete = more.addAction(strings.DELETE_LOT)
        theme.set_icon(delete, "trash")
        delete.triggered.connect(self.delete_requested)
        self.more_btn.setMenu(more)

        self.header_actions = QWidget()
        actions = QHBoxLayout(self.header_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.prev_btn)
        actions.addWidget(self.next_btn)
        actions.addSpacing(4)
        for widget in (self.new_lot_btn, self.research_btn, self.more_btn):
            actions.addWidget(widget)

        self.header = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.header.setSpacing(theme.SPACING)
        self.header.addLayout(titles, 1)
        self.header.addWidget(self.header_actions, 0, Qt.AlignmentFlag.AlignBottom)
        return self.header

    def _build_editor(self) -> QWidget:
        header = self._build_header()

        # Identification: what the item is.
        self.make = QLineEdit()
        self.make.setPlaceholderText(strings.MAKE_PLACEHOLDER)
        self.make.editingFinished.connect(self._apply_title_fields)
        self.model = QLineEdit()
        self.model.setPlaceholderText(strings.MODEL_PLACEHOLDER)
        self.model.editingFinished.connect(self._apply_title_fields)
        self.serial = QLineEdit()
        self.serial.setPlaceholderText(strings.SERIAL_PLACEHOLDER)
        self.serial.editingFinished.connect(self._on_serial_done)
        self.serial.textChanged.connect(self._update_lookup_row)
        self.year = QLineEdit()
        self.year.setPlaceholderText(strings.YEAR_PLACEHOLDER)
        self.year.setValidator(QIntValidator(0, 9999, self.year))
        self.year.setMaxLength(4)
        self.year.editingFinished.connect(self._apply_title_fields)
        # The serial lookup sites sit right under the serial they look up, so
        # the serial field keeps its full width however many sites there are.
        serial_box = QWidget()
        serial_layout = QVBoxLayout(serial_box)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        serial_layout.setSpacing(6)
        serial_layout.addWidget(self.serial)
        self.lookup_links = QWidget()
        self._links_layout = FlowLayout(self.lookup_links)
        look_up = QLabel(strings.LOOK_UP_ON)
        look_up.setObjectName("fieldHint")
        self._links_layout.addWidget(look_up)
        self.lookup_links.hide()
        serial_layout.addWidget(self.lookup_links)
        self.lookup_hint = QLabel()
        self.lookup_hint.setObjectName("fieldHint")
        self.lookup_hint.setWordWrap(True)
        self.lookup_hint.hide()

        # Caliber and type, e.g. "7.62x39" and "Rifle" in
        # "Arsenal SAM7SF 7.62x39 Rifle SN: ...".
        self.caliber = QLineEdit()
        self.caliber.setPlaceholderText(strings.CALIBER_PLACEHOLDER)
        self.caliber.editingFinished.connect(self._apply_title_fields)
        self.gun_type = QComboBox()
        self.gun_type.setEditable(True)
        self.gun_type.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.gun_type.addItems(["", *GUN_TYPES])
        # The blank choice reads "None" in the list but still clears the field.
        self.gun_type.setItemDelegate(_BlankAsNone(self.gun_type))
        self.gun_type.lineEdit().setPlaceholderText(strings.GUN_TYPE_PLACEHOLDER)
        self.gun_type.setAccessibleName(strings.GUN_TYPE)
        self.gun_type.activated.connect(self._apply_title_fields)
        self.gun_type.lineEdit().editingFinished.connect(self._apply_title_fields)

        # Barrel length sits with the other short facts about the gun.
        self.barrel_length = QLineEdit()
        self.barrel_length.setPlaceholderText(strings.BARREL_PLACEHOLDER)
        self.barrel_length.editingFinished.connect(self._apply_title_fields)

        # One card for what the item is, three short fields to a row when
        # there's room, so the listing below needs no scrolling to reach.
        id_card, id_layout = _card(strings.IDENTIFICATION_CARD)
        id_layout.addWidget(
            _FieldGrid(
                [
                    (_field(strings.MAKE, self.make), False),
                    (_field(strings.MODEL, self.model), False),
                    (_field(strings.CALIBER, self.caliber), False),
                    (_field(strings.GUN_TYPE, self.gun_type), False),
                    (_field(strings.BARREL_LENGTH, self.barrel_length), False),
                    (_field(strings.YEAR, self.year), False),
                    (_field(strings.SERIAL, serial_box, buddy=self.serial), True),
                    (self.lookup_hint, True),
                ],
                max_columns=3,
            )
        )

        # Fields added in Settings → Listing fields (see set_custom_fields).
        self.custom_card, self._custom_layout = _card(strings.CUSTOM_FIELDS_CARD)
        self._custom_grid: _FieldGrid | None = None
        self.custom_card.hide()

        # Listing: what bidders read. Condition, CA legality and C&R all
        # write into the title, so they sit together right above it.
        self.condition = QComboBox()
        self.condition.setPlaceholderText(strings.PICK_CONDITION)
        self.condition.activated.connect(self._apply_condition)
        self.ca_legality = QComboBox()
        self.ca_legality.addItems(CA_LEGALITY)
        self.ca_legality.activated.connect(self._apply_title_fields)
        self.c_and_r = QCheckBox(strings.C_AND_R_CHECK)
        self.c_and_r.setObjectName("fieldCheck")
        self.c_and_r.setToolTip(strings.C_AND_R_TIP)
        # clicked, not toggled: only the user's choice rewrites the title.
        self.c_and_r.clicked.connect(self._apply_title_fields)
        self.title = QLineEdit()
        self.title.setPlaceholderText(strings.TITLE_PLACEHOLDER)
        self.title.setMaxLength(TITLE_MAX_LENGTH)
        self.title.editingFinished.connect(self._apply_condition)
        self.title.textChanged.connect(self._update_heading)
        self.title_count = QLabel()
        self.title_count.setObjectName("charCount")
        self.title.textChanged.connect(self._update_title_count)
        self.condition.currentIndexChanged.connect(self._update_title_count)
        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText(strings.DESC_PLACEHOLDER)
        self.desc.setMinimumHeight(140)
        # Height comes from the room left in the window (from 140px up), not
        # from the text box's own preferred size, so it never forces a scroll.
        self.desc.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        self.desc.setTabChangesFocus(True)
        listing_card, listing_layout = _card(strings.LISTING_CARD)
        listing_layout.addWidget(
            _FieldGrid(
                [
                    (_field(strings.CONDITION, self.condition), False),
                    (_field(strings.CA_LEGALITY, self.ca_legality), False),
                    (_field(strings.C_AND_R, self.c_and_r), False),
                    (
                        _field(
                            strings.TITLE,
                            self.title,
                            self.title_count,
                            auto_tip=strings.TITLE_AUTO_TIP,
                        ),
                        True,
                    ),
                ],
                max_columns=3,
            )
        )
        # The description takes whatever height is left, so a tall window
        # shows more of it rather than empty space below the card.
        listing_layout.addWidget(
            _field(strings.DESC, self.desc, auto_tip=strings.DESC_AUTO_TIP), 1
        )

        # Photos: a drop area with thumbnails.
        photos_card, photos_layout = _card(strings.PHOTOS_CARD)
        add_photos = QPushButton(strings.ADD_PHOTOS)
        theme.set_icon(add_photos, "plus")
        add_photos.clicked.connect(self._pick_photos)
        photos_title_row = photos_layout.itemAt(0).widget()
        photos_layout.removeWidget(photos_title_row)
        photo_bar = QHBoxLayout()
        photo_bar.addWidget(photos_title_row, 1)
        photo_bar.addWidget(add_photos)
        photos_layout.insertLayout(0, photo_bar)
        self.photo_drop = _PhotoDrop()
        self.photo_drop.dropped.connect(self._add_photos)
        drop_layout = QVBoxLayout(self.photo_drop)
        drop_layout.setContentsMargins(8, 8, 8, 8)
        self.photo_empty = QWidget()
        empty_layout = QVBoxLayout(self.photo_empty)
        empty_layout.setContentsMargins(0, 18, 0, 18)
        empty_layout.setSpacing(6)
        empty_icon = QLabel()
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.set_icon(empty_icon, "image", "muted", QSize(28, 28))
        empty_layout.addWidget(empty_icon)
        self.photos_hint = QLabel()
        self.photos_hint.setObjectName("hint")
        self.photos_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photos_hint.setWordWrap(True)
        empty_layout.addWidget(self.photos_hint)
        formats = QLabel(strings.PHOTOS_DROP_HINT)
        formats.setObjectName("fieldHint")
        formats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(formats)
        drop_layout.addWidget(self.photo_empty)
        self.photo_list = QListWidget()
        self.photo_list.setObjectName("photos")
        self.photo_list.setViewMode(QListView.ViewMode.IconMode)
        self.photo_list.setFlow(QListView.Flow.LeftToRight)
        self.photo_list.setWrapping(True)
        self.photo_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.photo_list.setMovement(QListView.Movement.Static)
        self.photo_list.setGridSize(PHOTO_GRID)
        self.photo_list.setIconSize(QSize(theme.THUMB_SIZE, theme.THUMB_SIZE))
        self.photo_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.photo_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            remove = QShortcut(QKeySequence(key), self.photo_list)
            remove.setContext(Qt.ShortcutContext.WidgetShortcut)
            remove.activated.connect(self._remove_selected_photo)
        drop_layout.addWidget(self.photo_list)
        self.photos_more_hint = QLabel(strings.PHOTOS_HINT)
        self.photos_more_hint.setObjectName("fieldHint")
        self.photos_more_hint.setWordWrap(True)
        photos_layout.addWidget(self.photo_drop)
        photos_layout.addWidget(self.photos_more_hint)

        # Consignment.
        self.owner = QLineEdit()
        self.owner.setPlaceholderText(strings.OWNER_PLACEHOLDER)
        self.book_no = QLineEdit()
        self.book_no.setPlaceholderText(strings.BOOK_PLACEHOLDER)
        self.owner.editingFinished.connect(self._apply_title_fields)
        self.book_no.editingFinished.connect(self._apply_title_fields)
        owner_card, owner_layout = _card(strings.CONSIGNMENT_CARD)
        owner_layout.addWidget(
            _FieldGrid(
                [
                    (_field(strings.OWNER, self.owner), False),
                    (_field(strings.BOOK_NO, self.book_no), False),
                ]
            )
        )

        # Details on the left, photos and consignment on the right; stacked
        # in one column when the window (or the research panel) leaves less room.
        details = QVBoxLayout()
        details.setSpacing(14)
        details.addWidget(id_card)
        details.addWidget(self.custom_card)
        # The listing card stretches to the bottom of the window.
        details.addWidget(listing_card, 1)
        aside = QVBoxLayout()
        aside.setSpacing(14)
        aside.addWidget(photos_card)
        aside.addWidget(owner_card)
        aside.addStretch(1)
        self.columns = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.columns.setSpacing(14)
        self.columns.addLayout(details, 3)
        self.columns.addLayout(aside, 2)

        column = QWidget()
        column.setMaximumWidth(theme.CONTENT_MAX_WIDTH)
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(16)
        col_layout.addLayout(header)
        col_layout.addLayout(self.columns, 1)

        body = QWidget()
        body.setObjectName("scrollBody")
        self._body_layout = QHBoxLayout(body)
        self._body_layout.setContentsMargins(24, 18, 24, 20)
        self._body_layout.addWidget(column, 1)

        # Content reflows to fit; a horizontal scrollbar is only a last resort
        # so nothing is ever cut off at the right edge.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        return scroll

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_layout()

    def _update_layout(self) -> None:
        """Reflow the editor for its current width."""
        width = self.width()
        self.columns.setDirection(
            QBoxLayout.Direction.LeftToRight
            if width >= theme.TWO_COLUMN_WIDTH
            else QBoxLayout.Direction.TopToBottom
        )
        # Small editor: less padding around the cards.
        side = 14 if width < 600 else 24
        self._body_layout.setContentsMargins(side, 16 if side == 14 else 18, side, 20)
        # The lot actions get their own row under the title once the
        # breadcrumb and the actions no longer fit side by side.
        need = (
            max(self.subtitle.sizeHint().width() + 160, 300)
            + theme.SPACING
            + self.header_actions.sizeHint().width()
            + 2 * side
        )
        narrow = width < need
        self.header.setDirection(
            QBoxLayout.Direction.TopToBottom
            if narrow
            else QBoxLayout.Direction.LeftToRight
        )
        self.header.setAlignment(
            self.header_actions,
            Qt.AlignmentFlag.AlignLeft if narrow else Qt.AlignmentFlag.AlignBottom,
        )
        self._fit_photos()

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
        self.subtitle.setText(
            strings.LOT_BREADCRUMB.format(auction=auction_no, lot=lot.lot_number)
        )
        self.export_action.setText(strings.EXPORT_AUCTION_N.format(n=auction_no))
        self._update_layout()
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
        self.caliber.setText(lot.caliber)
        self.gun_type.setCurrentText(lot.gun_type)
        self.barrel_length.setText(lot.barrel_length)
        # Show long values from their start, not scrolled to the end.
        for field in (
            self.serial,
            self.title,
            self.owner,
            self.book_no,
            self.make,
            self.model,
            self.caliber,
            self.gun_type.lineEdit(),
            self.barrel_length,
        ):
            field.setCursorPosition(0)
        self.ca_legality.setCurrentText(lot.ca_legality)
        self.c_and_r.setChecked(lot.c_and_r)
        for key, edit in self._custom_inputs.items():
            edit.setText(lot.custom.get(key, ""))
            edit.setCursorPosition(0)
        self._applied_prefixes = dict(self._prefixes)
        self._applied_desc_lines = desc_lines(
            lot, self._desc_fields, labels(self._custom_fields)
        )
        self._applied_desc_labels = [
            labels(self._custom_fields)[k] for k in self._desc_fields
        ]
        # None (a lot from before title layouts) is kept so the title can be
        # recognised as written in the old default layout.
        self._applied_title_lot = lot
        self._looked_up = lot.serial
        self.lookup_hint.clear()
        self._update_lookup_row()
        self._update_title_count()
        self._refresh_photos()
        self._update_heading()
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

    def set_navigation(self, has_previous: bool, has_next: bool) -> None:
        """Enable the previous/next lot buttons."""
        self.prev_btn.setEnabled(has_previous)
        self.next_btn.setEnabled(has_next)

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

    def set_title_fields(self, fields: list[str]) -> None:
        fields = validate(fields)
        if self._lot is not None:
            current = self.collect()
            self.title.setText(
                update_title(
                    self.title.text(),
                    self._applied_title_lot,
                    self._title_fields,
                    current,
                    fields,
                    self._prefixes,
                    self._applied_prefixes,
                )
            )
            self._applied_title_lot = replace(current, title_fields=list(fields))
            self._applied_prefixes = dict(self._prefixes)
        self._title_fields = fields
        self._update_title_count()

    def set_serial_links(self, links: list[SerialLink]) -> None:
        """The lookup sites shown under Serial # (from Settings)."""
        for button, _link in self._link_buttons:
            self._links_layout.removeWidget(button)
            button.deleteLater()
        self._link_buttons = []
        for link in links:
            button = QPushButton(strings.SERIAL_LINK.format(name=link.name))
            button.setObjectName("lookupLink")
            theme.set_icon(button, "external", size=QSize(13, 13))
            button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # icon after
            button.clicked.connect(lambda _=False, link=link: self._open_link(link))
            self._links_layout.addWidget(button)
            self._link_buttons.append((button, link))
        self.lookup_links.setVisible(bool(links))
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
            barrel_length=self.barrel_length.text().strip(),
            caliber=self.caliber.text().strip(),
            gun_type=self.gun_type.currentText().strip(),
            ca_legality=self.ca_legality.currentText(),
            c_and_r=self.c_and_r.isChecked(),
            title_fields=list(self._title_fields),
            custom=self._collect_custom(),
        )

    def set_custom_fields(self, fields: list[CustomField]) -> None:
        """The extra fields defined in Settings → Listing fields. An open lot
        keeps the values it has; call set_title_fields afterwards."""
        values = {}
        if self._lot is not None:
            values = self._collect_custom()
            # Typed values of removed fields stay with the lot.
            self._lot = replace(self._lot, custom=values)
        self._custom_fields = list(fields)
        self._prefixes = prefixes(fields)
        self._desc_fields = [
            k
            for k in self._desc_fields
            if not is_custom_key(k) or k in {f.key for f in fields}
        ]
        if self._custom_grid is not None:
            self._custom_layout.removeWidget(self._custom_grid)
            self._custom_grid.deleteLater()
            self._custom_grid = None
        self._custom_inputs = {}
        items = []
        for custom in fields:
            edit = QLineEdit(values.get(custom.id, ""))
            edit.setAccessibleName(custom.label)
            edit.textChanged.connect(self._mark_dirty)
            edit.editingFinished.connect(self._apply_title_fields)
            self._custom_inputs[custom.id] = edit
            items.append((_field(custom.label, edit), False))
        if items:
            self._custom_grid = _FieldGrid(items)
            self._custom_layout.addWidget(self._custom_grid)
        self.custom_card.setVisible(bool(items))

    def _collect_custom(self) -> dict[str, str]:
        """Values typed in the custom fields, plus any the lot has for
        fields no longer defined (so removing a field loses nothing)."""
        assert self._lot is not None
        values = {
            key: value
            for key, value in self._lot.custom.items()
            if key not in self._custom_inputs
        }
        for key, edit in self._custom_inputs.items():
            if text := edit.text().strip():
                values[key] = text
        return values

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
        """e.g. "87/100", red when the generated parts would trim the title."""
        n = len(self.title.text())
        if self._lot is not None and not self._loading:
            current = self.collect()
            n = len(
                update_title(
                    self.title.text(),
                    current,
                    self._title_fields,
                    current,
                    self._title_fields,
                    self._prefixes,
                    max_length=10_000,
                )
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
        if self._lot is None or self._loading:
            return
        condition = self._condition()
        known = self._known_conditions()
        current = self.collect()
        title = update_title(
            self.title.text(),
            self._applied_title_lot,
            self._title_fields,
            current,
            self._title_fields,
            self._prefixes,
            self._applied_prefixes,
        )
        self._applied_title_lot = current
        self._applied_prefixes = dict(self._prefixes)
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
        """Synchronize the title fields and the description's field lines."""
        if self._lot is None or self._loading:
            return
        self._apply_desc_fields(self.collect())
        self._apply_condition()

    def _apply_desc_fields(self, current: Lot) -> None:
        """Rewrite the "Label: value" lines at the top of the description when
        the chosen fields, their labels or their values changed."""
        label_for = labels(self._custom_fields)
        lines = desc_lines(current, self._desc_fields, label_for)
        if lines == self._applied_desc_lines:
            return
        # Remove lines written earlier (also under old labels), keep the rest.
        known = [label_for[k] for k in self._desc_fields] + self._applied_desc_labels
        desc = update_desc(self.desc.toPlainText(), known, lines)
        if desc != self.desc.toPlainText():
            self.desc.setPlainText(desc)
        self._applied_desc_lines = lines
        self._applied_desc_labels = [label_for[k] for k in self._desc_fields]

    def set_desc_fields(self, fields: list[str]) -> None:
        """Fields written as lines at the top of the description (Settings)."""
        self._desc_fields = validate_desc(fields)
        if self._lot is not None and not self._loading:
            self._applied_desc_lines = None  # force a rewrite in the new layout
            self._apply_desc_fields(self.collect())

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

    def _update_lookup_row(self, *_args) -> None:
        """Lookup buttons work once there's a serial; the hint shows results."""
        has_serial = bool(self.serial.text().strip())
        for button, link in self._link_buttons:
            button.setEnabled(has_serial)
            button.setToolTip(
                (
                    strings.SERIAL_LINK_TIP
                    if has_serial
                    else strings.SERIAL_LINK_NEEDS_SERIAL
                ).format(name=link.name)
            )
        self.lookup_hint.setVisible(has_serial and bool(self.lookup_hint.text()))

    def _update_heading(self, *_args) -> None:
        title = self.title.text().strip()
        self.heading.setText(title or strings.UNTITLED_LOT)
        self.heading.setToolTip(title)

    def _step(self, step: int) -> None:
        button = self.prev_btn if step < 0 else self.next_btn
        if self._lot is not None and button.isEnabled():
            self.step_requested.emit(step)

    def _new_lot(self) -> None:
        if self._lot is not None:
            self.new_lot_requested.emit()

    def apply_autofill(self, values: dict[str, str]) -> None:
        """Put reviewed research suggestions into the open lot's fields
        (keys: make, model, year, serial, barrel_length or "custom:<id>")."""
        if self._lot is None:
            return
        fields = {
            "make": self.make,
            "model": self.model,
            "caliber": self.caliber,
            "gun_type": self.gun_type.lineEdit(),
            "year": self.year,
            "serial": self.serial,
            "barrel_length": self.barrel_length,
        } | {CUSTOM_PREFIX + key: edit for key, edit in self._custom_inputs.items()}
        for key, value in values.items():
            if (edit := fields.get(key)) is not None:
                edit.setText(value)
                edit.setCursorPosition(0)
        # Rebuild the title/description and look the new serial up.
        self._on_serial_done()

    def _open_link(self, link: SerialLink) -> None:
        url = build_url(
            link.url, self.serial.text(), self.title.text(), self.make.text()
        )
        QDesktopServices.openUrl(QUrl(url))

    def _pick_photos(self) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in PHOTO_SUFFIXES)
        files, _ = QFileDialog.getOpenFileNames(
            self, strings.PICK_PHOTOS, "", f"Images ({patterns})"
        )
        self._add_photos([Path(f) for f in files])

    def _add_photos(self, files: list[Path]) -> None:
        if files and self._lot is not None:
            self._photos.extend(files)
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
        has_photos = bool(self._photos)
        self.photo_list.setVisible(has_photos)
        self.photo_empty.setVisible(not has_photos)
        self.photos_more_hint.setVisible(has_photos)
        self.photos_hint.setText(strings.NO_PHOTOS)
        self._fit_photos()

    def _fit_photos(self) -> None:
        """Grow the thumbnail grid with the photos, up to a few rows."""
        if not self._photos:
            return
        width = max(self.photo_list.viewport().width(), PHOTO_GRID.width())
        per_row = max(1, width // PHOTO_GRID.width())
        rows = min(PHOTO_MAX_ROWS, math.ceil(len(self._photos) / per_row))
        self.photo_list.setFixedHeight(rows * PHOTO_GRID.height() + 8)
