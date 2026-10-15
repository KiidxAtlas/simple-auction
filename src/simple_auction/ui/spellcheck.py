"""Opt-out, offline spelling adapters; never replace the application's editors.

All offsets crossing into Qt are UTF-16 offsets. The spelling service deliberately
uses Python offsets instead, so conversion belongs at this UI boundary.
"""

from bisect import bisect_right

from PySide6.QtCore import QEvent, QObject, QPointF, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QPainter,
    QPolygonF,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextLayout,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QStyle,
    QStyleOptionFrame,
    QTextEdit,
    QWidget,
)
from shiboken6 import isValid

from ..services.spelling import Spelling, word_spans

_EDITORS = (QLineEdit, QPlainTextEdit, QTextEdit)


def _utf16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _python_offset(text: str, offset: int) -> int:
    total = 0
    for index, char in enumerate(text):
        total += _utf16(char)
        if total > offset:
            return index
    return len(text)


def _enabled(widget) -> bool:
    if widget.property("spellcheck") is False or widget.isReadOnly():
        return False
    if isinstance(widget, QLineEdit):
        return (
            widget.echoMode() == QLineEdit.EchoMode.Normal
            and widget.validator() is None
            and not widget.inputMask()
            and not isinstance(widget.parentWidget(), QAbstractSpinBox)
        )
    return True


def _text(widget) -> str:
    return widget.text() if isinstance(widget, QLineEdit) else widget.toPlainText()


class _Highlighter(QSyntaxHighlighter):
    def __init__(self, adapter):
        super().__init__(adapter.widget.document())
        self.adapter = adapter
        self.error_format = QTextCharFormat()
        self.error_format.setUnderlineColor(QColor("#d32f2f"))
        self.error_format.setUnderlineStyle(
            QTextCharFormat.UnderlineStyle.SpellCheckUnderline
        )

    def highlightBlock(self, text):
        if not _enabled(self.adapter.widget):
            return
        start = self.currentBlock().position()
        end = start + _utf16(text)
        spans = self.adapter.qt_spans
        index = max(0, bisect_right(spans, (start, float("inf"))) - 1)
        for left, right in spans[index:]:
            if left >= end:
                break
            if right > start:
                self.setFormat(
                    max(left, start) - start,
                    min(right, end) - max(left, start),
                    self.error_format,
                )


class _LineOverlay(QWidget):
    """Paint only decoration, anchored to Qt's actual scrolled cursor geometry."""

    def __init__(self, adapter):
        super().__init__(adapter.widget)
        self.adapter = adapter
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(adapter.widget.rect())
        self.show()

    def paintEvent(self, event):
        widget = self.adapter.widget
        if not _enabled(widget) or not self.adapter.qt_spans:
            return
        option = QStyleOptionFrame()
        widget.initStyleOption(option)
        clip = widget.style().subElementRect(
            QStyle.SubElement.SE_LineEditContents, option, widget
        )
        margins = widget.textMargins()
        clip.adjust(
            margins.left() + 2, margins.top(), -margins.right() - 2, -margins.bottom()
        )
        layout = QTextLayout(widget.text(), widget.font())
        text_option = layout.textOption()
        text_option.setTextDirection(widget.layoutDirection())
        layout.setTextOption(text_option)
        layout.beginLayout()
        line = layout.createLine()
        layout.endLayout()
        if not line.isValid():
            return
        cursor = widget.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)
        # QLineEdit exposes a wide cursor *damage* rectangle (usually 10px),
        # whose horizontal midpoint is the caret, not its left edge.
        caret_x = cursor.x() + cursor.width() / 2
        origin = caret_x - line.cursorToX(widget.cursorPosition())[0]
        y = min(cursor.bottom() - 1, clip.bottom() - 1)
        painter = QPainter(self)
        painter.setClipRect(clip)
        painter.setPen(QColor("#d32f2f"))
        for start, end in self.adapter.qt_spans:
            x1 = origin + line.cursorToX(start)[0]
            x2 = origin + line.cursorToX(end)[0]
            left, right = sorted((x1, x2))
            left, right = max(left, clip.left()), min(right, clip.right())
            if right <= left:
                continue
            points = QPolygonF()
            x = left
            while x <= right:
                points.append(QPointF(x, y + (1 if int(x - left) % 4 < 2 else -1)))
                x += 1
            painter.drawPolyline(points)


class _Adapter(QObject):
    def __init__(self, manager, widget):
        super().__init__(manager)
        self.manager = manager
        self.widget = widget
        widget.destroyed.connect(self.deleteLater)
        self.qt_spans = []
        self._generation = 0
        self._painting = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._begin)
        self.highlighter = None
        self.overlay = None
        if isinstance(widget, QLineEdit):
            self.overlay = _LineOverlay(self)
            self.destroyed.connect(self.overlay.deleteLater)
            widget.cursorPositionChanged.connect(self.overlay.update)
            widget.selectionChanged.connect(self.overlay.update)
        else:
            self.highlighter = _Highlighter(self)
            self.highlighter.setParent(self)
            highlighter = self.highlighter

            def detach():
                # Removing highlight formats during teardown also emits
                # textChanged unless the still-live editor is blocked.
                if isValid(widget) and isValid(highlighter):
                    with QSignalBlocker(widget):
                        highlighter.setDocument(None)

            self.destroyed.connect(detach)
        widget.textChanged.connect(self.schedule)
        self.schedule()

    def schedule(self):
        if not isValid(self.widget):
            return
        if self._painting:
            return
        self._generation += 1
        # Clear stale ranges immediately, without touching the undo stack.
        self.qt_spans = []
        self._paint()
        self.timer.start(180)

    def _paint(self):
        if self.overlay:
            self.overlay.update()
        if self.highlighter:
            self._painting = True
            try:
                # QSyntaxHighlighter can emit the editor's textChanged signal
                # for formatting alone. Never count decoration as a user edit.
                with QSignalBlocker(self.widget):
                    self.highlighter.rehighlight()
            finally:
                self._painting = False

    def _begin(self):
        if not _enabled(self.widget):
            return
        generation = self._generation
        text = _text(self.widget)
        words = iter(word_spans(text))
        spans = []
        offsets = [0]
        for char in text:
            offsets.append(offsets[-1] + _utf16(char))

        def batch():
            if not isValid(self) or not isValid(self.widget):
                return
            if generation != self._generation or not _enabled(self.widget):
                return
            for _ in range(80):
                try:
                    start, end, word = next(words)
                except StopIteration:
                    self.qt_spans = spans
                    self._paint()
                    return
                if not self.manager.checker.correct(word):
                    spans.append((offsets[start], offsets[end]))
            QTimer.singleShot(0, self, batch)

        batch()

    def menu(self, point):
        """Build on Qt's own edit menu, retaining all its actions and shortcuts."""
        widget = self.widget
        text = _text(widget)
        if isinstance(widget, QLineEdit):
            menu = widget.createStandardContextMenu()
            offset = _python_offset(text, widget.cursorPositionAt(point))
        else:
            menu = widget.createStandardContextMenu(point)
            offset = _python_offset(text, widget.cursorForPosition(point).position())
        token = next(
            (
                (start, end, word)
                for start, end, word in word_spans(text)
                if start <= offset < end
            ),
            None,
        )
        if not token or self.manager.checker.correct(token[2]):
            return menu
        start, end, word = token
        first = menu.actions()[0] if menu.actions() else None

        def insert(label, callback=None):
            action = QAction(label, menu)
            if callback:
                action.triggered.connect(callback)
            else:
                action.setEnabled(False)
            menu.insertAction(first, action)
            return action

        for suggestion in self.manager.checker.suggest(word):
            # QAction treats '&' as a mnemonic, not a literal character.
            insert(
                suggestion.replace("&", "&&"),
                lambda checked=False, value=suggestion: self.replace(
                    text, start, end, value
                ),
            )
        insert("Ignore for this session", lambda: self.learn(word, False))
        insert("Add to dictionary", lambda: self.learn(word, True))
        menu.insertSeparator(first)
        return menu

    def replace(self, original, start, end, replacement):
        widget = self.widget
        if not _enabled(widget) or _text(widget) != original:
            return
        left, right = _utf16(original[:start]), _utf16(original[:end])
        if isinstance(widget, QLineEdit):
            widget.setSelection(left, right - left)
            widget.insert(replacement)
        else:
            cursor = widget.textCursor()
            cursor.beginEditBlock()
            cursor.setPosition(left)
            cursor.setPosition(right, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(replacement)
            cursor.endEditBlock()
            widget.setTextCursor(cursor)

    def learn(self, word, permanent):
        try:
            if permanent:
                if self.manager.checker.add(word) is False:
                    raise OSError("The dictionary could not be saved.")
            else:
                self.manager.checker.ignore(word)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self.widget,
                "Spelling dictionary",
                f"Could not add the word to the dictionary.\n{error}",
            )
            return
        self.manager.refresh()


class SpellcheckManager(QObject):
    """Application-owned adapter registry; editable prose is enabled by default."""

    def __init__(self, app, checker=None):
        super().__init__(app)
        self.checker = checker if checker is not None else Spelling()
        self.adapters = {}
        self._revision = self.checker.revision
        app.installEventFilter(self)
        self._poll = QTimer(self)
        self._poll.setInterval(500)
        self._poll.timeout.connect(self._check_revision)
        self._poll.start()
        for widget in app.allWidgets():
            self.attach(widget)

    def attach(self, widget):
        if not isinstance(widget, _EDITORS) or not _enabled(widget):
            return None
        key = id(widget)
        if key not in self.adapters:
            self.adapters[key] = _Adapter(self, widget)
            widget.destroyed.connect(lambda: self.adapters.pop(key, None))
        return self.adapters[key]

    def refresh(self):
        self._revision = self.checker.revision
        for adapter in list(self.adapters.values()):
            adapter.schedule()

    def _check_revision(self):
        if self.checker.revision != self._revision:
            self.refresh()

    def eventFilter(self, obj, event):
        kind = event.type()
        # Global filters also see events from half-constructed Qt controls.
        # Never inspect their parent/viewport on constructor events.
        if kind not in (
            QEvent.Type.Show,
            QEvent.Type.FocusIn,
            QEvent.Type.ContextMenu,
            QEvent.Type.DynamicPropertyChange,
            QEvent.Type.ReadOnlyChange,
            QEvent.Type.EnabledChange,
            QEvent.Type.Resize,
            QEvent.Type.Paint,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
            QEvent.Type.LayoutDirectionChange,
        ):
            return False
        widget = obj
        if kind == QEvent.Type.ContextMenu and isinstance(obj, QWidget):
            parent = obj.parentWidget()
            if (
                isinstance(parent, (QPlainTextEdit, QTextEdit))
                and obj is parent.viewport()
            ):
                widget = parent
        if not isinstance(widget, _EDITORS):
            return False
        if kind in (QEvent.Type.Show, QEvent.Type.FocusIn):
            self.attach(widget)
        adapter = self.adapters.get(id(widget))
        if adapter is None:
            return False
        if kind == QEvent.Type.ContextMenu and _enabled(widget):
            point = event.pos()
            if event.reason() == event.Reason.Keyboard:
                if isinstance(widget, QLineEdit):
                    point = QPointF(
                        widget.inputMethodQuery(
                            Qt.InputMethodQuery.ImCursorRectangle
                        ).center()
                    ).toPoint()
                else:
                    point = widget.cursorRect().center()
            menu = adapter.menu(point)
            menu.exec(event.globalPos())
            menu.deleteLater()
            return True
        if kind in (
            QEvent.Type.DynamicPropertyChange,
            QEvent.Type.ReadOnlyChange,
            QEvent.Type.EnabledChange,
            QEvent.Type.FocusIn,
        ):
            adapter.schedule()
        if adapter.overlay and kind in (
            QEvent.Type.Resize,
            QEvent.Type.Paint,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
            QEvent.Type.LayoutDirectionChange,
        ):
            adapter.overlay.setGeometry(widget.rect())
            adapter.overlay.raise_()
            adapter.overlay.update()
        return False


def install_spellcheck(app: QApplication, checker=None) -> SpellcheckManager:
    """Install once after QApplication construction and retain on the app."""
    existing = getattr(app, "_spellcheck_manager", None)
    if existing is not None and isValid(existing):
        return existing
    manager = SpellcheckManager(app, checker)
    app._spellcheck_manager = manager
    return manager
