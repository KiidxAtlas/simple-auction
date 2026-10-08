"""All look-and-feel lives here: colors, sizes, and the stylesheet."""

import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

SPACING = 12
RADIUS = 8
SIDEBAR_WIDTH = 250  # starting widths; both can be dragged
SIDEBAR_MIN_WIDTH = 180
SIDEBAR_MAX_WIDTH = 480
RESEARCH_WIDTH = 400
RESEARCH_MIN_WIDTH = 300
CONTENT_MAX_WIDTH = 760
THUMB_SIZE = 84
TREE_ROW_HEIGHT = 30
WINDOW_SIZE = (1120, 740)

STYLESHEET = Path(__file__).with_name("styles.qss")


@dataclass(frozen=True)
class Colors:
    bg: str
    surface: str
    sidebar: str
    border: str
    field: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    hover: str
    danger: str


LIGHT = Colors(
    bg="#f5f6f8",
    surface="#ffffff",
    sidebar="#eceef1",
    border="#dde1e6",
    field="#fbfbfc",
    text="#1d2127",
    muted="#6b7380",
    accent="#2f8f9d",
    accent_hover="#277884",
    accent_text="#ffffff",
    accent_soft="#d5ecef",
    hover="#e1e5ea",
    danger="#c93c3c",
)

DARK = Colors(
    bg="#16181b",
    surface="#1e2125",
    sidebar="#121417",
    border="#2d3137",
    field="#181a1e",
    text="#e5e7ea",
    muted="#8a919b",
    accent="#3aa5b4",
    accent_hover="#4bb5c4",
    accent_text="#ffffff",
    accent_soft="#1c3a3f",
    hover="#24282d",
    danger="#e06a5a",
)

_current = LIGHT


def colors() -> Colors:
    return _current


def _is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def apply(app: QApplication) -> None:
    """Apply the light or dark theme, matching the OS setting."""
    global _current
    _current = DARK if _is_dark() else LIGHT
    app.setStyle("Fusion")
    app.setPalette(_palette(_current))
    app.setStyleSheet(_stylesheet(_current))


def _palette(c: Colors) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.bg,
        QPalette.ColorRole.WindowText: c.text,
        QPalette.ColorRole.Base: c.field,
        QPalette.ColorRole.AlternateBase: c.hover,
        QPalette.ColorRole.Text: c.text,
        QPalette.ColorRole.PlaceholderText: c.muted,
        QPalette.ColorRole.Button: c.surface,
        QPalette.ColorRole.ButtonText: c.text,
        QPalette.ColorRole.Highlight: c.accent,
        QPalette.ColorRole.HighlightedText: c.accent_text,
        QPalette.ColorRole.ToolTipBase: c.surface,
        QPalette.ColorRole.ToolTipText: c.text,
        QPalette.ColorRole.Mid: c.border,
        QPalette.ColorRole.Link: c.accent,
        QPalette.ColorRole.LinkVisited: c.accent_hover,
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(c.muted))
    p.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(c.muted)
    )
    return p


def _chevron(c: Colors) -> str:
    """Dropdown arrow as an SVG file, since QSS can't draw one itself."""
    path = Path(tempfile.gettempdir()) / f"simple-auction-chevron-{c.muted[1:]}.svg"
    if not path.exists():
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" '
            'viewBox="0 0 12 12"><path d="M3 4.5l3 3 3-3" fill="none" '
            f'stroke="{c.muted}" stroke-width="1.6" stroke-linecap="round" '
            'stroke-linejoin="round"/></svg>'
        )
    return path.as_posix()


def _stylesheet(c: Colors) -> str:
    if not STYLESHEET.exists():
        return ""
    values = asdict(c) | {"radius": RADIUS, "chevron": _chevron(c)}
    return Template(STYLESHEET.read_text()).substitute(values)
