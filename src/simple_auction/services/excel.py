from pathlib import Path

from openpyxl import Workbook, load_workbook

from simple_auction.models import Condition, Lot

HEADERS = ["Lot", "Serial", "Condition", "Title", "Desc", "Owner", "Book #", "Year"]


class ExcelLockedError(Exception):
    """The workbook is open in Excel and can't be written."""


def auction_path(folder: Path, auction_no: int) -> Path:
    return folder / f"{auction_no}.xlsx"


def list_auctions(folder: Path) -> list[int]:
    """Auction numbers, parsed from filenames like 41000.xlsx."""
    if not folder.exists():
        return []
    return sorted(
        int(p.stem)
        for p in folder.glob("*.xlsx")
        if p.stem.isdigit() and not p.name.startswith("~$")
    )


def create_auction(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.active.append(HEADERS)
    wb.save(path)


def load_auction(path: Path) -> list[Lot]:
    wb = load_workbook(path, read_only=True)
    try:
        rows = wb.active.iter_rows(min_row=2, values_only=True)
        return [_row_to_lot(row) for row in rows if row[0] is not None]
    finally:
        wb.close()


def save_lot(path: Path, lot: Lot) -> None:
    if not path.exists():
        create_auction(path)
    wb = load_workbook(path)
    ws = wb.active
    row = _lot_to_row(lot)
    for cells in ws.iter_rows(min_row=2):
        if cells[0].value == lot.lot_number:
            for cell, value in zip(cells, row):
                cell.value = value
            break
    else:
        ws.append(row)
    try:
        wb.save(path)
    except PermissionError as e:
        raise ExcelLockedError(path) from e


def delete_lots(path: Path, lot_numbers: set[int]) -> None:
    wb = load_workbook(path)
    ws = wb.active
    rows = [c[0].row for c in ws.iter_rows(min_row=2) if c[0].value in lot_numbers]
    for row in reversed(rows):  # bottom-up so row numbers stay valid
        ws.delete_rows(row)
    try:
        wb.save(path)
    except PermissionError as e:
        raise ExcelLockedError(path) from e


def _lot_to_row(lot: Lot) -> list:
    return [
        lot.lot_number,
        lot.serial,
        lot.condition.value,
        lot.title,
        lot.desc,
        lot.owner,
        lot.book_no,
        lot.year,
    ]


def _row_to_lot(row: tuple) -> Lot:
    cells = list(row) + [None] * (len(HEADERS) - len(row))
    lot_no, serial, condition, title, desc, owner, book_no, year = cells[: len(HEADERS)]
    try:
        cond = Condition(condition)
    except ValueError:
        cond = Condition.LIKE_NEW
    return Lot(
        lot_number=int(lot_no),
        serial=serial or "",
        condition=cond,
        title=title or "",
        desc=desc or "",
        owner=owner or "",
        book_no=str(book_no) if book_no is not None else "",
        year=int(year) if year else None,
    )
