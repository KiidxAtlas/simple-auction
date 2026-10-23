from PySide6.QtWidgets import QMessageBox

from simple_auction.models import Lot
from simple_auction.services import catalogue, excel, lot_details, recovery
from simple_auction.services.config import Config
from simple_auction.ui.recovery_dialog import RecoveryDialog


def test_dialog_restores_persistent_deletion(tmp_path, monkeypatch):
    config = Config(base_dir=tmp_path / "main", photos_dir=tmp_path / "photos")
    workbook = excel.auction_path(config.auctions_dir, 41000)
    details = lot_details.details_path(config.data_dir, 41000)
    catalogue.add(workbook, details, [Lot(41001, title="Recover me")])
    catalogue.delete(workbook, details, config.auction_photos_dir(41000), {41001})
    monkeypatch.setattr(RecoveryDialog, "io", lambda self, callback: callback())
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    dialog = RecoveryDialog(config)
    dialog.items.setCurrentRow(0)
    assert dialog.restore_button.isEnabled()
    dialog.restore_selected()
    assert catalogue.load(workbook, details)[0].title == "Recover me"
    assert recovery.list_local(config)
    dialog.close()


def test_dialog_revision_export_only_and_shared_source(tmp_path, monkeypatch):
    config = Config(base_dir=tmp_path / "main", photos_dir=tmp_path / "photos")
    calls = []

    class Client:
        def request(self, op, **kwargs):
            calls.append(op)
            return [
                {
                    "id": "a" * 32,
                    "created": "2026-10-20",
                    "kind": "revision",
                    "auction": 41000,
                }
            ]

    monkeypatch.setattr(RecoveryDialog, "io", lambda self, callback: callback())
    dialog = RecoveryDialog(config, Client())
    dialog.items.setCurrentRow(0)
    assert calls == ["recovery_list"]
    assert not dialog.restore_button.isEnabled()
    dialog.source.setCurrentIndex(1)
    assert "No recovery history" in dialog.items.item(0).text()
    dialog.close()
