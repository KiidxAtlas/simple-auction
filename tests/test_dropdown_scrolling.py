"""Scrolling must never edit a closed dropdown, including a focused one."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QVBoxLayout, QWidget

from simple_auction.ui.wheel_guard import install_dropdown_wheel_guard


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def guarded(app):
    guard = install_dropdown_wheel_guard(app)
    assert install_dropdown_wheel_guard(app) is guard
    yield guard
    app.removeEventFilter(guard)
    guard.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def wheel(widget, *, angle=-120, pixels=0):
    position = widget.rect().center()
    event = QWheelEvent(
        QPointF(position),
        QPointF(widget.mapToGlobal(position)),
        QPoint(0, pixels),
        QPoint(0, angle),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate if pixels else Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


@pytest.mark.parametrize("editable", [False, True])
@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize(("angle", "pixels"), [(-120, 0), (120, 0), (0, -30)])
def test_closed_dropdown_ignores_mouse_and_trackpad_scroll(
    app, guarded, editable, focused, angle, pixels
):
    window = QWidget()
    layout = QVBoxLayout(window)
    combo = QComboBox()
    combo.setEditable(editable)
    combo.addItems(["First", "Second", "Third"])
    combo.setCurrentIndex(1)
    layout.addWidget(combo)
    other = QComboBox()
    other.addItems(["Other"])
    layout.addWidget(other)
    window.show()
    (combo if focused else other).setFocus()
    app.processEvents()
    changed = QSignalSpy(combo.currentIndexChanged)
    activated = QSignalSpy(combo.activated)
    wheel(combo, angle=angle, pixels=pixels)
    if editable:
        wheel(combo.lineEdit(), angle=angle, pixels=pixels)
    assert combo.currentIndex() == 1
    assert changed.count() == activated.count() == 0
    QTest.keyClick(combo, Qt.Key.Key_Down)
    assert combo.currentIndex() == 2
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("editable", [False, True])
def test_page_keeps_scrolling_when_pointer_is_over_dropdown(app, guarded, editable):
    scroll = QScrollArea()
    body = QWidget()
    body.setMinimumHeight(1800)
    layout = QVBoxLayout(body)
    layout.addSpacing(500)
    combo = QComboBox()
    combo.addItems(["First", "Second", "Third"])
    combo.setCurrentIndex(1)
    layout.addWidget(combo)
    layout.addStretch()
    scroll.setWidget(body)
    combo.setEditable(editable)
    scroll.setWidgetResizable(True)
    scroll.resize(400, 300)
    scroll.show()
    app.processEvents()
    scroll.verticalScrollBar().setValue(400)
    combo.setFocus()
    before = scroll.verticalScrollBar().value()
    wheel(combo)
    assert combo.currentIndex() == 1
    assert scroll.verticalScrollBar().value() > before
    scroll.close()
    scroll.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_open_popup_still_scrolls_and_click_selects(app, guarded):
    combo = QComboBox()
    combo.addItems([f"Option {number}" for number in range(100)])
    combo.setMaxVisibleItems(8)
    combo.show()
    combo.showPopup()
    app.processEvents()
    view = combo.view()
    before = view.verticalScrollBar().value()
    wheel(view.viewport())
    assert view.verticalScrollBar().value() > before
    target = combo.model().index(10, 0)
    view.scrollTo(target)
    app.processEvents()
    QTest.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(target).center()
    )
    assert combo.currentIndex() == 10
    combo.hidePopup()
    combo.close()
    combo.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
