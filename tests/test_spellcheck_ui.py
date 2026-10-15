"""Exercise the real Qt adapters with an offline, deterministic dictionary."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QIntValidator, QTextCharFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QTextEdit,
)

from simple_auction.ui.spellcheck import SpellcheckManager


class Dictionary:
    def __init__(self):
        self.revision = 0
        self.accepted = set()
        self.suggestion_calls = []

    def correct(self, word):
        return word.casefold() != "wrng" or word.casefold() in self.accepted

    def suggest(self, word):
        self.suggestion_calls.append(word)
        return ["wrong", "wring"]

    def ignore(self, word):
        self.accepted.add(word.casefold())
        self.revision += 1

    def add(self, word):
        self.ignore(word)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(app):
    checker = Dictionary()
    manager = SpellcheckManager(app, checker)
    widgets = []

    def create(kind=QLineEdit, text="wrng"):
        widget = kind()
        widget.resize(260, 100 if kind is not QLineEdit else 32)
        if isinstance(widget, QLineEdit):
            widget.setText(text)
        else:
            widget.setPlainText(text)
        widgets.append(widget)
        widget.show()
        app.processEvents()
        return widget

    yield manager, checker, create
    for widget in widgets:
        widget.close()
        widget.deleteLater()
    manager.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def settle(app):
    QTest.qWait(240)
    app.processEvents()


def position(widget, offset):
    if isinstance(widget, QLineEdit):
        widget.setCursorPosition(offset)
        return widget.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle).center()
    cursor = widget.textCursor()
    cursor.setPosition(offset)
    widget.setTextCursor(cursor)
    return widget.cursorRect().center()


def formats(widget):
    return [
        format_range
        for block in blocks(widget)
        for format_range in block.layout().formats()
        if format_range.format.underlineStyle()
        == QTextCharFormat.UnderlineStyle.SpellCheckUnderline
    ]


def blocks(widget):
    block = widget.document().begin()
    while block.isValid():
        yield block
        block = block.next()


@pytest.mark.parametrize("kind", [QLineEdit, QPlainTextEdit, QTextEdit])
def test_clicked_word_replaced_with_one_undo_and_standard_actions_kept(
    app, setup, kind
):
    manager, checker, create = setup
    widget = create(kind, "😀 wrng, wrng!")
    settle(app)
    assert checker.suggestion_calls == []
    adapter = manager.adapters[id(widget)]
    menu = adapter.menu(
        position(widget, 10)
    )  # second word; Qt counts emoji as two units
    labels = [action.text().replace("&", "") for action in menu.actions()]
    assert "wrong" in labels
    assert any("Copy" in label for label in labels)
    assert any("Paste" in label for label in labels)
    next(action for action in menu.actions() if action.text() == "wrong").trigger()
    text = widget.text() if kind is QLineEdit else widget.toPlainText()
    assert text == "😀 wrng, wrong!"
    widget.undo()
    text = widget.text() if kind is QLineEdit else widget.toPlainText()
    assert text == "😀 wrng, wrng!"
    menu.deleteLater()


@pytest.mark.parametrize("kind", [QLineEdit, QPlainTextEdit, QTextEdit])
@pytest.mark.parametrize(
    "reason", [QContextMenuEvent.Reason.Mouse, QContextMenuEvent.Reason.Keyboard]
)
def test_context_menu_executes_and_replaces_word(app, setup, kind, reason):
    manager, _checker, create = setup
    widget = create(kind)
    settle(app)
    point = position(widget, 2)
    target = widget if kind is QLineEdit else widget.viewport()
    event = QContextMenuEvent(reason, point, target.mapToGlobal(point))
    opened = []

    def choose_suggestion():
        menu = app.activePopupWidget()
        if isinstance(menu, QMenu):
            opened.append([action.text() for action in menu.actions()])
            try:
                for action in menu.actions():
                    if action.text() == "wrong":
                        action.trigger()
                        break
            finally:
                menu.close()

    # Exercise the real PySide exec overload, not a mock of the menu method.
    QTimer.singleShot(0, choose_suggestion)
    assert manager.eventFilter(target, event)
    assert opened and "wrong" in opened[0]
    text = widget.text() if kind is QLineEdit else widget.toPlainText()
    assert text == "wrong"
    widget.undo()
    text = widget.text() if kind is QLineEdit else widget.toPlainText()
    assert text == "wrng"


@pytest.mark.parametrize("kind", [QPlainTextEdit, QTextEdit])
def test_multiline_has_red_formats_at_utf16_offsets_without_document_edits(
    app, setup, kind
):
    _manager, _checker, create = setup
    widget = create(kind, "😀 wrng.\nFine wrng")
    widget.document().setModified(False)
    settle(app)
    ranges = formats(widget)
    assert [(item.start, item.length) for item in ranges] == [(3, 4), (5, 4)]
    assert all(item.format.underlineColor().name() == "#d32f2f" for item in ranges)
    assert not widget.document().isModified()
    assert not widget.document().isUndoAvailable()
    widget.setReadOnly(True)
    settle(app)
    assert not formats(widget)
    widget.setReadOnly(False)
    settle(app)
    assert len(formats(widget)) == 2


@pytest.mark.parametrize("label", ["Ignore for this session", "Add to dictionary"])
def test_dictionary_actions_refresh_every_editor_and_external_revision(
    app, setup, label
):
    manager, checker, create = setup
    line = create()
    paragraph = create(QPlainTextEdit)
    settle(app)
    assert formats(paragraph)
    menu = manager.adapters[id(line)].menu(position(line, 2))
    next(action for action in menu.actions() if action.text() == label).trigger()
    settle(app)
    assert not formats(paragraph)
    assert not manager.adapters[id(line)].qt_spans
    assert line.text() == "wrng"
    checker.accepted.clear()
    checker.revision += 1
    QTest.qWait(750)
    assert formats(paragraph)
    menu.deleteLater()


def test_add_failure_is_reported_without_clearing_mark(app, setup, monkeypatch):
    manager, checker, create = setup
    widget = create(QPlainTextEdit)
    settle(app)
    messages = []

    def fail(word):
        raise OSError("disk full")

    monkeypatch.setattr(checker, "add", fail)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    menu = manager.adapters[id(widget)].menu(position(widget, 2))
    next(
        action for action in menu.actions() if action.text() == "Add to dictionary"
    ).trigger()
    assert messages and "disk full" in messages[0]
    assert formats(widget)
    menu.deleteLater()


def test_opt_out_numeric_password_readonly_and_live_transitions(app, setup):
    manager, _checker, create = setup
    excluded = []
    for configure in (
        lambda widget: widget.setProperty("spellcheck", False),
        lambda widget: widget.setEchoMode(QLineEdit.EchoMode.Password),
        lambda widget: widget.setValidator(QIntValidator(widget)),
        lambda widget: widget.setReadOnly(True),
        lambda widget: widget.setInputMask("0000"),
    ):
        widget = QLineEdit("wrng")
        configure(widget)
        excluded.append(widget)
        widget.show()
    spin = QSpinBox()
    excluded.append(spin)
    spin.show()
    app.processEvents()
    assert all(id(widget) not in manager.adapters for widget in excluded)
    assert id(spin.lineEdit()) not in manager.adapters
    paragraph = create(QPlainTextEdit)
    settle(app)
    assert formats(paragraph)
    paragraph.setProperty("spellcheck", False)
    settle(app)
    assert not formats(paragraph)
    for widget in excluded:
        widget.close()
        widget.deleteLater()


def test_overlay_tracks_scroll_alignment_and_is_mouse_transparent(app, setup):
    manager, _checker, create = setup
    widget = create(text="wrng " + "a long correct phrase " * 20 + "wrng")
    widget.resize(160, 32)
    widget.setTextMargins(9, 0, 11, 0)
    settle(app)
    adapter = manager.adapters[id(widget)]
    overlay = adapter.overlay
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.geometry() == widget.rect()
    widget.setCursorPosition(len(widget.text()))
    app.processEvents()
    # A real paint exercises cursor scrolling, clipping and UTF-16 geometry.
    image = widget.grab().toImage()
    red = [
        (x, y)
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).red() > 150
        and image.pixelColor(x, y).green() < 100
        and image.pixelColor(x, y).blue() < 100
    ]
    assert red
    assert all(9 < x < image.width() - 11 for x, y in red)
    widget.setAlignment(Qt.AlignmentFlag.AlignRight)
    widget.setCursorPosition(0)
    app.processEvents()
    assert not widget.grab().isNull()
    assert widget.cursorPositionAt(QPoint(30, 15)) >= 0


def test_stale_menu_cannot_replace_a_different_token(app, setup):
    manager, _checker, create = setup
    widget = create(text="wrng")
    menu = manager.adapters[id(widget)].menu(position(widget, 2))
    widget.setText("different text")
    next(action for action in menu.actions() if action.text() == "wrong").trigger()
    assert widget.text() == "different text"
    menu.deleteLater()


def test_manager_installed_before_editor_construction(app, setup):
    manager, _checker, create = setup
    # Startup installs the global filter before any complex editor's C++
    # constructor runs; constructor events must not inspect its viewport.
    for kind in (QLineEdit, QPlainTextEdit, QTextEdit):
        widget = create(kind)
        assert id(widget) in manager.adapters
    settle(app)


@pytest.mark.parametrize(
    "alignment",
    [
        Qt.AlignmentFlag.AlignLeft,
        Qt.AlignmentFlag.AlignHCenter,
        Qt.AlignmentFlag.AlignRight,
    ],
)
def test_line_underline_follows_visible_word_with_emoji_and_alignment(
    app, setup, alignment
):
    _manager, _checker, create = setup
    widget = create(text="😀 wrng")
    widget.setAlignment(alignment)
    settle(app)
    widget.setCursorPosition(3)
    start = widget.cursorRect().center().x()
    widget.setCursorPosition(7)
    end = widget.cursorRect().center().x()
    widget.setSelection(3, 4)
    image = widget.grab().toImage()
    red_x = [
        x
        for x in range(image.width())
        for y in range(image.height())
        # Match decoration exactly: a color emoji can itself contain red.
        if image.pixelColor(x, y).name() == "#d32f2f"
    ]
    assert red_x
    assert abs(min(red_x) - start) <= 2
    assert abs(max(red_x) - end) <= 2


def test_underlining_is_not_a_text_edit_and_manager_disposal_detaches(app):
    from PySide6.QtTest import QSignalSpy
    from shiboken6 import isValid

    widget = QPlainTextEdit("wrng")
    widget.show()
    edits = QSignalSpy(widget.textChanged)
    first = SpellcheckManager(app, Dictionary())
    settle(app)
    assert formats(widget)
    assert edits.count() == 0
    old_highlighter = first.adapters[id(widget)].highlighter
    first.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(old_highlighter)
    second = SpellcheckManager(app, Dictionary())
    settle(app)
    assert formats(widget)
    assert edits.count() == 0
    widget.insertPlainText("another ")
    assert edits.count() == 1
    settle(app)
    assert edits.count() == 1
    widget.close()
    widget.deleteLater()
    second.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
