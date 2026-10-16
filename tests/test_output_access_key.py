from PySide6.QtWidgets import QApplication

from simple_auction.services import api_key
from simple_auction.services.config import Config
from simple_auction.ui.settings import SettingsDialog


def test_settings_has_no_visible_output_access_field(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(api_key, "saved", lambda: None)
    dialog = SettingsDialog(Config(base_dir=tmp_path), [])
    assert not hasattr(dialog, "access_key")
    dialog.deleteLater()
    app.processEvents()


def test_root_in_the_gemini_field_unlocks_output_without_replacing_the_key(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    stored = {"gemini": "existing-gemini-key"}
    monkeypatch.setattr(api_key, "saved", lambda: stored["gemini"])
    monkeypatch.setattr(api_key, "save", lambda key: stored.update(gemini=key))
    dialog = SettingsDialog(Config(base_dir=tmp_path), [])
    dialog.key.setText("root")
    assert dialog.history_access()
    assert dialog.new_api_key() is None  # root is never a replacement Gemini key
    if key := dialog.new_api_key():
        api_key.save(key)
    assert stored["gemini"] == "existing-gemini-key"
    dialog._lock_history()
    assert not dialog.history_access()
    assert stored["gemini"] == "existing-gemini-key"
    dialog.deleteLater()
    app.processEvents()


def test_an_ordinary_gemini_key_does_not_unlock_output(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(api_key, "saved", lambda: "existing-gemini-key")
    dialog = SettingsDialog(Config(base_dir=tmp_path), [])
    dialog.key.setText("replacement-gemini-key")
    assert not dialog.history_access()
    assert dialog.new_api_key() == "replacement-gemini-key"
    dialog.deleteLater()
    app.processEvents()
