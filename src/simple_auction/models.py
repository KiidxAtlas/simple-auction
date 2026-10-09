from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Lot:
    lot_number: int
    serial: str = ""
    # One of the condition names from Settings (plain text, so it survives
    # the condition being renamed or removed there).
    condition: str = ""
    title: str = ""
    desc: str = ""
    owner: str = ""
    book_no: str = ""
    year: int | None = None
    photos: list[Path] = field(default_factory=list)
    # Not Excel columns: kept in a side file, used for research and to fill
    # the start of the title and description.
    make: str = ""
    model: str = ""
