"""All look-and-feel lives here: colors, sizes, and the stylesheet."""

import tempfile
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from string import Template

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QLineEdit
from shiboken6 import isValid

SPACING = 12
RADIUS = 10
SIDEBAR_WIDTH = 280  # starting widths; both can be dragged
SIDEBAR_MIN_WIDTH = 200
SIDEBAR_MAX_WIDTH = 480
RESEARCH_WIDTH = 400
RESEARCH_MIN_WIDTH = 300
CONTENT_MAX_WIDTH = 1240
# The lot editor shows details and photos side by side from this width.
TWO_COLUMN_WIDTH = 940
# Narrowest the lot editor gets; the side panels give way first.
EDITOR_MIN_WIDTH = 440
# Fields in a card sit side by side while each gets at least this width.
FIELD_MIN_WIDTH = 150
THUMB_SIZE = 96
TREE_ROW_HEIGHT = 30
WINDOW_SIZE = (1280, 800)
WINDOW_MIN_SIZE = (720, 520)
ICON_SIZE = QSize(16, 16)

# One type scale for the whole app (pixels), used by styles.qss.
FONT_SIZES = {
    "fs_caption": 11,  # section eyebrows, counters
    "fs_small": 12,  # hints, field labels
    "fs_body": 13,  # default text
    "fs_heading": 15,  # card and section titles
    "fs_title": 22,  # page titles
    "fs_display": 28,  # the shipping weight entry
}

STYLESHEET = Path(__file__).with_name("styles.qss")
FONT_DIR = Path(__file__).with_name("fonts")
FONT_SCALES = {"small": 12 / 13, "medium": 1.0, "large": 17 / 13}


@cache
def _dyslexic_family() -> str:
    families = []
    for style in ("Regular", "Bold", "Italic", "BoldItalic"):
        path = FONT_DIR / f"OpenDyslexic-{style}.otf"
        font_id = QFontDatabase.addApplicationFont(str(path))
        loaded = QFontDatabase.applicationFontFamilies(font_id)
        if font_id < 0 or not loaded:
            raise RuntimeError(f"Could not load bundled OpenDyslexic font: {path}")
        families.extend(loaded)
    return families[0]


def text_font(*, dyslexic_font: bool = False, font_size: str = "medium") -> QFont:
    """One app-wide family and base size; role sizes use the same scale."""
    if font_size not in FONT_SCALES:
        raise ValueError("Unknown font size")
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    if dyslexic_font:
        font.setFamily(_dyslexic_family())
    font.setPixelSize(round(FONT_SIZES["fs_body"] * FONT_SCALES[font_size]))
    return font


# Line icons (24×24, stroked), drawn in the current theme's colors.
ICONS = {
    "plus": "M12 5v14M5 12h14",
    "settings": (
        "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"
        "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06"
        "a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09"
        "A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83"
        "l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09"
        "A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83"
        "l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09"
        "a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83"
        "l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09"
        "a1.65 1.65 0 0 0-1.51 1z"
    ),
    "import": "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
    "export": "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
    "search": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35",
    "prev": "M15 18l-6-6 6-6",
    "next": "M9 18l6-6-6-6",
    "up": "M18 15l-6-6-6 6",
    "down": "M6 9l6 6 6-6",
    "folder": "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z",
    "list": "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
    "type": "M4 7V4h16v3M9 20h6M12 4v16",
    "sun": (
        "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.22 4.22l1.42 1.42"
        "M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
    ),
    "wifi": (
        "M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0"
        "M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01"
    ),
    "close": "M18 6L6 18M6 6l12 12",
    "external": "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3",
    "sparkle": (
        "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"
        "M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"
    ),
    "more": "M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM19 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM5 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
    "refresh": "M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15",
    "image": "M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM21 15l-5-5L5 21",
    "trash": "M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2",
    "box": "M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16zM3.27 6.96L12 12.01l8.73-5.05M12 22.08V12",
    "book": "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z",
    "update": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM16 12l-4-4-4 4M12 16V8",
    "gavel": (
        "M14 13l-7.5 7.5a2.12 2.12 0 0 1-3-3L11 10M16 16l6-6M8 8l6-6M9 7l8 8M21 11l-8-8"
    ),
}

# Widgets showing an icon, so a theme switch can redraw them in its colors.
_icon_users: list[tuple] = []


@dataclass(frozen=True)
class Colors:
    bg: str
    surface: str
    sidebar: str
    border: str  # card and divider lines
    field_border: str  # inputs and buttons: a touch stronger than cards
    shadow: str  # the bottom edge of raised surfaces
    field: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    hover: str
    danger: str
    warning: str


LIGHT = Colors(
    bg="#f3f4f6",
    surface="#ffffff",
    sidebar="#eceef2",
    border="#e2e5ea",
    field_border="#d3d8df",
    shadow="#d3d7dd",
    field="#ffffff",
    text="#15181d",
    muted="#616a77",
    accent="#1f7f8d",
    accent_hover="#196b77",
    accent_text="#ffffff",
    accent_soft="#dbeff2",
    hover="#e7eaee",
    danger="#c23a3a",
    warning="#bf7f10",
)

DARK = Colors(
    bg="#111316",
    surface="#1a1d21",
    sidebar="#0d0f12",
    border="#272b31",
    field_border="#343941",
    shadow="#08090b",
    field="#14171a",
    text="#e8eaed",
    muted="#8d949e",
    accent="#3fb3c2",
    accent_hover="#5cc3d0",
    accent_text="#04252a",
    accent_soft="#173539",
    hover="#22262b",
    danger="#ec7465",
    warning="#e3ab4b",
)

_current = LIGHT


def colors() -> Colors:
    return _current


def _is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def apply(
    app: QApplication,
    *,
    dark_mode: bool | None = None,
    dyslexic_font: bool = False,
    font_size: str = "medium",
) -> None:
    """Apply color and typography together, including on OS theme changes."""
    global _current
    font = text_font(dyslexic_font=dyslexic_font, font_size=font_size)
    dark = _is_dark() if dark_mode is None else dark_mode
    _current = DARK if dark else LIGHT
    app.setStyle("Fusion")
    app.setFont(font)
    app.setPalette(_palette(_current))
    app.setStyleSheet(_stylesheet(_current, font=font, font_size=font_size))
    _refresh_icons()


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


def _svg_file(name: str, body: str, color: str) -> str:
    """Write an SVG once per color (QSS and QIcon both need a file)."""
    path = Path(tempfile.gettempdir()) / f"simple-auction-{name}-{color[1:]}.svg"
    if not path.exists():
        path.write_text(body)
    return path.as_posix()


def _chevron(c: Colors) -> str:
    """Dropdown arrow as an SVG file, since QSS can't draw one itself."""
    return _svg_file(
        "chevron",
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" '
        'viewBox="0 0 12 12"><path d="M3 4.5l3 3 3-3" fill="none" '
        f'stroke="{c.muted}" stroke-width="1.6" stroke-linecap="round" '
        'stroke-linejoin="round"/></svg>',
        c.muted,
    )


def _check(c: Colors) -> str:
    """Tick for checked list checkboxes, drawn in the accent text color."""
    return _svg_file(
        "check",
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" '
        'viewBox="0 0 12 12"><path d="M2.5 6.2l2.3 2.3 4.7-4.9" fill="none" '
        f'stroke="{c.accent_text}" stroke-width="1.8" stroke-linecap="round" '
        'stroke-linejoin="round"/></svg>',
        c.accent_text,
    )


def icon(name: str, role: str = "muted") -> QIcon:
    """A line icon drawn in a theme color (`role` is a Colors field)."""
    color = getattr(_current, role)
    path = _svg_file(
        f"icon-{name}",
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round"><path d="{ICONS[name]}"/></svg>',
        color,
    )
    return QIcon(path)


def set_icon(widget, name: str, role: str = "muted", size: QSize = ICON_SIZE) -> None:
    """Give a button, label, or line edit (as a leading action) a themed icon
    that is redrawn on later light/dark switches."""
    _apply_icon(widget, name, role, size)
    _icon_users[:] = [entry for entry in _icon_users if isValid(entry[0])]
    _icon_users.append((widget, name, role, size))


def _apply_icon(widget, name: str, role: str, size: QSize) -> None:
    if isinstance(widget, QAbstractButton):
        widget.setIcon(icon(name, role))
        widget.setIconSize(size)
    elif isinstance(widget, QLabel):
        widget.setPixmap(icon(name, role).pixmap(size))
    elif isinstance(widget, QLineEdit):
        for action in widget.actions():
            if action.property("themeIcon"):
                action.setIcon(icon(name, role))
                return
        action = widget.addAction(
            icon(name, role), QLineEdit.ActionPosition.LeadingPosition
        )
        action.setProperty("themeIcon", True)
    else:
        widget.setIcon(icon(name, role))


def _refresh_icons() -> None:
    alive = [entry for entry in _icon_users if isValid(entry[0])]
    _icon_users[:] = alive
    for entry in alive:
        _apply_icon(*entry)


def repolish(widget, **properties) -> None:
    """Set properties that styles.qss matches on, and restyle if they changed."""
    changed = False
    for key, value in properties.items():
        if widget.property(key) != value:
            widget.setProperty(key, value)
            changed = True
    if changed:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def _stylesheet(
    c: Colors, *, font: QFont | None = None, font_size: str = "medium"
) -> str:
    if not STYLESHEET.exists():
        return ""
    values = (
        asdict(c)
        | {
            key: round(value * FONT_SCALES[font_size])
            for key, value in FONT_SIZES.items()
        }
        | {
            "radius": RADIUS,
            "chevron": _chevron(c),
            "check": _check(c),
            "font_family": (font or text_font()).family().replace('"', '\\"'),
        }
    )
    return Template(STYLESHEET.read_text()).substitute(values)
