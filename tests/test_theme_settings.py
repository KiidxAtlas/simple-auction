import json
import os
import subprocess
import sys

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea

from simple_auction.services.config import Config, ConfigFileError
from simple_auction.ui import main_page, theme
from simple_auction.ui.settings import SettingsDialog


@pytest.fixture
def app(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_page.api_key, "saved", lambda: None)
    yield app
    theme.apply(app)
    app.processEvents()


@pytest.mark.parametrize("mode", [None, False, True])
def test_theme_preference_round_trip(tmp_path, mode):
    path = tmp_path / "config.json"
    config = Config(base_dir=tmp_path / "data", dark_mode=mode)
    config.save(path)
    assert Config.load(path).dark_mode is mode
    assert json.loads(path.read_text())["dark_mode"] is mode


def test_legacy_settings_follow_system_without_overwriting_file(tmp_path):
    path = tmp_path / "config.json"
    raw = json.dumps({"base_dir": str(tmp_path / "data")})
    path.write_text(raw)
    assert Config.load(path).dark_mode is None
    assert path.read_text() == raw


@pytest.mark.parametrize("invalid", ["false", 0, 1, [], {}])
def test_invalid_theme_setting_is_reported_without_overwriting(tmp_path, invalid):
    path = tmp_path / "config.json"
    raw = json.dumps({"dark_mode": invalid})
    path.write_text(raw)
    with pytest.raises(ConfigFileError, match="dark_mode"):
        Config.load(path)
    assert path.read_text() == raw


@pytest.mark.parametrize("system_dark", [False, True])
@pytest.mark.parametrize("mode", [None, False, True])
def test_theme_override_and_system_default(app, monkeypatch, system_dark, mode):
    monkeypatch.setattr(theme, "_is_dark", lambda: system_dark)
    theme.apply(app, dark_mode=mode)
    expected = theme.DARK if (system_dark if mode is None else mode) else theme.LIGHT
    assert theme.colors() == expected
    assert app.palette().color(QPalette.ColorRole.Window).name() == expected.bg
    assert app.palette().color(QPalette.ColorRole.WindowText).name() == expected.text
    # Reapplying after a system change must not override an explicit preference.
    monkeypatch.setattr(theme, "_is_dark", lambda: not system_dark)
    theme.apply(app, dark_mode=mode)
    if mode is not None:
        assert theme.colors() == expected


@pytest.mark.parametrize("mode", [False, True])
def test_settings_theme_choice_uses_saved_preference(app, tmp_path, mode):
    theme.apply(app, dark_mode=not mode)
    dialog = SettingsDialog(Config(base_dir=tmp_path, dark_mode=mode), [])
    try:
        assert dialog.dark_mode() is mode
        dialog.theme_options[not mode].setChecked(True)
        assert dialog.dark_mode() is (not mode)
        dialog.theme_options[None].setChecked(True)
        assert dialog.dark_mode() is None
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_legacy_settings_offer_match_system(app, tmp_path):
    theme.apply(app, dark_mode=True)
    dialog = SettingsDialog(Config(base_dir=tmp_path), [])
    try:
        assert dialog.theme_options[None].isChecked()
        assert dialog.dark_mode() is None
    finally:
        dialog.deleteLater()
        app.processEvents()


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(main_page.source_update, "repo_root", lambda: None)
    monkeypatch.setattr(main_page, "is_frozen", lambda: False)
    config = Config(
        base_dir=tmp_path / "data", photos_dir=tmp_path / "photos", dark_mode=False
    )
    theme.apply(app, dark_mode=False)
    page = main_page.MainPage(config)
    page._ui_state = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    yield page
    page.close()
    page.deleteLater()
    app.processEvents()


def test_settings_save_switches_both_ways_and_persists(window, tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    save = Config.save
    monkeypatch.setattr(Config, "save", lambda self: save(self, path))
    chosen = True

    def accept(dialog):
        dialog.theme_options[chosen].setChecked(True)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(SettingsDialog, "exec", accept)
    window.open_settings()
    assert window.config.dark_mode is True
    assert theme.colors() == theme.DARK
    assert Config.load(path).dark_mode is True
    chosen = False
    window.open_settings()
    assert window.config.dark_mode is False
    assert theme.colors() == theme.LIGHT
    assert Config.load(path).dark_mode is False


def test_settings_cancel_does_not_change_theme_or_save(window, monkeypatch):
    def reject(dialog):
        dialog.theme_options[True].setChecked(True)
        dialog.reject()
        return dialog.result()

    def must_not_save(self):
        raise AssertionError("Cancel must not save settings")

    monkeypatch.setattr(SettingsDialog, "exec", reject)
    monkeypatch.setattr(Config, "save", must_not_save)
    window.open_settings()
    assert window.config.dark_mode is False
    assert theme.colors() == theme.LIGHT


def test_failed_settings_save_keeps_previous_theme(window, monkeypatch):
    def accept(dialog):
        dialog.theme_options[True].setChecked(True)
        dialog.accept()
        return dialog.result()

    def fail(self):
        raise OSError("disk full")

    monkeypatch.setattr(SettingsDialog, "exec", accept)
    monkeypatch.setattr(Config, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        window.open_settings()
    assert window.config.dark_mode is False
    assert theme.colors() == theme.LIGHT


def test_startup_restores_saved_theme_and_os_callback_honors_it(tmp_path):
    path = tmp_path / "config.json"
    Config(base_dir=tmp_path / "data", dark_mode=True).save(path)
    code = """
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from simple_auction import __main__ as entry
from simple_auction.services.config import Config
from simple_auction.ui import theme
path = Path(sys.argv[1])
entry.CONFIG_PATH = path
entry._load_config = lambda: Config.load(path)
entry._setup_logging = lambda: None
entry._use_system_certificates = lambda: None
entry.load_dotenv = lambda: None
class Window(QWidget):
    def __init__(self, config):
        super().__init__()
        assert config.dark_mode is True and theme.colors() == theme.DARK
        app = QApplication.instance()
        app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
        assert theme.colors() == theme.DARK
        config.dark_mode = False
        app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
        assert theme.colors() == theme.LIGHT
        QTimer.singleShot(0, app.quit)
entry.MainPage = Window
assert entry.main() == 0
"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_settings_follow_system_theme_is_saved(window, tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    save = Config.save
    monkeypatch.setattr(Config, "save", lambda self: save(self, path))

    def accept(dialog):
        dialog.theme_options[None].setChecked(True)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(SettingsDialog, "exec", accept)
    window.open_settings()
    assert window.config.dark_mode is None
    assert Config.load(path).dark_mode is None


def test_settings_controls_remain_reachable_on_small_screens(app, tmp_path):
    dialog = SettingsDialog(Config(base_dir=tmp_path), [])
    try:
        dialog.resize(720, 480)
        dialog.show()
        app.processEvents()
        buttons = dialog.findChild(QDialogButtonBox)
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        assert save.objectName() == "primary"
        sections = [dialog.nav.item(i).text() for i in range(dialog.nav.count())]
        assert sections == [
            "Auction setup",
            "Conditions",
            "Listing fields",
            "Appearance",
            "Sharing",
            "Folders",
            "Research",
        ]
        assert dialog.pages.currentIndex() == 0
        expected_visible = {
            "Auction setup": [dialog.next_number, dialog.links],
            "Conditions": [dialog.conditions_editor],
            "Listing fields": [dialog.title_fields_list, dialog.desc_order],
            "Appearance": [dialog.theme_options[None]],
            "Sharing": [dialog.network],
            "Folders": [dialog.folder, dialog.photos],
            "Research": [dialog.key],
        }
        everything = [w for ws in expected_visible.values() for w in ws]
        for section, visible in expected_visible.items():
            dialog.show_section(section)
            app.processEvents()
            scroll = dialog.pages.currentWidget()
            assert isinstance(scroll, QScrollArea)
            for widget in everything:
                assert widget.isVisible() == (widget in visible), (section, widget)
            assert buttons.isVisible()
            assert dialog.rect().contains(
                buttons.geometry().translated(buttons.parentWidget().pos())
            )
            # Nothing on the page is wider than the page (no cut-off controls).
            assert scroll.widget().width() <= scroll.viewport().width()
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            app.processEvents()
            assert buttons.isVisible()
        # Switching sections preserves pending edits until the shared Save action.
        dialog.next_number.setText("52000")
        dialog.show_section("Appearance")
        dialog.theme_options[True].setChecked(True)
        dialog.show_section("Auction setup")
        assert dialog.next_auction() == 52000
        assert dialog.dark_mode() is True
        # Lists use extra window space instead of staying at a fixed height.
        dialog.show_section("Conditions")
        app.processEvents()
        editor = dialog.conditions_editor
        small_height = editor.list.height()
        dialog.resize(980, 1000)
        app.processEvents()
        assert editor.list.height() > small_height
        # The first condition is open for editing from the start.
        assert editor.list.currentRow() == 0
        assert editor.inputs["name"].text() == dialog.conditions()[0].name
        assert not dialog.move_up.isEnabled()
        assert dialog.move_down.isEnabled()
        first = dialog.conditions()[0]
        dialog.move_down.click()
        assert dialog.conditions()[1] == first
        assert dialog.move_up.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_settings_lists_are_edited_in_a_detail_form(app, tmp_path):
    dialog = SettingsDialog(Config(base_dir=tmp_path), [])
    try:
        links = dialog.links
        links.add_button.click()
        links.inputs["name"].setText("Proof house")
        links.inputs["url"].setText("https://proof.test/{serial}")
        assert dialog.serial_links()[-1].name == "Proof house"
        assert links.list.currentItem().text() == "Proof house"
        links.remove_button.click()
        assert all(link.name != "Proof house" for link in dialog.serial_links())

        editor = dialog.conditions_editor
        editor.list.setCurrentRow(0)
        note = editor.inputs["note"]
        note.setPlainText("A longer sentence that wraps in the editor.")
        assert (
            dialog.conditions()[0].note == "A longer sentence that wraps in the editor."
        )
        # Selecting another row shows that row's own values.
        editor.list.setCurrentRow(1)
        assert editor.inputs["name"].text() == dialog.conditions()[1].name
    finally:
        dialog.deleteLater()
        app.processEvents()
