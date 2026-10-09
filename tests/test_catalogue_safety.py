import errno
import json
import subprocess
import sys

import pytest
from PIL import Image, UnidentifiedImageError

from simple_auction.models import Lot
from simple_auction.services import catalogue, excel, image, lot_details, storage
from simple_auction.services.config import Config, ConfigFileError


@pytest.fixture
def saved(tmp_path):
    workbook = tmp_path / "auctions" / "41000.xlsx"
    details = tmp_path / "data" / "41000 details.json"
    photos = tmp_path / "photos"
    photos.mkdir()
    first, second = photos / "41001.jpg", photos / "41001-1.jpg"
    Image.new("RGB", (100, 100), "red").save(first)
    Image.new("RGB", (100, 100), "blue").save(second)
    lot = Lot(
        lot_number=41001, title="Original", make="Original", photos=[first, second]
    )
    catalogue.save(workbook, details, photos, lot)
    return workbook, details, photos, lot


def _snapshot(workbook, details, photos):
    return {p: p.read_bytes() for p in [workbook, details, *photos.glob("*.jpg")]}


def test_invalid_new_photo_preserves_all_originals(saved, tmp_path):
    workbook, details, photos, lot = saved
    before = _snapshot(workbook, details, photos)
    bad = tmp_path / "invalid.jpg"
    bad.write_bytes(b"not an image")
    lot.title = "Changed"
    lot.photos = [lot.photos[1], bad]
    with pytest.raises(UnidentifiedImageError):
        catalogue.save(workbook, details, photos, lot)
    assert _snapshot(workbook, details, photos) == before


def test_photo_helper_does_not_delete_old_photos_on_invalid_input(saved, tmp_path):
    _, _, photos, lot = saved
    before = {p: p.read_bytes() for p in lot.photos}
    bad = tmp_path / "invalid.jpg"
    bad.write_bytes(b"invalid")
    with pytest.raises(UnidentifiedImageError):
        image.process_photos(lot.lot_number, [bad], photos)
    assert {p: p.read_bytes() for p in lot.photos} == before


@pytest.mark.parametrize("failure", ["workbook", "details", "photo"])
def test_save_failure_rolls_back_every_file_and_retry_works(
    saved, monkeypatch, failure
):
    workbook, details, photos, lot = saved
    before = _snapshot(workbook, details, photos)
    failed_path = {"workbook": workbook, "details": details, "photo": lot.photos[0]}[
        failure
    ]
    real = storage.atomic_write
    failed = False

    def fail_once(path, data):
        nonlocal failed
        if path == failed_path and not failed:
            failed = True
            raise PermissionError(errno.EACCES, "denied", str(path))
        real(path, data)

    monkeypatch.setattr(storage, "atomic_write", fail_once)
    lot.title = "Changed"
    lot.make = "Changed"
    lot.photos = [lot.photos[1]]
    expected = excel.ExcelLockedError if failure == "workbook" else PermissionError
    with pytest.raises(expected):
        catalogue.save(workbook, details, photos, lot)
    assert _snapshot(workbook, details, photos) == before
    assert not storage.journal_path(workbook).exists()
    out, _ = catalogue.save(workbook, details, photos, lot)
    assert out == [photos / "41001.jpg"]
    assert out[0].read_bytes() == before[photos / "41001-1.jpg"]
    loaded = catalogue.load(workbook, details)
    assert loaded[0].title == loaded[0].make == "Changed"
    assert not (photos / "41001-1.jpg").exists()


@pytest.mark.parametrize(
    "raw", [b"{", b"[]", b'{"41001": null}', b'{"41001": {"make": 42}}']
)
def test_bad_sidecar_is_reported_and_never_overwritten(saved, raw):
    workbook, details, photos, lot = saved
    details.write_bytes(raw)
    before = _snapshot(workbook, details, photos)
    with pytest.raises(lot_details.DetailsFileError):
        lot_details.save(details, Lot(lot_number=41002, make="New"))
    with pytest.raises(lot_details.DetailsFileError):
        catalogue.save(workbook, details, photos, lot)
    with pytest.raises(catalogue.CatalogueReadError):
        catalogue.load(workbook, details)
    assert _snapshot(workbook, details, photos) == before


def test_import_and_delete_are_coordinated(saved, monkeypatch):
    workbook, details, photos, lot = saved
    before = _snapshot(workbook, details, photos)
    real = storage.atomic_write

    def fail_details(path, data):
        if path == details and data != before[details]:
            raise OSError("details disk full")
        real(path, data)

    monkeypatch.setattr(storage, "atomic_write", fail_details)
    with pytest.raises(OSError, match="details disk full"):
        catalogue.add(workbook, details, [Lot(lot_number=41002, make="New")])
    assert _snapshot(workbook, details, photos) == before
    with pytest.raises(OSError, match="details disk full"):
        catalogue.delete(workbook, details, photos, {lot.lot_number})
    assert _snapshot(workbook, details, photos) == before


def test_photo_reorder_and_duplicate_keep_original_bytes(saved):
    workbook, details, photos, lot = saved
    a, b = (p.read_bytes() for p in lot.photos)
    lot.photos = [lot.photos[1], lot.photos[0], lot.photos[1]]
    out, _ = catalogue.save(workbook, details, photos, lot)
    assert [p.read_bytes() for p in out] == [b, a, b]


def test_cache_reuses_unchanged_workbooks_and_invalidates_sidecar(saved, monkeypatch):
    workbook, details, _, _ = saved
    cache = catalogue.Cache()
    real = excel.load_auction
    calls = []

    def count(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(excel, "load_auction", count)
    first = cache.load(workbook, details)
    first[0].title = "Must not mutate cache"
    assert cache.load(workbook, details)[0].title == "Original"
    assert len(calls) == 1
    lot_details.save(details, Lot(lot_number=41001, make="External"))
    assert cache.load(workbook, details)[0].make == "External"
    assert len(calls) == 2
    excel.save_lot(workbook, Lot(lot_number=41001, title="External workbook"))
    assert cache.load(workbook, details)[0].title == "External workbook"
    assert len(calls) == 3


@pytest.mark.parametrize(
    "raw", [b"{", b"[]", b'{"base_dir": 12}', b'{"step": 0}', b'{"start_at": "wrong"}']
)
def test_config_failure_preserves_file_and_does_not_switch_folders(tmp_path, raw):
    path = tmp_path / "config.json"
    path.write_bytes(raw)
    with pytest.raises(ConfigFileError):
        Config.load(path)
    with pytest.raises(ConfigFileError):
        Config(base_dir=tmp_path).save(path)
    assert path.read_bytes() == raw


def test_explicit_config_recovery_keeps_damaged_copy_and_restores_custom_folders(
    tmp_path,
):
    path = tmp_path / "config.json"
    config = Config(base_dir=tmp_path / "custom", photos_dir=tmp_path / "pictures")
    config.save(path)
    config.save(path)  # creates the known-good backup
    path.write_bytes(b"damaged")
    restored = Config.recover(path)
    assert restored.base_dir == config.base_dir
    assert restored.photos_dir == config.photos_dir
    assert Config.load(path).base_dir == config.base_dir
    copies = list(tmp_path.glob("config.json.invalid-*"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == b"damaged"


def test_config_failed_save_keeps_readable_previous_settings(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    config = Config(base_dir=tmp_path / "custom")
    config.save(path)
    before = path.read_bytes()
    config.step += 1
    real = storage.atomic_write

    def fail(path_, data):
        if path_ == path:
            raise OSError("disk full")
        real(path_, data)

    monkeypatch.setattr(storage, "atomic_write", fail)
    with pytest.raises(OSError):
        config.save(path)
    assert path.read_bytes() == before
    assert json.loads(path.read_bytes())["step"] != config.step


def test_startup_recovers_after_process_exits_mid_commit(saved):
    workbook, details, photos, _ = saved
    before = _snapshot(workbook, details, photos)
    code = """
import os
import sys
from pathlib import Path
from simple_auction.models import Lot
from simple_auction.services import catalogue, storage
workbook, details, photos = map(Path, sys.argv[1:])
real_write = storage.atomic_write
def interrupted(path, data):
    if path == details:
        os._exit(17)
    real_write(path, data)
storage.atomic_write = interrupted
lot = Lot(lot_number=41001, title='Interrupted', make='Changed', photos=[photos / '41001-1.jpg'])
catalogue.save(workbook, details, photos, lot)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(workbook), str(details), str(photos)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 17, result.stderr
    assert storage.journal_path(workbook).exists()
    assert workbook.read_bytes() != before[workbook]
    # This is the actual startup discovery entry point, not a manual recovery.
    assert excel.list_auctions(workbook.parent) == [41000]
    assert _snapshot(workbook, details, photos) == before
    assert not storage.journal_path(workbook).exists()


def test_recovery_handles_uncreated_destination_directories(tmp_path, monkeypatch):
    first, second = tmp_path / "first" / "file", tmp_path / "second" / "file"
    journal = tmp_path / "journal"
    real_write = storage.atomic_write

    def fail(path, data):
        if path == first:
            raise OSError("disk full")
        real_write(path, data)

    monkeypatch.setattr(storage, "atomic_write", fail)
    with pytest.raises(OSError, match="disk full"):
        storage.commit({first: b"new", second: b"new"}, journal)
    assert not first.exists() and not second.exists()
    assert not journal.exists()


def test_delete_missing_workbook_does_not_recreate_it_or_remove_other_data(saved):
    workbook, details, photos, lot = saved
    workbook.unlink()
    before = {p: p.read_bytes() for p in [details, *photos.glob("*.jpg")]}
    with pytest.raises(FileNotFoundError):
        catalogue.delete(workbook, details, photos, {lot.lot_number})
    assert not workbook.exists()
    assert {p: p.read_bytes() for p in before} == before


def test_empty_details_batch_does_not_create_sidecar(tmp_path):
    path = tmp_path / "details.json"
    lot_details.save_many(path, [Lot(lot_number=41001)])
    assert not path.exists()
