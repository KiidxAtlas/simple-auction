import io
from contextlib import contextmanager
from pathlib import Path

from openpyxl import Workbook, load_workbook

from simple_auction.models import Lot
from simple_auction.services import storage

HEADERS = ["Lot", "Serial", "Condition", "Title", "Desc", "Owner", "Book #", "Year"]


class ExcelLockedError(Exception):
    """The workbook is open in Excel and can't be written."""


def auction_path(folder: Path, auction_no: int) -> Path:
    return folder / f"{auction_no}.xlsx"


def list_auctions(folder: Path) -> list[int]:
    """Auction numbers, parsed from filenames like 41000.xlsx."""
    with storage.lock:
        if not folder.exists():
            return []
        for journal in folder.glob(".*.xlsx.transaction"):
            storage.recover(journal)
        return sorted(
            int(p.stem)
            for p in folder.glob("*.xlsx")
            if p.stem.isdigit() and not p.name.startswith("~$")
        )


def create_auction(path: Path) -> None:
    with storage.lock:
        storage.recover(storage.journal_path(path))
        wb = Workbook()
        try:
            wb.active.append(HEADERS)
            _save(wb, path)
        finally:
            wb.close()


def load_auction(path: Path) -> list[Lot]:
    with storage.lock:
        storage.recover(storage.journal_path(path))
        wb = load_workbook(path, read_only=True)
        try:
            rows = wb.active.iter_rows(min_row=2, values_only=True)
            return [_row_to_lot(row) for row in rows if row[0] is not None]
        finally:
            wb.close()


def save_lot(path: Path, lot: Lot) -> None:
    with _edit_workbook(path) as wb:
        _put_lot(wb, lot)
        _save(wb, path)


def prepare_add(path: Path, lots: list[Lot]) -> tuple[bytes, list[Lot]]:
    with _edit_workbook(path) as wb:
        existing = {c[0].value for c in wb.active.iter_rows(min_row=2)}
        added = []
        for lot in sorted(lots, key=lambda x: x.lot_number):
            if lot.lot_number not in existing:
                wb.active.append(_lot_to_row(lot))
                existing.add(lot.lot_number)
                added.append(lot)
        return _encode(wb), added


def prepare_delete(path: Path, lot_numbers: set[int]) -> bytes:
    with _edit_workbook(path) as wb:
        if not path.exists():
            raise FileNotFoundError(path)
        rows = [
            c[0].row
            for c in wb.active.iter_rows(min_row=2)
            if c[0].value in lot_numbers
        ]
        for row in reversed(rows):
            wb.active.delete_rows(row)
        return _encode(wb)


def add_lots(path: Path, lots: list[Lot]) -> list[Lot]:
    """Append lots the workbook doesn't have yet (by lot number), in one save.
    Existing lots are left untouched. Returns the lots that were added."""
    with storage.lock:
        data, added = prepare_add(path, lots)
        _write_data(path, data)
        return added


def delete_lots(path: Path, lot_numbers: set[int]) -> None:
    with storage.lock:
        _write_data(path, prepare_delete(path, lot_numbers))


@contextmanager
def _edit_workbook(path: Path):
    with storage.lock:
        storage.recover(storage.journal_path(path))
        wb = load_workbook(path) if path.exists() else Workbook()
        try:
            if not path.exists():
                wb.active.append(HEADERS)
            yield wb
        finally:
            wb.close()


def _put_lot(wb, lot: Lot) -> None:
    ws = wb.active
    row = _lot_to_row(lot)
    for cells in ws.iter_rows(min_row=2):
        if cells[0].value == lot.lot_number:
            for cell, value in zip(cells, row):
                cell.value = value
            break
    else:
        ws.append(row)


def _encode(wb) -> bytes:
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def prepare_lot(path: Path, lot: Lot) -> bytes:
    """Encode an update without changing the original workbook."""
    with _edit_workbook(path) as wb:
        _put_lot(wb, lot)
        return _encode(wb)


def _save(wb, path: Path) -> None:
    _write_data(path, _encode(wb))


def _write_data(path: Path, data: bytes) -> None:
    try:
        storage.atomic_write(path, data)
    except PermissionError as e:
        raise ExcelLockedError(path) from e


def _lot_to_row(lot: Lot) -> list:
    return [
        lot.lot_number,
        lot.serial,
        lot.condition,
        lot.title,
        lot.desc,
        lot.owner,
        lot.book_no,
        lot.year,
    ]


def _row_to_lot(row: tuple) -> Lot:
    cells = list(row) + [None] * (len(HEADERS) - len(row))
    lot_no, serial, condition, title, desc, owner, book_no, year = cells[: len(HEADERS)]
    return Lot(
        lot_number=int(lot_no),
        serial=serial or "",
        condition=str(condition).strip() if condition is not None else "",
        title=title or "",
        desc=desc or "",
        owner=owner or "",
        book_no=str(book_no) if book_no is not None else "",
        year=int(year) if year else None,
    )
