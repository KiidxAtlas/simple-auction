"""Coordinate the workbook, sidecar and photos as one recoverable save."""

import logging
from copy import deepcopy
from pathlib import Path

from simple_auction.models import Lot
from simple_auction.services import excel, image, lot_details, storage

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
        changes = dict.fromkeys(removed)
        changes[workbook] = workbook_data
        changes[details] = details_data
        _commit(workbook, changes)
        return removed


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
