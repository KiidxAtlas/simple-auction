"""Full shipping workspace; catalogue widgets stay in their own stacked page."""

import base64
import json
from copy import deepcopy
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QLocale, QSignalBlocker, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QDoubleValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from simple_auction.services import network, shipping, storage
from simple_auction.ui import strings, theme
from simple_auction.ui.background import run_io
from simple_auction.ui.shipping_import_dialog import ShippingImportDialog


class ShippingPage(QWidget):
    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.client = None
        self.shared = False
        self._shared_base = None
        self.folder = folder
        self.batch: shipping.Batch | None = None
        self.path: Path | None = None
        self.dirty = False
        self.busy = False
        self._loaded = False
        self._quiet = False
        self._buyer_index = -1
        self._package_index = 0
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(lambda: self.flush(warn=False))

        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(18)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        heading = QLabel("Shipping")
        heading.setObjectName("lotTitle")
        titles.addWidget(heading)
        subtitle = QLabel(
            "Turn a Proxibid winning-bidders report into a Pirate Ship upload."
        )
        subtitle.setObjectName("hint")
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        # Where the user is in import → review → export; updated by _update_summary.
        self.step_bar = QWidget()
        steps = QHBoxLayout(self.step_bar)
        steps.setContentsMargins(0, 0, 0, 0)
        steps.setSpacing(4)
        self.steps: list[QLabel] = []
        for number, text in enumerate(
            ("Import report", "Weigh & measure", "Export CSV"), 1
        ):
            if number > 1:
                divider = QLabel("—")
                divider.setObjectName("shippingStepDivider")
                steps.addWidget(divider)
            step = QLabel(f"{number}  {text}")
            step.setObjectName("shippingStep")
            self.steps.append(step)
            steps.addWidget(step)
        header.addWidget(self.step_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.import_button = QPushButton("Import CSV…")
        self.import_button.setToolTip("Import a Proxibid winning-bidders CSV report.")
        self.import_button.clicked.connect(lambda: self.import_report())
        header.addWidget(self.import_button)
        layout.addLayout(header)

        self.workspace = QStackedWidget()
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("shippingEmpty")
        empty_layout = QVBoxLayout(self.drop_zone)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intro = QWidget()
        intro.setMaximumWidth(540)
        intro_layout = QVBoxLayout(intro)
        intro_layout.setSpacing(12)
        eyebrow = QLabel("GET STARTED")
        eyebrow.setObjectName("sectionLabel")
        intro_layout.addWidget(eyebrow)
        title = QLabel("Import your Proxibid winning-bidders report")
        title.setObjectName("shippingEmptyTitle")
        title.setWordWrap(True)
        intro_layout.addWidget(title)
        description = QLabel(
            "In Proxibid, download the auction's Winning Bidders report as a CSV "
            "file. Each buyer is grouped with their shipping address and the lots "
            "they won."
        )
        description.setObjectName("hint")
        description.setWordWrap(True)
        intro_layout.addWidget(description)
        intro_layout.addSpacing(6)
        for number, (step_title, step_detail) in enumerate(
            (
                ("Import the CSV", "Confirm the columns before anything is saved."),
                (
                    "Weigh and measure every box",
                    (
                        "Check each buyer's address, pack their lots, and enter "
                        "the weight and box size. Split lots into extra boxes or "
                        "mark local pickups as needed."
                    ),
                ),
                (
                    "Export for Pirate Ship",
                    "Upload the spreadsheet in Pirate Ship to buy labels.",
                ),
            ),
            1,
        ):
            row = QHBoxLayout()
            row.setSpacing(12)
            badge = QLabel(str(number))
            badge.setObjectName("shippingStepNumber")
            badge.setFixedSize(26, 26)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            text_column = QVBoxLayout()
            text_column.setSpacing(1)
            step_heading = QLabel(step_title)
            step_heading.setObjectName("shippingStepTitle")
            text_column.addWidget(step_heading)
            detail = QLabel(step_detail)
            detail.setObjectName("hint")
            detail.setWordWrap(True)
            text_column.addWidget(detail)
            row.addLayout(text_column, 1)
            intro_layout.addLayout(row)
        intro_layout.addSpacing(8)
        actions = QHBoxLayout()
        actions.setSpacing(12)
        choose = QPushButton("Choose CSV file…")
        choose.setObjectName("primary")
        choose.setMinimumHeight(40)
        choose.clicked.connect(lambda: self.import_report())
        actions.addWidget(choose)
        drop_hint = QLabel("or drop the file anywhere on this page")
        drop_hint.setObjectName("hint")
        actions.addWidget(drop_hint)
        actions.addStretch()
        intro_layout.addLayout(actions)
        saved_hint = QLabel(
            "Progress saves automatically, so you can stop and pick up where you "
            "left off."
        )
        saved_hint.setObjectName("hint")
        saved_hint.setWordWrap(True)
        intro_layout.addWidget(saved_hint)
        empty_layout.addWidget(intro)
        self.workspace.addWidget(self.drop_zone)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        queue = QFrame()
        queue.setObjectName("shippingQueue")
        queue.setMinimumWidth(240)
        queue.setMaximumWidth(360)
        queue_layout = QVBoxLayout(queue)
        queue_layout.setContentsMargins(14, 16, 14, 12)
        queue_layout.setSpacing(10)
        self.batch_bar = QWidget()
        bar = QVBoxLayout(self.batch_bar)
        bar.setContentsMargins(0, 0, 0, 4)
        bar.setSpacing(4)
        label = QLabel("AUCTION")
        label.setObjectName("sectionLabel")
        bar.addWidget(label)
        self.batches = QComboBox()
        self.batches.currentIndexChanged.connect(self._select_batch)
        bar.addWidget(self.batches)
        queue_layout.addWidget(self.batch_bar)
        queue_header = QHBoxLayout()
        queue_title = QLabel("Buyers")
        queue_title.setObjectName("shippingCardTitle")
        queue_header.addWidget(queue_title, 1)
        self.queue_count = QLabel()
        self.queue_count.setObjectName("hint")
        queue_header.addWidget(self.queue_count)
        queue_layout.addLayout(queue_header)
        self.progress = QProgressBar()
        self.progress.setObjectName("shippingProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        queue_layout.addWidget(self.progress)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("hint")
        queue_layout.addWidget(self.progress_label)
        queue_layout.addSpacing(2)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, bidder, or lot")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        queue_layout.addWidget(self.search)
        self.status_filter = QComboBox()
        for label, value in (
            ("All buyers", "all"),
            ("Needs attention", "attention"),
            ("Ready to export", "ready"),
            ("Already exported", "exported"),
            ("Local pickup", "pickup"),
        ):
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self._filter)
        queue_layout.addWidget(self.status_filter)
        self.buyers = QTableWidget(0, 2)
        self.buyers.setObjectName("shippingBuyers")
        self.buyers.horizontalHeader().hide()
        self.buyers.verticalHeader().hide()
        self.buyers.verticalHeader().setDefaultSectionSize(60)
        self.buyers.setShowGrid(False)
        self.buyers.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.buyers.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.buyers.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.buyers.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.buyers.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.buyers.currentCellChanged.connect(self._select_buyer)
        queue_layout.addWidget(self.buyers, 1)
        self.splitter.addWidget(queue)

        review = QWidget()
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(16, 0, 0, 0)
        review_layout.setSpacing(14)
        buyer_header = QHBoxLayout()
        buyer_labels = QVBoxLayout()
        buyer_labels.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.buyer_title = QLabel("Select a buyer")
        self.buyer_title.setObjectName("shippingBuyerTitle")
        self.buyer_title.setTextFormat(Qt.TextFormat.PlainText)
        title_row.addWidget(self.buyer_title)
        self.buyer_status = QLabel()
        self.buyer_status.setObjectName("shippingPill")
        self.buyer_status.hide()
        title_row.addWidget(self.buyer_status, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        buyer_labels.addLayout(title_row)
        self.buyer_meta = QLabel()
        self.buyer_meta.setObjectName("hint")
        self.buyer_meta.setTextFormat(Qt.TextFormat.PlainText)
        buyer_labels.addWidget(self.buyer_meta)
        buyer_header.addLayout(buyer_labels, 1)
        self.next_buyer = QPushButton("Next buyer →")
        self.next_buyer.setToolTip("Skip to the next buyer in the list.")
        self.next_buyer.clicked.connect(self._next_buyer)
        buyer_header.addWidget(self.next_buyer, 0, Qt.AlignmentFlag.AlignTop)
        review_layout.addLayout(buyer_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor = QWidget()
        self.editor.setMinimumWidth(340)
        self.detail_columns = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.editor)
        self.detail_columns.setContentsMargins(0, 0, 0, 0)
        self.detail_columns.setSpacing(16)
        self.detail_columns.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.package_column = QWidget()
        package_layout = QVBoxLayout(self.package_column)
        package_layout.setContentsMargins(0, 0, 0, 0)
        package_layout.setSpacing(14)
        self.packing_panel = QFrame()
        self.packing_panel.setObjectName("shippingCard")
        packing = QVBoxLayout(self.packing_panel)
        packing.setContentsMargins(18, 18, 18, 18)
        packing.setSpacing(14)
        packing_heading = QLabel("Package details")
        packing_heading.setObjectName("shippingCardTitle")
        packing.addWidget(packing_heading)
        self.box_controls = QWidget()
        boxes = QHBoxLayout(self.box_controls)
        boxes.setContentsMargins(0, 0, 0, 0)
        self.packages = QComboBox()
        self.packages.currentIndexChanged.connect(self._select_package)
        boxes.addWidget(self.packages, 1)
        self.add_box = QPushButton("+ Box")
        self.add_box.clicked.connect(self.add_package)
        boxes.addWidget(self.add_box)
        self.remove_box = QPushButton("Remove")
        self.remove_box.setObjectName("link")
        self.remove_box.clicked.connect(self.remove_package)
        boxes.addWidget(self.remove_box)
        packing.addWidget(self.box_controls)
        weight_label = QLabel("Weight")
        weight_label.setObjectName("shippingFieldLabel")
        packing.addWidget(weight_label)
        self.measurements: dict[str, QLineEdit] = {}
        for key in ("weight_lb", "length", "width", "height"):
            edit = QLineEdit()
            edit.setObjectName("shippingNumber")
            validator = QDoubleValidator(0, 1e9, 10, edit)
            validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            locale = QLocale.c()
            locale.setNumberOptions(QLocale.NumberOption.RejectGroupSeparator)
            validator.setLocale(locale)
            edit.setValidator(validator)
            edit.setMaxLength(24)
            edit.textChanged.connect(
                lambda value, name=key: self._measurement_changed(name, value)
            )
            self.measurements[key] = edit
        weight_box = QFrame()
        weight_box.setObjectName("shippingWeightBox")
        weight_layout = QHBoxLayout(weight_box)
        weight_layout.setContentsMargins(14, 6, 14, 6)
        weight = self.measurements["weight_lb"]
        weight.setObjectName("shippingWeight")
        weight.setPlaceholderText("0.00")
        weight.setMinimumHeight(46)
        weight_layout.addWidget(weight, 1)
        unit = QLabel("lb")
        unit.setObjectName("shippingWeightUnit")
        weight_layout.addWidget(unit)
        packing.addWidget(weight_box)
        weight_hint = QLabel("Type pounds, including decimals. Example: 2.5 lb")
        weight_hint.setObjectName("hint")
        weight_hint.setWordWrap(True)
        packing.addWidget(weight_hint)
        dimension_label = QLabel("Box size · inches")
        dimension_label.setObjectName("shippingFieldLabel")
        packing.addWidget(dimension_label)
        dimensions = QHBoxLayout()
        for key, label, example in (
            ("length", "Length", "12"),
            ("width", "Width", "8"),
            ("height", "Height", "6"),
        ):
            group = QVBoxLayout()
            label_widget = QLabel(label)
            label_widget.setObjectName("hint")
            group.addWidget(label_widget)
            self.measurements[key].setPlaceholderText(example)
            self.measurements[key].setMinimumHeight(38)
            group.addWidget(self.measurements[key])
            dimensions.addLayout(group)
        packing.addLayout(dimensions)
        package_layout.addWidget(self.packing_panel)
        self.items_card = QFrame()
        self.items_card.setObjectName("shippingCard")
        items_layout = QVBoxLayout(self.items_card)
        items_layout.setContentsMargins(18, 16, 18, 16)
        self.lots_label = QLabel("Items in this shipment")
        self.lots_label.setObjectName("shippingCardTitle")
        self.lots_label.setWordWrap(True)
        items_layout.addWidget(self.lots_label)
        self.lots = QListWidget()
        self.lots.setObjectName("shippingLots")
        self.lots.setMinimumHeight(80)
        self.lots.setMaximumHeight(100)
        self.lots.itemChanged.connect(self._lot_changed)
        items_layout.addWidget(self.lots)
        package_layout.addStretch()
        self.detail_columns.addWidget(self.package_column, 3)

        address_card = QFrame()
        address_card.setObjectName("shippingCard")
        address_card.setMinimumWidth(250)
        address_layout = QVBoxLayout(address_card)
        address_layout.setContentsMargins(16, 16, 16, 16)
        address_layout.setSpacing(10)
        address_header = QHBoxLayout()
        address_title = QLabel("Shipping address")
        address_title.setObjectName("shippingCardTitle")
        address_header.addWidget(address_title, 1)
        self.edit_address = QPushButton("Edit")
        self.edit_address.setObjectName("link")
        self.edit_address.setCheckable(True)
        address_header.addWidget(self.edit_address)
        address_layout.addLayout(address_header)
        self.address_summary = QLabel()
        self.address_summary.setObjectName("shippingAddressText")
        self.address_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.address_summary.setWordWrap(True)
        self.address_summary.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        address_layout.addWidget(self.address_summary)
        self.address_editor = QWidget()
        address_grid = QGridLayout(self.address_editor)
        address_grid.setContentsMargins(0, 0, 0, 0)
        self.address: dict[str, QLineEdit] = {}
        placements = (
            ("name", "Name", 0, 0, 2),
            ("email", "Email", 1, 0, 2),
            ("address1", "Street address", 2, 0, 2),
            ("address2", "Apartment / unit", 3, 0, 2),
            ("city", "City", 4, 0, 2),
            ("state", "State", 5, 0, 1),
            ("zip", "Postal code", 5, 1, 1),
            ("country", "Country", 6, 0, 2),
        )
        for key, label, row, column, span in placements:
            group = QWidget()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(4)
            group_layout.addWidget(QLabel(label))
            edit = QLineEdit()
            if key == "country":
                edit.setMaxLength(2)
                edit.setPlaceholderText("US, CA, GB…")
            edit.textChanged.connect(self._address_changed)
            self.address[key] = edit
            group_layout.addWidget(edit)
            address_grid.addWidget(group, row, column, 1, span)
        self.address_editor.hide()
        self.edit_address.toggled.connect(self.address_editor.setVisible)
        self.edit_address.toggled.connect(
            lambda editing: self.address_summary.setVisible(not editing)
        )
        address_layout.addWidget(self.address_editor)
        self.pickup = QCheckBox("Local pickup")
        self.pickup.setToolTip("Leave this buyer out of the Pirate Ship export.")
        self.pickup.toggled.connect(self._pickup_changed)
        address_layout.addWidget(self.pickup)
        address_column = QWidget()
        address_column_layout = QVBoxLayout(address_column)
        address_column_layout.setContentsMargins(0, 0, 0, 0)
        address_column_layout.setSpacing(14)
        address_column_layout.addWidget(address_card)
        address_column_layout.addWidget(self.items_card)
        address_column_layout.addStretch()
        self.detail_columns.addWidget(address_column, 2)
        scroll.setWidget(self.editor)
        review_layout.addWidget(scroll, 1)
        action_bar = QFrame()
        action_bar.setObjectName("shippingActionBar")
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(16, 10, 10, 10)
        action_layout.setSpacing(12)
        self.validation = QLabel()
        self.validation.setObjectName("shippingCheck")
        self.validation.setTextFormat(Qt.TextFormat.PlainText)
        self.validation.setWordWrap(True)
        action_layout.addWidget(self.validation, 1)
        self.ready_next = QPushButton("Mark ready && next →")
        self.ready_next.setObjectName("primary")
        self.ready_next.setMinimumHeight(40)
        self.ready_next.setToolTip("Mark this box packed and move on. Shortcut: Return")
        self.ready_next.clicked.connect(self._ready_and_next)
        action_layout.addWidget(self.ready_next)
        review_layout.addWidget(action_bar)
        self.splitter.addWidget(review)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 800])
        self.workspace.addWidget(self.splitter)
        layout.addWidget(self.workspace, 1)

        self.export_result = QFrame()
        self.export_result.setObjectName("shippingExport")
        result_layout = QHBoxLayout(self.export_result)
        result_layout.setContentsMargins(16, 12, 12, 12)
        result_layout.setSpacing(10)
        result_text = QVBoxLayout()
        result_text.setSpacing(2)
        result_title = QLabel("CSV exported · next, upload it to Pirate Ship")
        result_title.setObjectName("shippingCardTitle")
        result_text.addWidget(result_title)
        self.export_message = QLabel()
        self.export_message.setWordWrap(True)
        self.export_message.setTextFormat(Qt.TextFormat.PlainText)
        self.export_message.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        result_text.addWidget(self.export_message)
        result_layout.addLayout(result_text, 1)
        self.show_export = QPushButton("Open export folder")
        self.show_export.clicked.connect(self._open_export_folder)
        result_layout.addWidget(self.show_export)
        self.open_ship = QPushButton("Open Pirate Ship")
        self.open_ship.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://ship.pirateship.com/ship"))
        )
        result_layout.addWidget(self.open_ship)
        layout.addWidget(self.export_result)
        self.export_footer = QFrame()
        self.export_footer.setObjectName("shippingFooter")
        footer = QHBoxLayout(self.export_footer)
        footer.setContentsMargins(16, 12, 14, 12)
        footer.setSpacing(14)
        footer_labels = QVBoxLayout()
        footer_labels.setSpacing(2)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        footer_labels.addWidget(self.summary)
        self.notice = QLabel("Your progress is saved automatically.")
        self.notice.setObjectName("hint")
        self.notice.setWordWrap(True)
        footer_labels.addWidget(self.notice)
        footer.addLayout(footer_labels, 1)
        self.export_button = QPushButton("Export to Pirate Ship…")
        self.export_button.setObjectName("primary")
        self.export_button.setMinimumHeight(42)
        self.export_button.clicked.connect(self.export_report)
        footer.addWidget(self.export_button)
        layout.addWidget(self.export_footer)
        fields = list(self.measurements.values())
        for previous, following in pairwise(fields):
            QWidget.setTabOrder(previous, following)
        QWidget.setTabOrder(fields[-1], self.ready_next)
        fields[-1].returnPressed.connect(self._ready_and_next)
        self._update_summary()
        self._fill_editor()

    def _io(self, label, operation):
        self.busy = True
        try:
            return run_io(self.window(), label, operation)
        finally:
            self.busy = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "detail_columns"):
            wide = self.width() >= 1020
            self.detail_columns.setDirection(
                QBoxLayout.Direction.LeftToRight
                if wide
                else QBoxLayout.Direction.TopToBottom
            )
            self.step_bar.setVisible(wide)

    @staticmethod
    def _set_state(widget, state):
        """Set the `state` property that styles.qss uses, and restyle."""
        if widget.property("state") != state:
            widget.setProperty("state", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    @staticmethod
    def _dropped_csv(event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() == ".csv":
                return path
        return None

    def dragEnterEvent(self, event):
        if not self.busy and self._dropped_csv(event):
            event.acceptProposedAction()
            self._set_state(self.drop_zone, "dragging")
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_state(self.drop_zone, None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_state(self.drop_zone, None)
        if not self.busy and (path := self._dropped_csv(event)):
            event.acceptProposedAction()
            self.import_report(path)
        else:
            event.ignore()

    def _status(self, buyer, package):
        status = shipping.package_status(buyer, package)
        if status == "Needs attention" and not shipping.problems(
            buyer, package, include_measurements=False
        ):
            return "To pack"
        return "To pack" if status == "Needs packing" else status

    def _ready(self):
        return shipping.ready_packages(self.batch) if self.batch else []

    def _next_buyer(self):
        if not self.batch:
            return
        for row in range(self._buyer_index + 1, len(self.batch.buyers)):
            if not self.buyers.isRowHidden(row):
                self.buyers.setCurrentCell(row, 0)
                return
        self.notice.setText("This is the last buyer in the list.")

    def _ready_and_next(self):
        buyer, package = self._buyer(), self._package()
        if (
            not buyer
            or not package
            or buyer.pickup
            or package.exported_at
            or shipping.problems(buyer, package)
        ):
            return
        package.packed = True
        self._changed()
        # Finish this buyer's other boxes before moving to another buyer.
        for index, box in enumerate(buyer.packages):
            if not box.packed and not box.exported_at:
                self._package_index = index
                self._fill_editor()
                return
        self._next_buyer()
        self._fill_editor()

    def _last_export(self):
        return max(
            (p for b in self.batch.buyers for p in b.packages if p.exported_at)
            if self.batch
            else [],
            key=lambda p: p.exported_at,
            default=None,
        )

    def _open_export_folder(self):
        if package := self._last_export():
            if self.shared:
                self.download_export(package.exported_file)
                return
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(package.exported_file).parent))
            )

    def activate(self) -> bool:
        if not self._loaded:
            return self.reload(self.folder)
        return True

    def reload(self, folder: Path) -> bool:
        if not self.flush():
            return False
        self.folder = folder
        self.batch = None
        self.path = None
        self._buyer_index = -1
        self._loaded = False
        try:

            def discover():
                if self.shared:
                    if self.client is None:
                        raise network.NetworkError(
                            "Hosting is unavailable. Check Local network sharing in Settings."
                        )
                    return sorted(
                        self.client.snapshot()["shipping"].items(),
                        key=lambda item: item[1],
                    )
                if not folder.exists():
                    return []
                for journal in folder.glob(".*.json.transaction"):
                    storage.recover(journal)
                result = []
                for path in sorted(folder.glob("*.json")):
                    try:
                        result.append((path, shipping.load_batch(path).auction))
                    except shipping.ShippingError:
                        result.append((path, f"Unreadable: {path.name}"))
                return result

            choices = self._io("Loading shipping progress…", discover)
        except (OSError, shipping.ShippingError) as e:
            self._error(e)
            return False
        with QSignalBlocker(self.batches):
            self.batches.clear()
            self.batches.addItem("Choose an auction…", None)
            for path, auction in choices:
                self.batches.addItem(auction, path)
        self._loaded = True
        self._fill_buyers()
        if choices:
            self.batches.setCurrentIndex(len(choices))
        return True

    def _error(self, error):
        QMessageBox.warning(self, "Shipping", str(error))

    def _restore_batch_selection(self):
        with QSignalBlocker(self.batches):
            self.batches.setCurrentIndex(self.batches.findData(self.path))

    def _select_batch(self, _index):
        path = self.batches.currentData()
        if path == self.path:
            return
        if not self.flush():
            self._restore_batch_selection()
            return
        try:
            batch = (
                self._io("Loading shipping progress…", lambda: self._load_batch(path))
                if path
                else None
            )
        except (OSError, shipping.ShippingError) as e:
            self._error(e)
            self._restore_batch_selection()
            return
        self.path, self.batch = path, batch
        self._shared_base = network.batch_data(batch) if batch and self.shared else None
        self._fill_buyers()

    def import_report(self, path: Path | None = None):
        if not self.flush():
            return
        if path is None:
            name, _ = QFileDialog.getOpenFileName(
                self, "Choose Proxibid Winning Bidders CSV", "", "CSV reports (*.csv)"
            )
            if not name:
                return
            path = Path(name)
        try:
            sheet = self._io(
                "Reading Proxibid report…", lambda: shipping.read_report(path)
            )
            dialog = ShippingImportDialog(path, sheet, self)
            if not dialog.exec():
                return
            batch = dialog.batch
            if batch is None:
                return
            target = (
                network.shipping_key(batch.auction)
                if self.shared
                else shipping.batch_path(self.folder, batch.auction)
            )
            if not self.shared and target.exists():
                raise shipping.ShippingError(
                    "This auction reference already has saved shipping progress. Select it from the auction list. For a different auction, import with a different reference."
                )
            self._io(
                "Saving shipping orders…", lambda: self._save_batch(target, batch, None)
            )
        except (OSError, UnicodeError, shipping.ShippingError) as e:
            self._error(e)
            return
        self.path, self.batch = target, batch
        self._shared_base = network.batch_data(batch) if self.shared else None
        with QSignalBlocker(self.batches):
            self.batches.addItem(batch.auction, target)
            self.batches.setCurrentIndex(self.batches.count() - 1)
        self.search.clear()
        self.status_filter.setCurrentIndex(0)
        self.notice.setText("Buyers imported. Check their addresses, then export.")
        self._fill_buyers()

    def _fill_buyers(self):
        self._buyer_index = -1
        with QSignalBlocker(self.buyers):
            self.buyers.setRowCount(len(self.batch.buyers) if self.batch else 0)
            if self.batch:
                for row in range(len(self.batch.buyers)):
                    self._buyer_row(row)
        self.editor.setEnabled(False)
        self._update_summary()
        self._filter()
        self._fill_editor()

    def _buyer_state(self, buyer):
        """One label and style state summarising all of a buyer's boxes."""
        statuses = {self._status(buyer, p) for p in buyer.packages}
        if statuses == {"Exported"}:
            return "Exported", "done"
        if buyer.pickup:
            return "Local pickup", "neutral"
        if statuses & {"Needs attention", "Check address / items"}:
            return "Check details", "attention"
        if statuses <= {"Ready", "Exported"}:
            return "Ready", "ready"
        return "To pack", "neutral"

    def _buyer_row(self, row):
        buyer = self.batch.buyers[row]
        text, state = self._buyer_state(buyer)
        colors = theme.colors()
        name = QTableWidgetItem(
            f"{buyer.name or 'Unnamed buyer'}\n"
            f"{strings.count(len(buyer.lots), 'lot')} · #{buyer.id}"
        )
        status = QTableWidgetItem(text)
        status.setForeground(
            QColor(
                {"ready": colors.accent, "attention": colors.danger}.get(
                    state, colors.muted
                )
            )
        )
        status.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        font = status.font()
        font.setBold(state in ("ready", "attention"))
        status.setFont(font)
        for col, item in enumerate((name, status)):
            item.setToolTip(f"Bidder {buyer.id} · {buyer.email}")
            self.buyers.setItem(row, col, item)

    def _filter(self, *_args):
        if self.batch:
            query = self.search.text().strip().casefold()
            for row, b in enumerate(self.batch.buyers):
                statuses = [self._status(b, p) for p in b.packages]
                selected = self.status_filter.currentData()
                matches = {
                    "all": True,
                    "attention": any(
                        s not in ("Ready", "Exported", "Local pickup") for s in statuses
                    ),
                    "ready": "Ready" in statuses,
                    "exported": "Exported" in statuses,
                    "pickup": b.pickup,
                }[selected]
                self.buyers.setRowHidden(
                    row,
                    not matches
                    or query
                    not in " ".join((b.name, b.id, b.email, *b.lots)).casefold(),
                )
            row = self.buyers.currentRow()
            if row < 0 or self.buyers.isRowHidden(row):
                first = next(
                    (
                        i
                        for i in range(len(self.batch.buyers))
                        if not self.buyers.isRowHidden(i)
                    ),
                    -1,
                )
                if first >= 0:
                    self.buyers.setCurrentCell(first, 0)
                    self._select_buyer(first)
                else:
                    self.buyers.clearSelection()
                    self._select_buyer(-1)
            elif row != self._buyer_index:
                self._select_buyer(row)
            self.next_buyer.setEnabled(
                any(
                    not self.buyers.isRowHidden(i)
                    for i in range(self._buyer_index + 1, len(self.batch.buyers))
                )
            )

    def _buyer(self):
        return (
            self.batch.buyers[self._buyer_index]
            if self.batch and 0 <= self._buyer_index < len(self.batch.buyers)
            else None
        )

    def _package(self):
        buyer = self._buyer()
        return (
            buyer.packages[self._package_index]
            if buyer and 0 <= self._package_index < len(buyer.packages)
            else None
        )

    def _select_buyer(self, row, *_args):
        if row != self._buyer_index:
            self.edit_address.setChecked(False)
        self._buyer_index = row
        self._package_index = 0
        self._fill_editor()

    def _fill_editor(self):
        buyer = self._buyer()
        self.editor.setEnabled(buyer is not None)
        self.next_buyer.setEnabled(
            self.batch is not None
            and any(
                not self.buyers.isRowHidden(row)
                for row in range(self._buyer_index + 1, len(self.batch.buyers))
            )
        )
        if buyer is None:
            filtered = bool(self.batch and self.batch.buyers)
            self.ready_next.setEnabled(False)
            self.buyer_title.setText(
                "No buyers match" if filtered else "Select a buyer"
            )
            self.buyer_meta.setText(
                "Change the search or filter to see more buyers." if filtered else ""
            )
            self.buyer_status.hide()
            self.address_summary.clear()
            self.lots.clear()
            self.validation.clear()
            return
        self._quiet = True
        try:
            self._fill_header(buyer)
            self.remove_box.setVisible(len(buyer.packages) > 1)
            self.pickup.setChecked(buyer.pickup)
            exported = any(p.exported_at for p in buyer.packages)
            self.pickup.setEnabled(not exported)
            self.edit_address.setEnabled(not exported)
            self._address_summary()
            for key, edit in self.address.items():
                edit.setText(getattr(buyer, key))
                edit.setReadOnly(exported)
            self.packages.clear()
            for i, p in enumerate(buyer.packages):
                self.packages.addItem(f"Box {i + 1} · {self._status(buyer, p)}")
            self._package_index = min(self._package_index, len(buyer.packages) - 1)
            self.packages.setCurrentIndex(self._package_index)
        finally:
            self._quiet = False
        self._fill_package()

    def _address_summary(self):
        buyer = self._buyer()
        if buyer:
            self.address_summary.setText(
                "\n".join(
                    line
                    for line in (
                        buyer.name,
                        buyer.address1,
                        buyer.address2,
                        f"{buyer.city}, {buyer.state} {buyer.zip}",
                        buyer.country,
                        buyer.email,
                    )
                    if line
                )
            )

    def _select_package(self, index):
        if not self._quiet and index >= 0:
            self._package_index = index
            self._fill_package()

    def _fill_package(self):
        buyer, package = self._buyer(), self._package()
        if not buyer or not package:
            return
        self._quiet = True
        try:
            self.lots.clear()
            locked_lots = {
                lot for p in buyer.packages if p.exported_at for lot in p.lots
            }
            for lot, title in buyer.lots.items():
                item = QListWidgetItem(f"{lot}  {title}")
                item.setData(Qt.ItemDataRole.UserRole, lot)
                if len(buyer.packages) > 1:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if lot in package.lots
                        else Qt.CheckState.Unchecked
                    )
                if lot in locked_lots or buyer.pickup or package.exported_at:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self.lots.addItem(item)
            self.lots_label.setText(
                "Items in this box · select an item to move it here"
                if len(buyer.packages) > 1
                else "Items in this shipment"
            )
            for key, edit in self.measurements.items():
                value = (
                    package.weight_oz / 16
                    if key == "weight_lb"
                    else getattr(package, key)
                )
                edit.setText(format(value, ".10g") if value else "")
                edit.setEnabled(not buyer.pickup and not package.exported_at)
            self.add_box.setEnabled(
                not buyer.pickup and any(not p.exported_at for p in buyer.packages)
            )
            self.remove_box.setEnabled(
                not buyer.pickup and not package.exported_at and len(buyer.packages) > 1
            )
        finally:
            self._quiet = False
        self._validation()

    def _fill_header(self, buyer):
        boxes = len(buyer.packages)
        self.buyer_title.setText(buyer.name or "Unnamed buyer")
        self.buyer_meta.setText(
            " · ".join(
                part
                for part in (
                    f"Bidder {buyer.id}",
                    strings.count(len(buyer.lots), "lot"),
                    f"{boxes} {'box' if boxes == 1 else 'boxes'}",
                    buyer.email,
                )
                if part
            )
        )
        text, state = self._buyer_state(buyer)
        self.buyer_status.setText(text)
        self._set_state(self.buyer_status, state)
        self.buyer_status.show()

    def _validation(self):
        buyer, package = self._buyer(), self._package()
        if not buyer or not package:
            return
        if package.exported_at:
            text, state = f"Exported to {package.exported_file}", "done"
        elif buyer.pickup:
            text, state = (
                "Local pickup. This buyer is left out of the export.",
                "neutral",
            )
        else:
            errors = shipping.problems(buyer, package)
            if errors:
                # A box that just hasn't been measured yet is the next to-do,
                # not an error; only real address/lot problems are shown in red.
                measuring_only = errors == [
                    "Enter a positive weight and all three dimensions."
                ]
                text = "\n".join(errors)
                state = "neutral" if measuring_only else "error"
            elif package.packed:
                text, state = "✓ Ready to export.", "ok"
            else:
                text, state = (
                    "Measurements complete. Mark this box ready to continue.",
                    "neutral",
                )
        self.validation.setText(text)
        self._set_state(self.validation, state)
        self.ready_next.setEnabled(
            not buyer.pickup
            and not package.exported_at
            and not shipping.problems(buyer, package)
        )

    def _changed(self):
        if self._quiet:
            return
        self.dirty = True
        self._save_timer.start(500)
        self.notice.setText("Saving progress…")
        self._buyer_row(self._buyer_index)
        buyer = self._buyer()
        self._fill_header(buyer)
        for i, package in enumerate(buyer.packages):
            if i < self.packages.count():
                self.packages.setItemText(
                    i, f"Box {i + 1} · {self._status(buyer, package)}"
                )
        self._update_summary()
        self._validation()

    def _address_changed(self):
        if self._quiet or not (buyer := self._buyer()):
            return
        for key, edit in self.address.items():
            setattr(
                buyer,
                key,
                edit.text().strip().upper()
                if key == "country"
                else edit.text().strip(),
            )
        self._address_summary()
        for package in buyer.packages:
            if not package.exported_at:
                package.packed = False
        self._changed()

    def _pickup_changed(self, value):
        if self._quiet or not (buyer := self._buyer()):
            return
        buyer.pickup = value
        self._changed()
        self._fill_editor()

    def _measurement_changed(self, key, text):
        if self._quiet or not (package := self._package()):
            return
        # Preserve other saved values exactly while this field is being typed.
        # Empty/intermediate input clears this measurement, never reuses stale
        # data or becomes a negative/nonfinite value in the saved plan.
        value = float(text) if self.measurements[key].hasAcceptableInput() else 0
        setattr(
            package,
            "weight_oz" if key == "weight_lb" else key,
            value * 16 if key == "weight_lb" else value,
        )
        package.packed = False
        self._changed()

    def _lot_changed(self, item):
        if self._quiet:
            return
        buyer, package = self._buyer(), self._package()
        lot = item.data(Qt.ItemDataRole.UserRole)
        # All changes are moves, so a lot cannot quietly disappear from a plan.
        if item.checkState() == Qt.CheckState.Checked:
            for box in buyer.packages:
                if lot in box.lots:
                    box.lots.remove(lot)
                    box.packed = False
            package.lots.append(lot)
            package.packed = False
            self._changed()
        else:
            self.notice.setText(
                "To move this lot, select another box and check it there."
            )
        self._fill_editor()

    def add_package(self):
        buyer = self._buyer()
        if buyer:
            buyer.packages.append(shipping.Package())
            self._package_index = len(buyer.packages) - 1
            self._changed()
            self._fill_editor()

    def remove_package(self):
        buyer, package = self._buyer(), self._package()
        if not buyer or not package or package.exported_at or len(buyer.packages) < 2:
            return
        target = next(
            (p for p in buyer.packages if p is not package and not p.exported_at), None
        )
        if target is None:
            self._error(
                "This box cannot be removed: the other boxes have already been exported."
            )
            return
        target.lots.extend(package.lots)
        target.packed = False
        buyer.packages.remove(package)
        self._package_index = buyer.packages.index(target)
        self._changed()
        self._fill_editor()

    def _update_summary(self):
        count = len(self._ready())
        pending = self._pending_export_path()
        recoverable = pending is not None and pending.exists()
        self.export_button.setEnabled(count > 0 or recoverable)
        self.export_footer.setVisible(self.batch is not None)
        self.queue_count.setText(str(len(self.batch.buyers)) if self.batch else "0")
        unit = "box" if count == 1 else "boxes"
        self.export_button.setText(
            f"Export {count} {unit}…" if count else "Export to Pirate Ship…"
        )
        if recoverable:
            self.export_button.setText("Recover CSV download…")
        self.batch_bar.setVisible(self.batch is not None or self.batches.count() > 1)
        self.workspace.setCurrentIndex(1 if self.batch else 0)
        last_export = self._last_export()
        self.export_result.setVisible(last_export is not None)
        if last_export:
            self.export_message.setText(
                (
                    "CSV available from the shared database. Use Download CSV again to save a copy on this computer."
                    if self.shared
                    else f"CSV ready: {last_export.exported_file}"
                )
                + "\nIn Pirate Ship, choose Upload a Spreadsheet and select the CSV before buying labels."
            )
        shippable = (
            [p for b in self.batch.buyers if not b.pickup for p in b.packages]
            if self.batch
            else []
        )
        exported = sum(bool(p.exported_at) for p in shippable)
        if not self.batch:
            steps = ("active", "todo", "todo")
        elif shippable and exported == len(shippable):
            steps = ("done", "done", "done")
        elif count:
            steps = ("done", "done", "active")
        else:
            steps = ("done", "active", "todo")
        for step, state in zip(self.steps, steps, strict=True):
            self._set_state(step, state)
        self.progress.setMaximum(max(1, len(shippable)))
        self.progress.setValue(exported + count)
        self.progress_label.setText(
            f"{exported + count} of {strings.count(len(shippable), 'shipment')} "
            "ready or exported"
        )
        if self.batch:
            pickup = sum(b.pickup for b in self.batch.buyers)
            self.summary.setText(
                f"{strings.count(len(self.batch.buyers), 'buyer')} · "
                f"{count} ready to export · {exported} exported · "
                f"{strings.count(pickup, 'local pickup')}"
            )
        else:
            self.summary.clear()

    def flush(self, *, warn=True) -> bool:
        if self.busy:
            return False
        if not self.dirty:
            return True
        self._save_timer.stop()
        try:
            saved = self._io(
                "Saving shipping progress…",
                lambda: self._save_batch(self.path, self.batch, self._shared_base),
            )
        except (OSError, shipping.ShippingError) as e:
            self.notice.setText(f"Progress was not saved: {e}")
            if warn:
                self._error(e)
            return False
        if self.shared:
            self.batch = saved
            self._shared_base = network.batch_data(saved)
            for row in range(len(saved.buyers)):
                self._buyer_row(row)
            self._update_summary()
        self.dirty = False
        self.notice.setText(
            "Synced with host." if self.shared else "All changes saved."
        )
        return True

    def export_report(self):
        if not self.flush() or not self.batch:
            return
        ready = len(self._ready())
        pending = self._pending_export_path()
        if not ready and not (pending and pending.exists()):
            return
        name, _ = QFileDialog.getSaveFileName(
            self,
            f"Save Pirate Ship CSV · {ready} shipments",
            f"pirate-ship-{datetime.now(UTC):%Y%m%d-%H%M%S}.csv",
            "CSV spreadsheet (*.csv)",
        )
        if not name:
            return
        output = Path(name)
        if output.suffix.lower() != ".csv":
            output = output.with_suffix(".csv")
        try:
            batch = self._io(
                "Exporting packages…",
                lambda: self._export_batch(output, True),
            )
        except (OSError, shipping.ShippingError) as e:
            self._error(e)
            return
        self.batch = batch
        self._shared_base = network.batch_data(batch) if self.shared else None
        self._fill_editor()
        for row in range(len(batch.buyers)):
            self._buyer_row(row)
        self._update_summary()
        self._filter()
        self.notice.setText(f"CSV saved to {output.name}.")

    def set_connection(self, client, shared):
        self.client, self.shared = client, shared
        self._shared_base = None
        self._loaded = False
        self.batch = None
        self.path = None
        self._fill_buyers()
        self.show_export.setText(
            "Download CSV again" if shared else "Open export folder"
        )

    def _load_batch(self, path):
        if self.shared:
            if self.client is None:
                raise network.NetworkError("The host is unavailable; check Settings.")
            return network.as_batch(self.client.request("get_shipping", key=path))
        return shipping.load_batch(path)

    def _save_batch(self, path, batch, expected):
        if self.shared:
            if self.client is None:
                raise network.NetworkError("The host is unavailable; check Settings.")
            result = self.client.request(
                "save_shipping",
                key=path,
                batch=network.batch_data(batch),
                expected=expected,
            )
            return network.as_batch(result)
        shipping.save_batch(path, batch)
        return batch

    def _export_batch(self, output, measurements):
        if not self.shared:
            return shipping.export_batch(
                self.batch, self.path, output, include_measurements=measurements
            )
        if output.exists():
            raise shipping.ShippingError(
                "Choose a new CSV filename so previous exports are preserved."
            )
        # Keep the request identity on disk before sending. A lost response or
        # failed local download can be retried, even after restarting the app.
        pending_path = self._pending_export_path()
        if pending_path.exists():
            pending = json.loads(pending_path.read_bytes())
        else:
            pending = {
                "id": uuid4().hex,
                "expected": network.batch_data(self.batch),
                "measurements": measurements,
            }
            storage.atomic_write(pending_path, json.dumps(pending).encode())
        try:
            result = self.client.request("export_shipping", key=self.path, **pending)
        except network.Conflict:
            pending_path.unlink(missing_ok=True)
            raise
        raw = base64.b64decode(result["csv"], validate=True)
        try:
            storage.atomic_write(output, raw)
        except OSError as e:
            raise shipping.ShippingError(
                f"The host saved this export, but this computer could not save the CSV: {e}. Reconnect and use Download CSV again to recover it."
            ) from e
        pending_path.unlink(missing_ok=True)
        return network.as_batch(result["batch"])

    def download_export(self, reference):
        if not reference.startswith("shared:"):
            self._error(
                "This export was made before sharing was enabled. Its file remains on the computer that exported it."
            )
            return
        name, _ = QFileDialog.getSaveFileName(
            self, "Download Pirate Ship CSV", "pirate-ship.csv", "CSV (*.csv)"
        )
        if not name:
            return
        output = Path(name)
        if output.suffix.lower() != ".csv":
            output = output.with_suffix(".csv")
        try:
            if output.exists():
                raise shipping.ShippingError(
                    "Choose a new filename to preserve previous exports."
                )
            raw = self._io(
                "Downloading CSV…",
                lambda: self.client.request(
                    "download_export", id=reference.removeprefix("shared:")
                ),
            )
            storage.atomic_write(output, base64.b64decode(raw, validate=True))
            pending = (
                self.folder
                / "shared-export-pending"
                / self.client.identity
                / (self.path + ".json")
            )
            if pending.exists() and json.loads(pending.read_bytes())[
                "id"
            ] == reference.removeprefix("shared:"):
                pending.unlink()
            self.notice.setText(f"CSV saved to {output}.")
        except (OSError, ValueError, shipping.ShippingError) as e:
            self._error(e)

    def sync_snapshot(self, choices, batch_data):
        if self.dirty or self.busy:
            return
        if self.shared:
            selected = self.path
            with QSignalBlocker(self.batches):
                self.batches.clear()
                self.batches.addItem("Choose an auction…", None)
                for key, auction in sorted(choices.items(), key=lambda v: v[1]):
                    self.batches.addItem(auction, key)
                self.batches.setCurrentIndex(max(0, self.batches.findData(selected)))
            if batch_data and batch_data != self._shared_base:
                buyer = self._buyer().id if self._buyer() else None
                package = self._package().id if self._package() else None
                self.batch = network.as_batch(batch_data)
                self._shared_base = deepcopy(batch_data)
                self._fill_buyers()
                for row, item in enumerate(self.batch.buyers):
                    if item.id == buyer:
                        self.buyers.setCurrentCell(row, 0)
                        self._package_index = next(
                            (i for i, p in enumerate(item.packages) if p.id == package),
                            0,
                        )
                        self._fill_editor()
                        break
                self.notice.setText("Synced with host.")
            self._update_summary()

    def _pending_export_path(self):
        if self.shared and self.client and self.path:
            return (
                self.folder
                / "shared-export-pending"
                / self.client.identity
                / (self.path + ".json")
            )
        return None
