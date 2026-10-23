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
    barrel_length: str = ""
    caliber: str = ""
    gun_type: str = ""  # Rifle, Shotgun, Handgun (or anything typed)
    ca_legality: str = "N/A"
    # Curio & Relic eligible (written into the title as "C&R").
    c_and_r: bool = False
    # Layout used to generate this saved title; None means the legacy layout.
    title_fields: list[str] | None = None
    # Values of the custom fields defined in Settings: {field id: text}.
    custom: dict[str, str] = field(default_factory=dict)
    # Portable identification evidence, research and publication review state.
    dossier: dict = field(default_factory=dict)
