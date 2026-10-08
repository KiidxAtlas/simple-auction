from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Condition(StrEnum):
    LIKE_NEW = "Like New"
    EXCELLENT = "Excellent"
    GOOD = "Good"
    FAIR = "Fair"


@dataclass
class Lot:
    lot_number: int
    serial: str = ""
    condition: Condition = Condition.LIKE_NEW
    title: str = ""
    desc: str = ""
    owner: str = ""
    book_no: str = ""
    year: int | None = None
    photos: list[Path] = field(default_factory=list)
