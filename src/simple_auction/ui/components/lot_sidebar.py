from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from simple_auction import models
from simple_auction.ui import strings, theme

AUCTION_ROLE = Qt.ItemDataRole.UserRole
LOT_ROLE = Qt.ItemDataRole.UserRole + 1
COUNT_ROLE = Qt.ItemDataRole.UserRole + 2
TITLE_ROLE = Qt.ItemDataRole.UserRole + 3
MISSING_ROLE = Qt.ItemDataRole.UserRole + 4  # what the lot still needs

# One selected entry: (auction_no, lot_number), lot_number is None for an auction.
Selection = tuple[int, int | None]


def missing_fields(lot: models.Lot) -> list[str]:
    """What a lot still needs before it's ready to list."""
    return [
        label
        for label, value in (
            (strings.TITLE, lot.title),
            (strings.CONDITION, lot.condition),
        )
        if not value.strip()
    ]


class LotSidebar(QFrame):
    new_auction = Signal()
    new_lot = Signal(int)  # auction_no
    lot_selected = Signal(int, int)  # auction_no, lot_number
    export_auction = Signal(int)  # auction_no
    delete_requested = Signal(list)  # list[Selection]
    import_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setMinimumWidth(theme.SIDEBAR_MIN_WIDTH)
        self.setMaximumWidth(theme.SIDEBAR_MAX_WIDTH)
        self._quiet = False

        create = QPushButton(strings.CREATE_NEW)
        create.setObjectName("primary")
        create.setToolTip(strings.CREATE_NEW_TIP)
        theme.set_icon(create, "plus", "accent_text")
        create.clicked.connect(self.new_auction)
        import_btn = QPushButton()
        import_btn.setObjectName("iconButton")
        import_btn.setToolTip(strings.IMPORT_BTN)
        import_btn.setAccessibleName(strings.IMPORT_BTN)
        theme.set_icon(import_btn, "import")
        import_btn.clicked.connect(self.import_requested)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.addWidget(create, 1)
        actions.addWidget(import_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText(strings.SIDEBAR_SEARCH)
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(strings.SIDEBAR_SEARCH)
        theme.set_icon(self.search, "search")
        self.search.textChanged.connect(self._filter)

        section = QLabel(strings.AUCTIONS_SECTION)
        section.setObjectName("sectionLabel")

        self.tree = QTreeWidget()
        self.tree.setObjectName("lotTree")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setMouseTracking(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Keyboard users can Tab into the list and move with the arrow keys.
        self.tree.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.delegate = _TreeDelegate(self.tree)
        self.delegate.add_clicked.connect(self.new_lot)
        self.tree.setItemDelegate(self.delegate)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_menu)
        for key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            shortcut = QShortcut(QKeySequence(key), self.tree)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(self._delete_selected)
        # Return/Enter/Space open or close the focused auction.
        self.tree.installEventFilter(self)

        self.empty_hint = QLabel(strings.SIDEBAR_EMPTY)
        self.empty_hint.setObjectName("sidebarEmpty")
        self.empty_hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(0)
        layout.addLayout(actions)
        layout.addSpacing(10)
        layout.addWidget(self.search)
        layout.addSpacing(16)
        layout.addWidget(section)
        layout.addSpacing(6)
        layout.addWidget(self.empty_hint)
        layout.addWidget(self.tree, 1)

    # -- public -------------------------------------------------------------

    def populate(self, auctions: dict[int, list[models.Lot]]) -> None:
        first_load = self.tree.topLevelItemCount() == 0
        expanded = {
            item.data(0, AUCTION_ROLE)
            for item in self._auction_items()
            if item.isExpanded()
        }
        self._quiet = True
        self.tree.clear()
        numbers = sorted(auctions)
        for auction_no in numbers:
            lots = auctions[auction_no]
            parent = QTreeWidgetItem(self.tree, [str(auction_no)])
            parent.setData(0, AUCTION_ROLE, auction_no)
            parent.setData(0, COUNT_ROLE, len(lots))
            for lot in lots:
                child = QTreeWidgetItem(parent, [str(lot.lot_number)])
                child.setData(0, AUCTION_ROLE, auction_no)
                child.setData(0, LOT_ROLE, lot.lot_number)
                child.setData(0, TITLE_ROLE, lot.title)
                child.setData(0, MISSING_ROLE, missing_fields(lot))
            keep = auction_no in expanded or (first_load and auction_no == numbers[-1])
            parent.setExpanded(keep)
        self._quiet = False
        self._filter()

    def select(self, auction_no: int, lot_number: int) -> None:
        """Select one lot without re-emitting lot_selected."""
        child = self._lot_item(auction_no, lot_number)
        if child is None:
            return
        child.parent().setExpanded(True)
        self._quiet = True
        self.tree.setCurrentItem(child)
        self.tree.scrollToItem(child)
        self._quiet = False

    def update_lot(self, auction_no: int, lot: models.Lot) -> None:
        """Update one lot's row in place (keeps selection and scroll)."""
        child = self._lot_item(auction_no, lot.lot_number)
        if child is not None:
            child.setData(0, TITLE_ROLE, lot.title)
            child.setData(0, MISSING_ROLE, missing_fields(lot))

    def neighbor(self, auction_no: int, lot_number: int, step: int) -> int | None:
        """The lot `step` places away within the same auction, if any."""
        child = self._lot_item(auction_no, lot_number)
        if child is None:
            return None
        parent = child.parent()
        index = parent.indexOfChild(child) + step
        if 0 <= index < parent.childCount():
            return parent.child(index).data(0, LOT_ROLE)
        return None

    # -- internals ----------------------------------------------------------

    def _auction_items(self) -> list[QTreeWidgetItem]:
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def _lot_item(self, auction_no: int, lot_number: int) -> QTreeWidgetItem | None:
        for parent in self._auction_items():
            if parent.data(0, AUCTION_ROLE) != auction_no:
                continue
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.data(0, LOT_ROLE) == lot_number:
                    return child
        return None

    def _filter(self, *_args) -> None:
        """Hide lots and auctions that don't match the search box."""
        query = self.search.text().strip().casefold()
        any_visible = False
        for parent in self._auction_items():
            auction_match = (
                not query
                or query
                in strings.AUCTION_ROW.format(n=parent.data(0, AUCTION_ROLE)).casefold()
            )
            lot_match = False
            for j in range(parent.childCount()):
                child = parent.child(j)
                text = f"{child.data(0, LOT_ROLE)} {child.data(0, TITLE_ROLE) or ''}"
                matches = not query or query in text.casefold()
                child.setHidden(not (matches or auction_match))
                lot_match |= matches and bool(query)
            parent.setHidden(not (auction_match or lot_match))
            if lot_match:
                parent.setExpanded(True)
            any_visible |= not parent.isHidden()
        has_auctions = self.tree.topLevelItemCount() > 0
        self.empty_hint.setText(
            strings.SIDEBAR_NO_MATCH if has_auctions else strings.SIDEBAR_EMPTY
        )
        self.empty_hint.setVisible(not any_visible)

    # -- internals ----------------------------------------------------------

    def _auction_items(self) -> list[QTreeWidgetItem]:
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def _selection(self) -> list[Selection]:
        return [
            (item.data(0, AUCTION_ROLE), item.data(0, LOT_ROLE))
            for item in self.tree.selectedItems()
        ]

    def _on_selection_changed(self) -> None:
        if self._quiet:
            return
        selected = self._selection()
        if len(selected) == 1 and selected[0][1] is not None:
            self.lot_selected.emit(*selected[0])

    def _on_clicked(self, item: QTreeWidgetItem) -> None:
        plain = QApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier
        if item.data(0, LOT_ROLE) is None and plain:
            item.setExpanded(not item.isExpanded())

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self.tree
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            item = self.tree.currentItem()
            if item is not None and item.data(0, LOT_ROLE) is None:
                item.setExpanded(not item.isExpanded())
                return True
        return super().eventFilter(watched, event)

    def _show_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.tree.setCurrentItem(item)
        selected = self._selection()
        menu = QMenu(self)
        auctions = {auction_no for auction_no, _lot in selected}
        if len(auctions) == 1:
            auction_no = auctions.pop()
            new_lot = menu.addAction(
                strings.NEW_LOT, lambda: self.new_lot.emit(auction_no)
            )
            theme.set_icon(new_lot, "plus")
            export = menu.addAction(
                strings.EXPORT_AUCTION, lambda: self.export_auction.emit(auction_no)
            )
            theme.set_icon(export, "export")
            menu.addSeparator()
        label = (
            strings.DELETE
            if len(selected) == 1
            else strings.DELETE_N.format(n=len(selected))
        )
        delete = menu.addAction(label, lambda: self.delete_requested.emit(selected))
        theme.set_icon(delete, "trash")
        menu.exec(self.tree.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _delete_selected(self) -> None:
        selected = self._selection()
        if selected:
            self.delete_requested.emit(selected)


class _TreeDelegate(QStyledItemDelegate):
    """Paints the sidebar rows and the per-auction "+" button."""

    add_clicked = Signal(int)  # auction_no

    PLUS = 22
    DOT = 7
    LOT_INDENT = 30

    def __init__(self, tree: QTreeWidget) -> None:
        super().__init__(tree)
        self.tree = tree

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), theme.TREE_ROW_HEIGHT)

    def _plus_rect(self, row: QRect) -> QRect:
        return QRect(
            row.right() - self.PLUS - 4,
            row.center().y() - self.PLUS // 2 + 1,
            self.PLUS,
            self.PLUS,
        )

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        c = theme.colors()
        is_auction = index.data(LOT_ROLE) is None
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        row = option.rect.adjusted(0, 1, 0, -1)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if selected:
            painter.setBrush(QColor(c.accent_soft))
            painter.drawRoundedRect(row, 6, 6)
            # A short accent bar marks the open row, readable at a glance.
            painter.setBrush(QColor(c.accent))
            painter.drawRoundedRect(
                QRect(row.left() + 3, row.top() + 7, 3, row.height() - 14), 1.5, 1.5
            )
        elif hovered:
            painter.setBrush(QColor(c.hover))
            painter.drawRoundedRect(row, 6, 6)

        font = QFont(option.font)
        if is_auction:
            self._paint_chevron(painter, row, self.tree.isExpanded(index), c.muted)
            count = str(index.data(COUNT_ROLE) or 0)
            painter.setFont(font)
            count_width = painter.fontMetrics().horizontalAdvance(count) + 4
            count_rect = QRect(
                self._plus_rect(row).left() - 8 - count_width,
                row.top(),
                count_width,
                row.height(),
            )
            painter.setPen(QColor(c.muted))
            painter.drawText(
                count_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                count,
            )
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(c.text))
            text_rect = QRect(
                row.left() + 26,
                row.top(),
                count_rect.left() - 8 - (row.left() + 26),
                row.height(),
            )
            label = painter.fontMetrics().elidedText(
                strings.AUCTION_ROW.format(n=index.data(AUCTION_ROLE)),
                Qt.TextElideMode.ElideRight,
                text_rect.width(),
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, label)
            self._paint_plus(painter, row, c)
        else:
            lot_text = str(index.data(LOT_ROLE))
            painter.setFont(font)
            painter.setPen(QColor(c.muted))
            x = row.left() + self.LOT_INDENT
            number_width = painter.fontMetrics().horizontalAdvance(lot_text) + 10
            number_rect = QRect(x, row.top(), number_width, row.height())
            painter.drawText(number_rect, Qt.AlignmentFlag.AlignVCenter, lot_text)
            missing = index.data(MISSING_ROLE) or []
            right = row.right() - (self.DOT + 14 if missing else 8)
            title_rect = QRect(
                number_rect.right() + 6,
                row.top(),
                right - number_rect.right() - 6,
                row.height(),
            )
            title = index.data(TITLE_ROLE)
            if title:
                if selected:
                    font.setWeight(QFont.Weight.DemiBold)
                    painter.setFont(font)
                painter.setPen(QColor(c.text))
            else:
                title = strings.UNTITLED
                font.setItalic(True)
                painter.setFont(font)
                painter.setPen(QColor(c.muted))
            elided = painter.fontMetrics().elidedText(
                title, Qt.TextElideMode.ElideRight, title_rect.width()
            )
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter, elided)
            if missing:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(c.warning))
                painter.drawEllipse(
                    QRect(
                        row.right() - self.DOT - 10,
                        row.center().y() - self.DOT // 2 + 1,
                        self.DOT,
                        self.DOT,
                    )
                )
        painter.restore()

    def _paint_chevron(
        self, painter: QPainter, row: QRect, expanded: bool, color: str
    ) -> None:
        cx, cy = row.left() + 13, row.center().y() + 1
        path = QPainterPath()
        if expanded:
            path.moveTo(cx - 4, cy - 2)
            path.lineTo(cx, cy + 2)
            path.lineTo(cx + 4, cy - 2)
        else:
            path.moveTo(cx - 2, cy - 4)
            path.lineTo(cx + 2, cy)
            path.lineTo(cx - 2, cy + 4)
        pen = QPen(QColor(color), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _paint_plus(self, painter: QPainter, row: QRect, c: theme.Colors) -> None:
        rect = self._plus_rect(row)
        mouse = self.tree.viewport().mapFromGlobal(QCursor.pos())
        hot = rect.contains(mouse)
        if hot:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.accent))
            painter.drawRoundedRect(rect, 5, 5)
        pen = QPen(QColor(c.accent_text if hot else c.muted), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        center = rect.center()
        painter.drawLine(center.x() - 4, center.y(), center.x() + 4, center.y())
        painter.drawLine(center.x(), center.y() - 4, center.x(), center.y() + 4)

    def editorEvent(self, event, model, option, index) -> bool:
        if index.data(LOT_ROLE) is not None:
            return False
        if event.type() == QEvent.Type.MouseMove:
            self.tree.viewport().update(option.rect)
            return False
        if event.type() not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        ):
            return False
        if not self._plus_rect(option.rect).contains(event.position().toPoint()):
            return False
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            auction_no = index.data(AUCTION_ROLE)
            # Deferred: the handler rebuilds this tree.
            QTimer.singleShot(0, lambda: self.add_clicked.emit(auction_no))
        return True

    def helpEvent(self, event, view, option, index) -> bool:
        if index.data(LOT_ROLE) is None:
            if self._plus_rect(option.rect).contains(event.pos()):
                QToolTip.showText(event.globalPos(), strings.ADD_LOT_TIP, view)
                return True
            return super().helpEvent(event, view, option, index)
        # Lot rows: the full title (it's often cut off) and what's missing.
        lines = [index.data(TITLE_ROLE) or strings.UNTITLED]
        if missing := index.data(MISSING_ROLE):
            lines.append(strings.INCOMPLETE_TIP.format(fields=", ".join(missing)))
        QToolTip.showText(event.globalPos(), "\n".join(lines), view)
        return True
