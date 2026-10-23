"""Coordinate the workbook, sidecar and photos as one recoverable save."""

import logging
from copy import deepcopy
from pathlib import Path

from simple_auction.models import Lot
from simple_auction.services import excel, image, lot_details, recovery, storage

log = logging.getLogger(__name__)


class CatalogueReadError(ValueError):
    """A catalogue cannot safely be opened for editing."""


def load(workbook: Path, details: Path) -> list[Lot]:
    with storage.lock:
        storage.recover(storage.journal_path(workbook))
        if not workbook.exists():
            return []
        try:
            lots = excel.load_auction(workbook)
            lot_details.fill(details, lots)
            return lots
        except Exception as e:
            log.exception("Cannot read catalogue %s", workbook)
            raise CatalogueReadError(str(e)) from e


def _commit(workbook: Path, changes: dict[Path, bytes | None]) -> None:
    try:
        storage.commit(changes, storage.journal_path(workbook))
    except PermissionError as e:
        # Only a workbook permission failure is plausibly an Excel lock. Other
        # destinations keep their actual error/path for the UI.
        failed_path = e.filename2 or e.filename
        if failed_path and Path(failed_path).resolve() == workbook.resolve():
            raise excel.ExcelLockedError(workbook) from e
        raise


def save(
    workbook: Path,
    details: Path,
    photos_dir: Path,
    lot: Lot,
) -> tuple[list[Path], dict[Path, bytes]]:
    with storage.lock:
        storage.recover(storage.journal_path(workbook))
        # Validate sidecar before doing expensive image work or touching files.
        details_data = lot_details.prepare(details, [lot])
        workbook_data = excel.prepare_lot(workbook, lot)
        changes, photos = image.prepare_photos(lot.lot_number, lot.photos, photos_dir)
        removed = {p: p.read_bytes() for p, data in changes.items() if data is None}
        changes[workbook] = workbook_data
        changes[details] = details_data
        previous = load(workbook, details)
        old = next((v for v in previous if v.lot_number == lot.lot_number), None)
        if old is not None:
            old_photos = {
                p: p.read_bytes()
                for p in image.lot_photo_files(lot.lot_number, photos_dir)
            }
            if any(
                getattr(old, k) != getattr(lot, k) for k in vars(old) if k != "photos"
            ) or any(p not in {workbook, details} for p in changes):
                recovery.archive_local(
                    details, "revision", [old], old_photos, workbook=workbook
                )
        _commit(workbook, changes)
        return photos, removed


def add(workbook: Path, details: Path, lots: list[Lot]) -> list[Lot]:
    with storage.lock:
        storage.recover(storage.journal_path(workbook))
        workbook_data, added = excel.prepare_add(workbook, lots)
        details_data = lot_details.prepare(details, added)
        if added:
            _commit(workbook, {workbook: workbook_data, details: details_data})
        return added


def delete(
    workbook: Path,
    details: Path,
    photos_dir: Path,
    numbers: set[int],
) -> dict[Path, bytes]:
    with storage.lock:
        storage.recover(storage.journal_path(workbook))
        details_data = lot_details.prepare_delete(details, numbers)
        workbook_data = excel.prepare_delete(workbook, numbers)
        removed = {
            p: p.read_bytes()
            for number in numbers
            for p in image.lot_photo_files(number, photos_dir)
        }
        saved = [v for v in load(workbook, details) if v.lot_number in numbers]
        recovery.archive_local(details, "lots", saved, removed, workbook=workbook)
        changes = dict.fromkeys(removed)
        changes[workbook] = workbook_data
        changes[details] = details_data
        _commit(workbook, changes)
        return removed


def restore(
    workbook: Path,
    details: Path,
    lots: list[Lot],
    photos: dict[Path, bytes],
) -> None:
    """Put deleted lots (and their photo files) back, as delete() undone."""
    with storage.lock:
        storage.recover(storage.journal_path(workbook))
        workbook_data, added = excel.prepare_add(workbook, lots)
        if len(added) != len(lots):
            raise ValueError("A lot with that number has been added since.")
        details_data = lot_details.prepare(details, added)
        if any(p.exists() for p in photos):
            raise ValueError(
                "A photo with that name already exists; nothing was overwritten."
            )
        changes: dict[Path, bytes | None] = dict(photos)
        changes[workbook] = workbook_data
        changes[details] = details_data
        _commit(workbook, changes)


def delete_auction(workbook: Path, details: Path, photos_dir: Path) -> None:
    """Archive all lots/photos durably before the transactional removal."""
    with storage.lock:
        lots = load(workbook, details)
        photos = {p: p.read_bytes() for p in photos_dir.glob("*.jpg")}
        recovery.archive_local(details, "auction", lots, photos, workbook=workbook)
        changes = dict.fromkeys(photos)
        changes[workbook] = None
        changes[details] = None
        _commit(workbook, changes)
        # Empty directories are not transaction data. Leave unknown files alone.
        if photos_dir.exists() and not any(photos_dir.iterdir()):
            photos_dir.rmdir()


class Cache:
    """Reuse unchanged auctions; file metadata invalidates external edits too."""

    def __init__(self) -> None:
        self._entries: dict[tuple[Path, Path], tuple[tuple, list[Lot]]] = {}

    def load(self, workbook: Path, details: Path) -> list[Lot]:
        with storage.lock:
            storage.recover(storage.journal_path(workbook))
            key = (workbook.resolve(), details.resolve())
            stamp = tuple(
                (p.stat().st_mtime_ns, p.stat().st_ctime_ns, p.stat().st_size)
                if p.exists()
                else None
                for p in key
            )
            entry = self._entries.get(key)
            if entry is None or entry[0] != stamp:
                entry = (stamp, load(workbook, details))
                self._entries[key] = entry
            return deepcopy(entry[1])
