"""Lot fields that aren't Excel columns, in a side file per auction."""

import json
from copy import deepcopy
from pathlib import Path

from simple_auction.models import Lot
from simple_auction.services import dossier, storage
from simple_auction.services.title_layout import validate, validate_values

_DEFAULTS = {
    "make": "",
    "model": "",
    "barrel_length": "",
    "caliber": "",
    "gun_type": "",
    "ca_legality": "N/A",
    "c_and_r": False,
    "title_fields": None,
    "custom": {},
    "dossier": {},
}
_FIELDS = tuple(_DEFAULTS)
_STRUCTURED = {"title_fields", "custom", "dossier"}
_FLAGS = {"c_and_r"}  # true/false values


def details_path(folder: Path, auction_no: int) -> Path:
    return folder / f"{auction_no} details.json"


class DetailsFileError(ValueError):
    """The details file cannot safely be read or overwritten."""


def _read(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        raise DetailsFileError(
            f"Cannot read {path}: {e}. The file was not overwritten."
        ) from e
    if not isinstance(data, dict) or any(
        not isinstance(key, str)
        or not isinstance(entry, dict)
        or any(
            not isinstance(value, bool if name in _FLAGS else str)
            for name, value in entry.items()
            if name not in _STRUCTURED
        )
        for key, entry in data.items()
    ):
        raise DetailsFileError(
            f"Invalid details in {path}. The file was not overwritten."
        )
    try:
        for entry in data.values():
            if "title_fields" in entry:
                validate(entry["title_fields"])
            if "custom" in entry:
                validate_values(entry["custom"])
            if "dossier" in entry:
                dossier.validate(entry["dossier"])
    except (ValueError, TypeError) as e:
        raise DetailsFileError(f"Invalid title layout in {path}: {e}") from e
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.atomic_write(path, _encode(data))


def _encode(data: dict) -> bytes:
    return json.dumps(data, indent=2, sort_keys=True).encode("utf-8")


def prepare(path: Path, lots: list[Lot]) -> bytes:
    """Validate and encode updates without modifying the sidecar."""
    data = _read(path)
    for lot in lots:
        dossier.validate(lot.dossier)
        entry = {
            name: getattr(lot, name)
            for name in _FIELDS
            if getattr(lot, name) != _DEFAULTS[name]
        }
        if entry:
            data[str(lot.lot_number)] = entry
        else:
            data.pop(str(lot.lot_number), None)
    return _encode(data)


def prepare_delete(path: Path, lot_numbers: set[int]) -> bytes:
    data = _read(path)
    for number in lot_numbers:
        data.pop(str(number), None)
    return _encode(data)


def fill(path: Path, lots: list[Lot]) -> None:
    """Copy the stored details onto lots loaded from Excel."""
    data = _read(path)
    for lot in lots:
        for name in _FIELDS:
            value = data.get(str(lot.lot_number), {}).get(name, _DEFAULTS[name])
            setattr(lot, name, deepcopy(value))


def save(path: Path, lot: Lot) -> None:
    save_many(path, [lot])


def save_many(path: Path, lots: list[Lot]) -> None:
    """Like save() for each lot, with one read and one write."""
    data = prepare(path, lots)
    if data != b"{}" or path.exists():
        storage.atomic_write(path, data)


def delete(path: Path, lot_numbers: set[int]) -> None:
    data = _read(path)
    removed = [data.pop(str(n), None) for n in lot_numbers]
    if any(r is not None for r in removed):
        _write(path, data)
