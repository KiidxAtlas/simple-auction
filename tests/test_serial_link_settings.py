from PySide6.QtWidgets import QApplication

from simple_auction.models import Lot
from simple_auction.services.config import Config
from simple_auction.services.serial_links import DEFAULT_LINKS, SerialLink
from simple_auction.ui.components.lot_form import LotForm
from simple_auction.ui.settings import SettingsDialog


def test_all_default_sites_can_be_edited_removed_and_saved(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("simple_auction.ui.settings.api_key.saved", lambda: None)
    cfg = Config(base_dir=tmp_path, photos_dir=tmp_path / "photos")
    dialog = SettingsDialog(cfg, [])
    assert dialog.serial_links() == DEFAULT_LINKS
    colt_row = next(
        i for i, link in enumerate(DEFAULT_LINKS) if link.name == "Colt official"
    )
    dialog.links.list.setCurrentRow(colt_row)
    dialog.links.inputs["name"].setText("My Colt lookup")
    dialog.links.inputs["url"].setText("https://example.com/colt?serial={serial}")
    ruger_row = next(
        i for i, link in enumerate(DEFAULT_LINKS) if link.name == "Ruger official"
    )
    dialog.links.list.setCurrentRow(ruger_row)
    dialog.links.remove_button.click()
    cfg.serial_links = dialog.serial_links()
    path = tmp_path / "config.json"
    cfg.save(path)
    restored = Config.load(path)
    assert restored.serial_links == [
        DEFAULT_LINKS[0],
        SerialLink("My Colt lookup", "https://example.com/colt?serial={serial}"),
        DEFAULT_LINKS[-1],
    ]
    form = LotForm()
    form.load(Lot(1, serial="A123"), 1000)
    form.set_serial_links(restored.serial_links)
    assert [link for _button, link in form._link_buttons] == restored.serial_links
    form.set_serial_links([])
    app.processEvents()
    assert form._link_buttons == []
    assert form.lookup_links.isHidden()
    form.mark_saved()
    form.close()
    dialog.close()
    form.deleteLater()
    dialog.deleteLater()
