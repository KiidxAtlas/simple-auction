import json

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from simple_auction.services.config import Config, ConfigFileError
from simple_auction.ui import main_page, theme
from simple_auction.ui.settings import SECTION_APPEARANCE, SettingsDialog


@pytest.fixture
def app(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_page.api_key, "saved", lambda: None)
    yield app
    theme.apply(app)
    app.processEvents()


@pytest.mark.parametrize("dyslexic", [False, True])
@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_preferences_roundtrip_and_legacy_defaults(tmp_path, dyslexic, size):
    path = tmp_path / "config.json"
    config = Config(
        base_dir=tmp_path / "catalogue", dyslexic_font=dyslexic, font_size=size
    )
    config.save(path)
    loaded = Config.load(path)
    assert (loaded.dyslexic_font, loaded.font_size) == (dyslexic, size)
    path.write_text("{}")
    legacy = Config.load(path)
    assert (legacy.dyslexic_font, legacy.font_size) == (False, "medium")
    assert path.read_text() == "{}"


@pytest.mark.parametrize(
    "values",
    [
        {"dyslexic_font": "yes"},
        {"dyslexic_font": 1},
        {"font_size": "giant"},
        {"font_size": []},
    ],
)
def test_invalid_preferences_are_reported_not_overwritten(tmp_path, values):
    path = tmp_path / "config.json"
    raw = json.dumps(values)
    path.write_text(raw)
    with pytest.raises(ConfigFileError):
        Config.load(path)
    assert path.read_text() == raw


@pytest.mark.parametrize("dark", [False, True])
def test_bundled_font_applies_to_existing_and_new_widgets_and_role_sizes(app, dark):
    parent = QWidget()
    layout = QVBoxLayout(parent)
    field = QLineEdit("Catalogue details")
    caption = QLabel("Hint")
    caption.setObjectName("fieldHint")
    heading = QLabel("Heading")
    heading.setObjectName("lotTitle")
    button = QPushButton("Settings")
    for widget in (field, caption, heading, button):
        layout.addWidget(widget)
    parent.show()
    observed = []
    for size in ("small", "medium", "large"):
        theme.apply(app, dark_mode=dark, dyslexic_font=True, font_size=size)
        app.processEvents()
        new_menu = QMenu()
        new_menu.ensurePolished()
        expected_family = app.font().family()
        assert "opendyslexic" in expected_family.casefold()
        assert "opendyslexic" in QFontInfo(app.font()).family().casefold()
        for widget in (field, caption, heading, button, new_menu):
            assert widget.font().family() == expected_family
        assert (
            caption.font().pixelSize()
            < field.font().pixelSize()
            < heading.font().pixelSize()
        )
        observed.append(field.font().pixelSize())
        assert theme.colors() == (theme.DARK if dark else theme.LIGHT)
        new_menu.deleteLater()
    assert observed == sorted(set(observed))
    theme.apply(app, dark_mode=dark, dyslexic_font=False)
    app.processEvents()
    assert "opendyslexic" not in field.font().family().casefold()
    parent.close()
    parent.deleteLater()


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(main_page.source_update, "repo_root", lambda: None)
    monkeypatch.setattr(main_page, "is_frozen", lambda: False)
    theme.apply(app, dark_mode=False)
    page = main_page.MainPage(
        Config(
            base_dir=tmp_path / "catalogue",
            photos_dir=tmp_path / "photos",
            dark_mode=False,
        )
    )
    page._ui_state = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    yield page
    page._autosave.stop()
    page.form.mark_saved()
    page.close()
    page.deleteLater()
    app.processEvents()


def test_settings_save_applies_and_reopens_font_preferences(
    window, tmp_path, monkeypatch
):
    path = tmp_path / "config.json"
    save = Config.save
    monkeypatch.setattr(Config, "save", lambda self: save(self, path))

    def choose(dialog):
        dialog.dyslexic_toggle.setChecked(True)
        dialog.font_size_choice.setCurrentIndex(
            dialog.font_size_choice.findData("large")
        )
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(SettingsDialog, "exec", choose)
    window.open_settings()
    assert window.config.dyslexic_font is True
    assert window.config.font_size == "large"
    assert "opendyslexic" in QApplication.font().family().casefold()
    assert QApplication.font().pixelSize() == 17
    saved = Config.load(path)
    dialog = SettingsDialog(saved, [])
    assert dialog.dyslexic_font() is True
    assert dialog.font_size() == "large"
    assert "OpenDyslexic" in dialog.font_preview.styleSheet()
    dialog.deleteLater()


def test_cancel_and_save_failure_keep_current_font(window, monkeypatch):
    original = QApplication.font()

    def reject(dialog):
        dialog.dyslexic_toggle.setChecked(True)
        dialog.font_size_choice.setCurrentIndex(
            dialog.font_size_choice.findData("large")
        )
        dialog.reject()
        return dialog.result()

    monkeypatch.setattr(SettingsDialog, "exec", reject)
    window.open_settings()
    assert QApplication.font() == original
    assert window.config.dyslexic_font is False
    assert window.config.font_size == "medium"

    def accept(dialog):
        dialog.dyslexic_toggle.setChecked(True)
        dialog.font_size_choice.setCurrentIndex(
            dialog.font_size_choice.findData("large")
        )
        dialog.accept()
        return dialog.result()

    def fail(self):
        raise OSError("disk full")

    monkeypatch.setattr(SettingsDialog, "exec", accept)
    monkeypatch.setattr(Config, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        window.open_settings()
    assert QApplication.font() == original
    assert window.config.dyslexic_font is False
    assert window.config.font_size == "medium"


def test_large_dyslexic_appearance_controls_fit_and_sidebar_rows_grow(app, tmp_path):
    from PySide6.QtWidgets import QStyleOptionViewItem

    from simple_auction.models import Lot
    from simple_auction.ui.components.lot_sidebar import LotSidebar

    theme.apply(app, dyslexic_font=True, font_size="large")
    dialog = SettingsDialog(
        Config(base_dir=tmp_path, dyslexic_font=True, font_size="large"), []
    )
    dialog.show_section(SECTION_APPEARANCE)
    dialog.resize(720, 520)
    dialog.show()
    app.processEvents()
    scroll = dialog.pages.currentWidget()
    assert scroll.widget().width() <= scroll.viewport().width()
    for widget in (dialog.dyslexic_toggle, dialog.font_size_choice):
        assert widget.isVisible()
        assert widget.width() >= widget.minimumSizeHint().width()
    sidebar = LotSidebar()
    sidebar.populate({1000: [Lot(1000)]})
    option = QStyleOptionViewItem()
    option.initFrom(sidebar.tree)
    row_size = sidebar.delegate.sizeHint(option, sidebar.tree.model().index(0, 0))
    assert row_size.height() >= option.fontMetrics.height() + 12
    dialog.close()
    dialog.deleteLater()
    sidebar.deleteLater()
