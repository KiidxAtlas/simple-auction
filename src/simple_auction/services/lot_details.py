"""Lot fields that aren't Excel columns (make, model), in a side file per
auction next to its workbook: "41000 details.json"."""

import json
from pathlib import Path

from simple_auction.models import Lot

_FIELDS = ("make", "model")


def details_path(folder: Path, auction_no: int) -> Path:
    return folder / f"{auction_no} details.json"


def _read(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def fill(path: Path, lots: list[Lot]) -> None:
    """Copy the stored details onto lots loaded from Excel."""
    data = _read(path)
    for lot in lots:
        for name in _FIELDS:
            setattr(lot, name, str(data.get(str(lot.lot_number), {}).get(name, "")))


def save(path: Path, lot: Lot) -> None:
    data = _read(path)
    entry = {name: getattr(lot, name) for name in _FIELDS if getattr(lot, name)}
    key = str(lot.lot_number)
    if entry:
        data[key] = entry
    else:
        data.pop(key, None)
    if data or path.exists():
        _write(path, data)


def save_many(path: Path, lots: list[Lot]) -> None:
    """Like save() for each lot, with one read and one write."""
    data = _read(path)
    for lot in lots:
        entry = {name: getattr(lot, name) for name in _FIELDS if getattr(lot, name)}
        if entry:
            data[str(lot.lot_number)] = entry
        else:
            data.pop(str(lot.lot_number), None)
    if data or path.exists():
        _write(path, data)


def delete(path: Path, lot_numbers: set[int]) -> None:
    data = _read(path)
    removed = [data.pop(str(n), None) for n in lot_numbers]
    if any(r is not None for r in removed):
        _write(path, data)
