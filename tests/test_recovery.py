import base64
import json
from dataclasses import replace

import pytest
from PIL import Image

from simple_auction.models import Lot
from simple_auction.services import catalogue, excel, lot_details, network, recovery
from simple_auction.services.config import Config


@pytest.fixture
def saved(tmp_path):
    config = Config(base_dir=tmp_path / "main", photos_dir=tmp_path / "photos")
    workbook = excel.auction_path(config.auctions_dir, 41000)
    details = lot_details.details_path(config.data_dir, 41000)
    photos = config.auction_photos_dir(41000)
    photos.mkdir(parents=True)
    photo = photos / "41001.jpg"
    Image.new("RGB", (12, 12), "red").save(photo)
    lot = Lot(41001, title="Original", make="Maker", photos=[photo])
    catalogue.save(workbook, details, photos, lot)
    return config, workbook, details, photos, lot


def test_local_delete_survives_reopen_and_restores_details_photos(saved):
    config, workbook, details, photos, lot = saved
    original = (photos / "41001.jpg").read_bytes()
    catalogue.delete(workbook, details, photos, {41001})
    entry = recovery.list_local(replace(config))[0]
    assert entry["kind"] == "lots"
    assert catalogue.load(workbook, details) == []
    recovery.restore_local(replace(config), entry["id"])
    assert catalogue.load(workbook, details)[0].make == lot.make
    assert (photos / "41001.jpg").read_bytes() == original
    with pytest.raises(ValueError, match="number"):
        recovery.restore_local(config, entry["id"])


def test_local_archive_failure_stops_deletion_and_edit(saved, monkeypatch):
    _, workbook, details, photos, lot = saved
    before = workbook.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("archive disk unavailable")

    monkeypatch.setattr(recovery, "archive_local", fail)
    with pytest.raises(OSError):
        catalogue.delete(workbook, details, photos, {41001})
    with pytest.raises(OSError):
        catalogue.save(workbook, details, photos, replace(lot, title="New"))
    with pytest.raises(OSError):
        catalogue.delete_auction(workbook, details, photos)
    assert workbook.read_bytes() == before
    assert (photos / "41001.jpg").exists()


def test_local_auction_recovery_and_collision(saved):
    config, workbook, details, photos, _ = saved
    catalogue.delete_auction(workbook, details, photos)
    entry = recovery.list_local(config)[0]
    assert not workbook.exists()
    recovery.restore_local(config, entry["id"])
    assert catalogue.load(workbook, details)[0].title == "Original"
    with pytest.raises(ValueError, match="already in use"):
        recovery.restore_local(config, entry["id"])


def test_removed_photos_and_text_revision_export_without_overwrite(saved, tmp_path):
    config, workbook, details, photos, lot = saved
    raw = lot.photos[0].read_bytes()
    catalogue.save(workbook, details, photos, replace(lot, title="New", photos=[]))
    entry = recovery.list_local(config)[0]
    assert entry["kind"] == "revision"
    destination = tmp_path / "snapshot"
    recovery.export_local(config, entry["id"], destination)
    assert (
        json.loads((destination / "snapshot.json").read_text())["lots"][0]["title"]
        == "Original"
    )
    assert (destination / "41001.jpg").read_bytes() == raw
    with pytest.raises(FileExistsError):
        recovery.export_local(config, entry["id"], destination)
    with pytest.raises(ValueError, match="Export"):
        recovery.restore_local(config, entry["id"])


def test_archive_paths_cannot_escape_export(tmp_path):
    payload = {"photos": {"../escape.jpg": base64.b64encode(b"bad").decode()}}
    with pytest.raises(ValueError, match="Unsafe"):
        recovery.export_snapshot(payload, tmp_path / "export")
    assert not (tmp_path / "escape.jpg").exists()


def test_arbitrary_sidecar_filename_remains_supported(saved):
    _, workbook, details, photos, lot = saved
    renamed = details.with_name("1.json")
    details.rename(renamed)
    catalogue.save(workbook, renamed, photos, replace(lot, title="Changed"))
    catalogue.delete(workbook, renamed, photos, {41001})


def test_shared_delete_restore_after_restart_and_collision(saved):
    config, _, _, _, _ = saved
    db = network.Database(config)
    expected = db.dispatch("snapshot", {})["auctions"]["41000"]
    db.dispatch("delete", {"auction": 41000, "numbers": None, "expected": expected})
    reopened = network.Database(config)
    entry = reopened.dispatch("recovery_list", {})[0]
    assert entry["kind"] == "auction"
    reopened.dispatch("recovery_restore", {"id": entry["id"]})
    assert reopened.dispatch("snapshot", {})["auctions"]["41000"] == expected
    with pytest.raises(network.Conflict):
        reopened.dispatch("recovery_restore", {"id": entry["id"]})


def test_shared_archive_failure_rolls_back_delete(saved, monkeypatch):
    config, _, _, _, _ = saved
    db = network.Database(config)
    expected = db.dispatch("snapshot", {})["auctions"]["41000"]

    def fail(*args):
        raise OSError("archive disk full")

    monkeypatch.setattr(recovery, "archive", fail)
    with pytest.raises(OSError):
        db.dispatch(
            "delete", {"auction": 41000, "numbers": [41001], "expected": expected}
        )
    assert db.dispatch("snapshot", {})["auctions"]["41000"] == expected


def test_shared_removed_photos_are_available_in_revision(saved):
    config, _, _, _, _ = saved
    db = network.Database(config)
    old = db.dispatch("snapshot", {})["auctions"]["41000"][0]
    db.dispatch(
        "save_lot",
        {
            "auction": 41000,
            "lot": {k: v for k, v in old.items() if k != "photos"},
            "photos": [],
            "expected": old,
        },
    )
    entry = db.dispatch("recovery_list", {})[0]
    payload = db.dispatch("recovery_get", {"id": entry["id"]})
    assert payload["kind"] == "revision"
    assert "41001.jpg" in recovery.decode_photos(payload)
