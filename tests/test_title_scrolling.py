"""Long titles can pan independently of their text, caret and selection."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from simple_auction.constants import TITLE_MAX_LENGTH
from simple_auction.models import Lot
from simple_auction.ui import theme
from simple_auction.ui.components.lot_form import LotForm

LONG_TITLE = "Remington 870 Wingmaster pump-action shotgun with original case and additional collector accessories"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def form(app):
    theme.apply(app)
    form = LotForm()
    form.resize(1100, 950)
    form.load(Lot(1, title=LONG_TITLE), 1000)
    form.show()
    for _ in range(3):
        app.processEvents()
    form.title.setCursorPosition(0)
    form.mark_saved()
    yield form
    form.mark_saved()
    form.close()
    form.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    theme.apply(app)
    app.processEvents()


def wheel(widget, *, pixels=None, angle=None, shift=False):
    pixels = QPoint() if pixels is None else pixels
    angle = QPoint() if angle is None else angle
    position = widget.visibleRegion().boundingRect().center()
    event = QWheelEvent(
        QPointF(position),
        QPointF(widget.mapToGlobal(position)),
        pixels,
        angle,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate
        if not pixels.isNull()
        else Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


@pytest.mark.parametrize("receiver", ["edit", "viewport"])
@pytest.mark.parametrize(
    ("pixels", "angle", "shift"),
    [
        (QPoint(-80, 0), QPoint(), False),
        (QPoint(-80, -10), QPoint(), False),
        (QPoint(), QPoint(-120, 0), False),
        (QPoint(), QPoint(0, -120), True),
        (QPoint(0, -80), QPoint(), True),
    ],
)
def test_horizontal_gestures_do_not_edit_title_or_selection(
    form, receiver, pixels, angle, shift
):
    edit, view = form.title, form.title_scroll
    bar = view.horizontalScrollBar()
    assert bar.maximum() > 0 and bar.isVisible()
    edit.setSelection(3, 8)
    original = (
        edit.text(),
        edit.cursorPosition(),
        edit.selectionStart(),
        edit.selectedText(),
    )
    edits = QSignalSpy(form.changed)
    bar.setValue(0)
    wheel(
        edit if receiver == "edit" else view.viewport(),
        pixels=pixels,
        angle=angle,
        shift=shift,
    )
    assert bar.value() > 0
    assert (
        edit.text(),
        edit.cursorPosition(),
        edit.selectionStart(),
        edit.selectedText(),
    ) == original
    assert edits.count() == 0
    assert form.collect().title == original[0]


def test_scrollbar_drag_range_reveals_entire_title_without_moving_caret(form):
    bar = form.title_scroll.horizontalScrollBar()
    original_cursor = form.title.cursorPosition()
    original_text = form.title.text()
    bar.setValue(bar.maximum())
    assert form.title.geometry().right() <= form.title_scroll.viewport().rect().right()
    assert form.title.cursorPosition() == original_cursor
    assert form.title.text() == original_text
    bar.setValue(0)
    assert form.title.geometry().left() == 0


def test_keyboard_navigation_and_undo_keep_caret_in_view(app, form):
    edit, view = form.title, form.title_scroll
    edit.setFocus()
    QTest.keyClick(edit, Qt.Key.Key_End)
    assert edit.cursorPosition() == len(edit.text())
    caret = edit.mapTo(view.viewport(), edit.cursorRect().center())
    assert 0 <= caret.x() <= view.viewport().width()
    assert view.horizontalScrollBar().value() > 0
    QTest.keyClick(edit, Qt.Key.Key_Home)
    assert view.horizontalScrollBar().value() == 0
    original = edit.text()
    edit.selectAll()
    QTest.keyClicks(edit, "Short")
    app.processEvents()
    assert edit.text() == "Short"
    assert view.horizontalScrollBar().maximum() == 0
    assert not view.horizontalScrollBar().isVisible()
    edit.undo()
    app.processEvents()
    assert edit.text() == original
    assert view.horizontalScrollBar().maximum() > 0


@pytest.mark.parametrize("drift", [0, 8])
def test_vertical_scrolling_over_title_still_scrolls_page(app, form, drift):
    form.resize(1100, 480)
    for _ in range(3):
        app.processEvents()
    page_bar = form.scroll.verticalScrollBar()
    assert page_bar.maximum() > 0
    page_bar.setValue(0)
    horizontal = form.title_scroll.horizontalScrollBar().value()
    original = form.title.text()
    wheel(form.title, angle=QPoint(drift, -120))
    assert page_bar.value() > 0
    assert form.title_scroll.horizontalScrollBar().value() == horizontal
    assert form.title.text() == original


def test_font_and_width_changes_preserve_title_limit_and_do_not_widen_page(app, form):
    form.title.setText("W" * (TITLE_MAX_LENGTH + 20))
    assert len(form.title.text()) == TITLE_MAX_LENGTH
    theme.apply(app, dyslexic_font=True, font_size="large")
    form.resize(520, 950)
    for _ in range(3):
        app.processEvents()
    view = form.title_scroll
    assert view.horizontalScrollBar().maximum() > 0
    assert (
        view.height()
        >= form.title.height() + view.horizontalScrollBar().sizeHint().height()
    )
    assert form.scroll.horizontalScrollBar().maximum() == 0
    assert form.title.text() == "W" * TITLE_MAX_LENGTH
