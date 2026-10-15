from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIntValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from simple_auction.models import Lot
from simple_auction.services import api_key, lookup, numbering
from simple_auction.services.conditions import ConditionOption, cleaned, save_file
from simple_auction.services.config import Config
from simple_auction.services.listing import condition_desc
from simple_auction.services.serial_links import SerialLink, is_valid
from simple_auction.services.title_layout import (
    DESC_EXCLUDED,
    MAX_CUSTOM_TEXT,
    CustomField,
    desc_lines,
    is_custom_key,
    labels,
    new_custom_id,
    prefixes,
    update_desc,
    update_title,
)
from simple_auction.ui import strings, theme
from simple_auction.ui.field_order import FieldOrderList
from simple_auction.ui.list_editor import Field, ListEditor
from simple_auction.ui.network_settings import NetworkSettings

SECTION_AUCTION = "Auction setup"
SECTION_CONDITIONS = "Conditions"
SECTION_LISTING = "Listing fields"
SECTION_APPEARANCE = "Appearance"
SECTION_SHARING = "Sharing"
SECTION_FOLDERS = "Folders"
SECTION_RESEARCH = "Research"
# (title, nav icon, one-line description shown under the page title)
SECTIONS = [
    (SECTION_AUCTION, "book", strings.SETTINGS_AUCTION_ABOUT),
    (SECTION_CONDITIONS, "list", strings.SETTINGS_CONDITIONS_ABOUT),
    (SECTION_LISTING, "type", strings.SETTINGS_LISTING_ABOUT),
    (SECTION_APPEARANCE, "sun", strings.SETTINGS_APPEARANCE_ABOUT),
    (SECTION_SHARING, "wifi", strings.SETTINGS_SHARING_ABOUT),
    (SECTION_FOLDERS, "folder", strings.SETTINGS_FOLDERS_ABOUT),
    (SECTION_RESEARCH, "sparkle", strings.SETTINGS_RESEARCH_ABOUT),
]

# Theme choices: (label, Config.dark_mode value)
THEMES = [
    (strings.THEME_SYSTEM, None),
    (strings.THEME_LIGHT, False),
    (strings.THEME_DARK, True),
]


class SettingsDialog(QDialog):
    def __init__(self, config: Config, existing: list[int], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.SETTINGS)
        self.setObjectName("settingsDialog")
        self.setMinimumSize(720, 480)
        self._original_conditions = list(config.conditions)
        self._conditions_path = config.conditions_path

        self.network = NetworkSettings(config.sharing, self)
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(190)
        self.nav.setIconSize(QSize(16, 16))
        self.nav.setAccessibleName("Settings sections")
        self.pages = QStackedWidget()
        builders = {
            SECTION_AUCTION: lambda: self._auction_page(config, existing),
            SECTION_CONDITIONS: lambda: self._conditions_page(config),
            SECTION_LISTING: lambda: self._listing_page(config),
            SECTION_APPEARANCE: lambda: self._appearance_page(config),
            SECTION_SHARING: lambda: self.network,
            SECTION_FOLDERS: lambda: self._folders_page(config),
            SECTION_RESEARCH: self._research_page,
        }
        # Pages whose lists grow into spare height; others keep to the top.
        fills = {SECTION_AUCTION, SECTION_CONDITIONS}
        for title, icon, about in SECTIONS:
            item = QListWidgetItem(theme.icon(icon), title)
            item.setSizeHint(QSize(0, 36))
            self.nav.addItem(item)
            self.pages.addWidget(
                self._page(title, about, builders[title](), title in fills)
            )
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QFrame()
        footer.setObjectName("settingsFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 12, 20, 12)
        footer_hint = QLabel(strings.SETTINGS_FOOTER_HINT)
        footer_hint.setObjectName("fieldHint")
        footer_layout.addWidget(footer_hint, 1)
        footer_layout.addWidget(buttons)

        side = QFrame()
        side.setObjectName("settingsSide")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(10, 16, 10, 10)
        side_layout.addWidget(self.nav)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(side)
        body.addWidget(self.pages, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addLayout(body, 1)
        outer.addWidget(footer)
        available = self.screen().availableGeometry()
        self.resize(
            min(1000, available.width() - 60), min(780, available.height() - 60)
        )

    def show_section(self, title: str) -> None:
        self.nav.setCurrentRow([s[0] for s in SECTIONS].index(title))

    # -- pages --------------------------------------------------------------

    def _auction_page(self, config: Config, existing: list[int]) -> QWidget:
        self._suggested = numbering.next_auction(existing, config.step, config.start_at)
        self.next_number = QLineEdit(str(self._suggested))
        self.next_number.setValidator(QIntValidator(1, 99_999_000, self.next_number))
        self.next_number.setFixedWidth(140)
        self.next_number.setAccessibleName(strings.NEXT_AUCTION)
        numbering_section = self._section(strings.NUMBERING_SECTION)
        row = QHBoxLayout()
        row.setSpacing(12)
        label = QLabel(strings.NEXT_AUCTION)
        label.setBuddy(self.next_number)
        row.addWidget(label)
        row.addWidget(self.next_number)
        row.addStretch(1)
        numbering_section.layout().addLayout(row)
        numbering_section.layout().addWidget(self._hint(strings.NEXT_AUCTION_HINT))

        self.links = ListEditor(
            [
                Field("name", strings.LINK_NAME, strings.LINK_NAME_PLACEHOLDER),
                Field(
                    "url",
                    strings.LINK_URL,
                    "https://example.com/lookup?serial={serial}",
                    hint=strings.LINKS_HINT,
                ),
            ],
            noun="link",
            add_label=strings.ADD_LINK,
            empty_text=strings.LINKS_EMPTY,
            new_values={"name": "", "url": "https://"},
            accessible_name="Serial number links",
        )
        for link in config.serial_links:
            self.links.add_row({"name": link.name, "url": link.url})
        self.links.select_first()
        links = self._section(strings.SERIAL_LOOKUP_SECTION)
        links.layout().addWidget(self._hint(strings.SERIAL_LOOKUP_ABOUT))
        links.layout().addWidget(self.links, 1)
        edit_table = QPushButton(strings.EDIT_SERIAL_TABLE)
        edit_table.setToolTip(strings.EDIT_SERIAL_TABLE_TIP)
        theme.set_icon(edit_table, "external")
        edit_table.clicked.connect(self._edit_serial_table)
        table_row = QHBoxLayout()
        table_row.addWidget(self._hint(strings.SERIAL_TABLE_ABOUT), 1)
        table_row.addWidget(edit_table)
        links.layout().addSpacing(4)
        links.layout().addLayout(table_row)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(numbering_section)
        layout.addWidget(links, 1)
        return page

    def _conditions_page(self, config: Config) -> QWidget:
        self.conditions_editor = ListEditor(
            [
                Field("name", strings.CONDITION_NAME, strings.CONDITION_NAME_HINT),
                Field(
                    "note",
                    strings.CONDITION_NOTE,
                    strings.CONDITION_NOTE_PLACEHOLDER,
                    multiline=True,
                ),
            ],
            noun="condition",
            add_label=strings.ADD_CONDITION,
            empty_text=strings.CONDITIONS_EMPTY,
            accessible_name="Auction conditions",
        )
        for option in config.conditions:
            self.conditions_editor.add_row({"name": option.name, "note": option.note})
        self.conditions_editor.select_first()
        self.move_up = self.conditions_editor.move_up
        self.move_down = self.conditions_editor.move_down
        section = self._section(strings.CONDITIONS_SECTION)
        section.layout().addWidget(self._hint(strings.CONDITIONS_HINT))
        section.layout().addWidget(self.conditions_editor, 1)
        open_file = QPushButton(strings.OPEN_CONDITIONS_FILE)
        open_file.setToolTip(strings.OPEN_CONDITIONS_FILE_TIP)
        theme.set_icon(open_file, "external")
        open_file.clicked.connect(self._open_conditions_file)
        footer = QHBoxLayout()
        footer.addWidget(self._hint(strings.CONDITIONS_FILE_ABOUT), 1)
        footer.addWidget(open_file)
        section.layout().addSpacing(4)
        section.layout().addLayout(footer)
        return section

    def _listing_page(self, config: Config) -> QWidget:
        """Choose and order the fields written into titles and descriptions,
        add fields of your own, and see an example of the result."""
        custom = {f.key: f.label for f in config.custom_fields}
        all_labels = labels(config.custom_fields)

        # Title: fields before / after the user's own wording.
        self.title_order = FieldOrderList(
            "Title fields in display order",
            fixed={"title": strings.LISTING_OWN_WORDING},
        )
        for key in config.title_fields + [
            k for k in all_labels if k not in config.title_fields
        ]:
            self.title_order.add(
                key, self._field_label(key, all_labels), key in config.title_fields
            )
        self.title_order.item("title").setToolTip(strings.TITLE_FIELDS_CUSTOM_TIP)
        # Kept for code that works with the list itself.
        self.title_fields_list = self.title_order.list

        # Description: "Label: value" lines at the top, in this order.
        self.desc_order = FieldOrderList("Description fields in display order")
        for key in config.desc_fields + [
            k
            for k in all_labels
            if k not in config.desc_fields and k not in DESC_EXCLUDED
        ]:
            self.desc_order.add(
                key, self._field_label(key, all_labels), key in config.desc_fields
            )

        # A grid keeps the two lists level even when one hint wraps more.
        columns = QGridLayout()
        columns.setHorizontalSpacing(16)
        columns.setVerticalSpacing(6)
        for col, (title, hint, order) in enumerate(
            (
                (
                    strings.LISTING_TITLE_COLUMN,
                    strings.LISTING_TITLE_HINT,
                    self.title_order,
                ),
                (
                    strings.LISTING_DESC_COLUMN,
                    strings.LISTING_DESC_HINT,
                    self.desc_order,
                ),
            )
        ):
            heading = QLabel(title)
            heading.setObjectName("columnTitle")
            text = QLabel(hint)
            text.setObjectName("fieldHint")
            text.setWordWrap(True)
            text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            columns.addWidget(heading, 0, col)
            columns.addWidget(text, 1, col)
            columns.addWidget(order, 2, col)
            columns.setColumnStretch(col, 1)
        arrange = self._section(strings.LISTING_ARRANGE_SECTION)
        arrange.layout().addWidget(self._hint(strings.LISTING_ARRANGE_HINT))
        arrange.layout().addLayout(columns, 1)

        # Live example of the title and description these settings produce.
        self.preview_title = QLabel()
        self.preview_title.setObjectName("previewTitle")
        self.preview_title.setWordWrap(True)
        self.preview_title.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_desc = QLabel()
        self.preview_desc.setObjectName("previewDesc")
        self.preview_desc.setWordWrap(True)
        self.preview_desc.setTextFormat(Qt.TextFormat.PlainText)
        preview = self._section(strings.LISTING_PREVIEW_SECTION)
        preview.layout().addWidget(self._hint(strings.LISTING_PREVIEW_HINT))
        for caption, label in (
            (strings.LISTING_PREVIEW_TITLE, self.preview_title),
            (strings.LISTING_PREVIEW_DESC, self.preview_desc),
        ):
            text = QLabel(caption)
            text.setObjectName("fieldLabel")
            preview.layout().addWidget(text)
            frame = QFrame()
            frame.setObjectName("previewBox")
            inner = QVBoxLayout(frame)
            inner.setContentsMargins(12, 10, 12, 10)
            inner.addWidget(label)
            preview.layout().addWidget(frame)

        # Your own fields: a box each in the lot editor, usable above.
        self.custom_editor = ListEditor(
            [
                Field(
                    "label",
                    strings.CUSTOM_FIELD_NAME,
                    strings.CUSTOM_FIELD_NAME_PLACEHOLDER,
                    hint=strings.CUSTOM_FIELD_NAME_HINT,
                ),
                Field(
                    "prefix",
                    strings.CUSTOM_FIELD_PREFIX,
                    strings.CUSTOM_FIELD_PREFIX_PLACEHOLDER,
                    hint=strings.CUSTOM_FIELD_PREFIX_HINT,
                ),
            ],
            noun="field",
            add_label=strings.ADD_CUSTOM_FIELD,
            empty_text=strings.CUSTOM_FIELDS_EMPTY,
            new_values=lambda: {"id": new_custom_id(), "label": "", "prefix": ""},
            accessible_name="Your own lot fields",
        )
        for field_ in config.custom_fields:
            self.custom_editor.add_row(
                {"id": field_.id, "label": field_.label, "prefix": field_.prefix}
            )
        self.custom_editor.select_first()
        self.custom_editor.list.setMinimumHeight(140)
        own = self._section(strings.CUSTOM_FIELDS_SECTION)
        own.layout().addWidget(self._hint(strings.CUSTOM_FIELDS_HINT))
        own.layout().addWidget(self.custom_editor, 1)
        self._custom_keys = set(custom)

        self.custom_editor.changed.connect(self._sync_custom_fields)
        self.title_order.changed.connect(self._update_preview)
        self.desc_order.changed.connect(self._update_preview)
        self._update_preview()

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        # The lists come first; the example sits right under them so the
        # effect of a change is visible without scrolling far.
        layout.addWidget(arrange)
        layout.addWidget(preview)
        layout.addWidget(own)
        return page

    @staticmethod
    def _field_label(key: str, all_labels: dict[str, str]) -> str:
        label = all_labels.get(key, key)
        if is_custom_key(key):
            return strings.CUSTOM_FIELD_IN_LIST.format(label=label)
        return label

    def _sync_custom_fields(self) -> None:
        """Keep both lists in step with your own fields: new ones are added
        (shown in the description), renamed ones relabelled, removed or
        unnamed ones taken out."""
        wanted = {f.key: f.label for f in self.custom_fields()}
        for order in (self.title_order, self.desc_order):
            for key in [k for k in order.field_keys() if is_custom_key(k)]:
                if key not in wanted:
                    order.remove(key)
        for key, label in wanted.items():
            text = strings.CUSTOM_FIELD_IN_LIST.format(label=label)
            for order, checked in ((self.title_order, False), (self.desc_order, True)):
                if order.item(key) is None:
                    order.add(key, text, checked)
                else:
                    order.set_label(key, text)
        self._custom_keys = set(wanted)
        self._update_preview()

    def _update_preview(self) -> None:
        custom = self.custom_fields()
        # The house-style example: with the default layout and no extra
        # wording this reads exactly
        # "Arsenal SAM7SF 7.62x39 Rifle SN: BE 53 1936 Excellent Condition LEGAL FOR CA".
        sample = Lot(
            1,
            make="Arsenal",
            model="SAM7SF",
            caliber="7.62x39",
            gun_type="Rifle",
            serial="BE 53 1936",
            year=2009,
            condition="Excellent",
            owner="J. Smith",
            book_no="12",
            barrel_length="16.3 inches",
            ca_legality="Legal for CA",
            custom={
                f.id: strings.LISTING_PREVIEW_VALUE.format(label=f.label)
                for f in custom
            },
        )
        fields = self.title_fields()
        self.preview_title.setText(
            update_title("", Lot(0), fields, sample, fields, prefixes(custom)) or "—"
        )
        lines = desc_lines(sample, self.desc_fields(), labels(custom))
        desc = update_desc(strings.LISTING_PREVIEW_DESC_TEXT, [], lines)
        self.preview_desc.setText(
            condition_desc(desc, "Excellent", strings.LISTING_PREVIEW_CONDITION)
        )

    def _appearance_page(self, config: Config) -> QWidget:
        section = self._section(strings.THEME_SECTION)
        self.theme_buttons = QButtonGroup(self)
        self.theme_options = {}
        for label, value in THEMES:
            button = QRadioButton(label)
            self.theme_buttons.addButton(button)
            self.theme_options[value] = button
            section.layout().addWidget(button)
        self.theme_options[config.dark_mode].setChecked(True)
        section.layout().addWidget(self._hint(strings.THEME_HINT))
        self.dyslexic_toggle = QCheckBox("Use OpenDyslexic")
        self.dyslexic_toggle.setChecked(config.dyslexic_font)
        self.dyslexic_toggle.setAccessibleName("Use OpenDyslexic font")
        section.layout().addWidget(self.dyslexic_toggle)
        section.layout().addWidget(
            self._hint(
                "A bundled reading-friendly font. No separate font installation is needed."
            )
        )
        size_label = QLabel("Text size")
        self.font_size_choice = QComboBox()
        self.font_size_choice.setAccessibleName("Text size")
        for size in ("small", "medium", "large"):
            self.font_size_choice.addItem(size.title(), size)
        self.font_size_choice.setCurrentIndex(
            self.font_size_choice.findData(config.font_size)
        )
        size_label.setBuddy(self.font_size_choice)
        section.layout().addWidget(size_label)
        section.layout().addWidget(self.font_size_choice)
        self.font_preview = QLabel(
            "Aa Bb Dd — Catalogue descriptions and research notes. 0123456789"
        )
        self.font_preview.setWordWrap(True)
        self.font_preview.setAccessibleName("Font preview")
        section.layout().addWidget(self.font_preview)
        self.dyslexic_toggle.toggled.connect(self._update_font_preview)
        self.font_size_choice.currentIndexChanged.connect(self._update_font_preview)
        self._update_font_preview()
        return section

    def _folders_page(self, config: Config) -> QWidget:
        self.folder = QLineEdit(str(config.base_dir))
        self.photos = QLineEdit(str(config.photos_dir))
        self.folder.setProperty("spellcheck", False)
        self.photos.setProperty("spellcheck", False)
        section = self._section(strings.FOLDERS_SECTION)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        rows = (
            (
                strings.AUCTIONS_FOLDER,
                self.folder,
                strings.PICK_FOLDER,
                strings.MAIN_FOLDER_HINT,
            ),
            (
                strings.PHOTOS_FOLDER,
                self.photos,
                strings.PICK_PHOTOS_FOLDER,
                strings.PHOTOS_FOLDER_HINT,
            ),
        )
        for i, (label, field, title, hint) in enumerate(rows):
            text = QLabel(label)
            text.setObjectName("fieldLabel")
            text.setBuddy(field)
            field.setAccessibleName(label)
            browse = QPushButton(strings.BROWSE)
            browse.clicked.connect(lambda _=False, f=field, t=title: self._browse(f, t))
            show = QPushButton(strings.SHOW_FOLDER)
            theme.set_icon(show, "folder")
            show.setToolTip(strings.SHOW_FOLDER_TIP)
            show.clicked.connect(lambda _=False, f=field: self._show_folder(f))
            base = i * 4
            if i:
                grid.setRowMinimumHeight(base - 1, 14)
            grid.addWidget(text, base, 0, 1, 3)
            grid.addWidget(field, base + 1, 0)
            grid.addWidget(browse, base + 1, 1)
            grid.addWidget(show, base + 1, 2)
            grid.addWidget(self._hint(hint), base + 2, 0, 1, 3)
        grid.setColumnStretch(0, 1)
        section.layout().addLayout(grid)
        return section

    def _research_page(self) -> QWidget:
        section = self._section(strings.RESEARCH_SECTION)
        section.layout().addWidget(self._hint(strings.RESEARCH_ABOUT))
        label = QLabel(strings.API_KEY)
        label.setObjectName("fieldLabel")
        self.key = QLineEdit()
        self.key.setProperty("spellcheck", False)  # stays excluded when Show reveals it
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setAccessibleName(strings.API_KEY)
        label.setBuddy(self.key)
        self.show_key = QPushButton(strings.SHOW_KEY)
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(
            lambda shown: (
                self.key.setEchoMode(
                    QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
                ),
                self.show_key.setText(strings.HIDE_KEY if shown else strings.SHOW_KEY),
            )
        )
        self.forget_key = QPushButton(strings.FORGET_KEY)
        theme.set_icon(self.forget_key, "trash")
        self.forget_key.clicked.connect(self._forget_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        key_row.addWidget(self.show_key)
        key_row.addWidget(self.forget_key)
        self.key_state = QLabel()
        self.key_state.setObjectName("fieldHint")
        get_key = QPushButton(strings.GET_API_KEY)
        get_key.setObjectName("link")
        theme.set_icon(get_key, "external", "accent")
        get_key.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        get_key.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(strings.GET_API_KEY_URL))
        )
        section.layout().addSpacing(4)
        section.layout().addWidget(label)
        section.layout().addLayout(key_row)
        section.layout().addWidget(self.key_state)
        section.layout().addWidget(get_key, 0, Qt.AlignmentFlag.AlignLeft)
        self._refresh_key_state()
        return section

    # -- building blocks ----------------------------------------------------

    def _page(self, title: str, about: str, content: QWidget, fills: bool):
        page = QWidget()
        page.setObjectName("scrollBody")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 24, 22)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("settingsPageTitle")
        layout.addWidget(heading)
        layout.addWidget(self._hint(about))
        layout.addSpacing(12)
        layout.addWidget(content, 1 if fills else 0)
        if not fills:
            layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    @staticmethod
    def _section(title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("settingsSection")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("settingsSectionTitle")
        layout.addWidget(heading)
        return frame

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label

    # -- results ------------------------------------------------------------

    def accept(self):
        if self.network.validate():
            super().accept()
        else:
            self.show_section(SECTION_SHARING)

    def sharing(self):
        return self.network.value()

    def dark_mode(self) -> bool | None:
        """True/False for a fixed theme, None to follow the system."""
        return next(
            value for value, button in self.theme_options.items() if button.isChecked()
        )

    def dyslexic_font(self) -> bool:
        return self.dyslexic_toggle.isChecked()

    def font_size(self) -> str:
        return self.font_size_choice.currentData()

    def _update_font_preview(self) -> None:
        font = theme.text_font(
            dyslexic_font=self.dyslexic_font(), font_size=self.font_size()
        )
        self.font_preview.setStyleSheet(
            f'font-family: "{font.family()}"; font-size: {font.pixelSize()}px;'
        )

    def custom_fields(self) -> list[CustomField]:
        """Custom fields with a name, in the order listed."""
        return [
            CustomField(
                row["id"],
                row["label"].strip()[:MAX_CUSTOM_TEXT],
                row["prefix"].strip()[:MAX_CUSTOM_TEXT],
            )
            for row in self.custom_editor.rows()
            if row["label"].strip()
        ]

    def title_fields(self) -> list[str]:
        """Ticked title fields in order, around the user's own wording."""
        return self.title_order.included()

    def desc_fields(self) -> list[str]:
        """Ticked description fields in order."""
        return self.desc_order.included()

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

    def serial_links(self) -> list[SerialLink]:
        """The rows that make a usable link (name + http(s) URL)."""
        links = (
            SerialLink(row["name"].strip(), row["url"].strip())
            for row in self.links.rows()
        )
        return [link for link in links if is_valid(link)]

    def original_conditions(self) -> list[ConditionOption]:
        return list(self._original_conditions)

    def conditions(self) -> list[ConditionOption]:
        """The condition rows, in order (blank and repeated names dropped)."""
        return cleaned(
            [
                ConditionOption(row["name"], row["note"])
                for row in self.conditions_editor.rows()
            ]
        )

    # -- actions ------------------------------------------------------------

    def _refresh_key_state(self) -> None:
        saved = api_key.saved() is not None
        self.key.setPlaceholderText(
            strings.API_KEY_SAVED_PLACEHOLDER if saved else strings.API_KEY_PLACEHOLDER
        )
        self.key_state.setText(strings.API_KEY_SAVED if saved else strings.API_KEY_NONE)
        self.forget_key.setEnabled(saved)

    def _forget_key(self) -> None:
        api_key.forget()
        self.key.clear()
        self._refresh_key_state()

    def _open_conditions_file(self) -> None:
        """Open conditions.yaml in the default text editor (or show it in the
        folder if no app is set up to open .yaml files)."""
        path = self._conditions_path
        if not path.exists():
            save_file(path, self._original_conditions)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _browse(self, field: QLineEdit, title: str) -> None:
        chosen = QFileDialog.getExistingDirectory(self, title, field.text())
        if chosen:
            field.setText(chosen)

    @staticmethod
    def _show_folder(field: QLineEdit) -> None:
        path = Path(field.text()).expanduser()
        while not path.exists() and path != path.parent:
            path = path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _edit_serial_table(self) -> None:
        path = lookup.table_path(Config(base_dir=self.base_dir()).data_dir)
        lookup.ensure_table(path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
