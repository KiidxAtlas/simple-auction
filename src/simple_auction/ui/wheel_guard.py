"""Let pages scroll without accidentally changing closed dropdowns."""

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QComboBox
from shiboken6 import isValid


def forward_wheel_to_scroll_area(widget, event) -> None:
    """Pass a gesture to the containing page without editing the hovered input."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            viewport = parent.viewport()
            forwarded = QWheelEvent(
                viewport.mapFromGlobal(event.globalPosition()),
                event.globalPosition(),
                event.pixelDelta(),
                event.angleDelta(),
                event.buttons(),
                event.modifiers(),
                event.phase(),
                event.inverted(),
                event.source(),
                event.pointingDevice(),
            )
            QApplication.sendEvent(viewport, forwarded)
            event.setAccepted(forwarded.isAccepted())
            return
        parent = parent.parentWidget()
    event.ignore()


class DropdownWheelGuard(QObject):
    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Type.Wheel
            and isinstance(obj, QComboBox)
            and not obj.view().isVisible()
        ):
            forward_wheel_to_scroll_area(obj, event)
            return True
        return False


def install_dropdown_wheel_guard(app: QApplication) -> DropdownWheelGuard:
    """Cover existing and future dropdowns, including ones created by dialogs."""
    existing = getattr(app, "_dropdown_wheel_guard", None)
    if existing is not None and isValid(existing):
        return existing
    guard = DropdownWheelGuard(app)
    app.installEventFilter(guard)
    app._dropdown_wheel_guard = guard
    return guard
