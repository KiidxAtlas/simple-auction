"""App settings, and where files live.

<main folder>/
    auctions/   41000.xlsx, 42000.xlsx, ...
    data/       41000 details.json, serial_years.json, conditions.yaml
    photos/     auction 41000 photos/ ...   (photos folder is its own setting)
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from simple_auction.constants import AUCTION_STEP, PHOTO_FOLDER_NAME
from simple_auction.services import conditions, serial_links
from simple_auction.services.conditions import ConditionOption, ConditionsFileError
from simple_auction.services.serial_links import SerialLink

log = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".config" / "simple-auction" / "config.json"


def _default_base_dir() -> Path:
    return Path.home() / "Documents" / "simple-auction"


def _default_photos_dir() -> Path:
    return _default_base_dir() / "photos"


@dataclass
class Config:
    base_dir: Path = field(default_factory=_default_base_dir)
    photos_dir: Path = field(default_factory=_default_photos_dir)
    step: int = AUCTION_STEP
    # Set in Settings to continue from your real series; see next_auction().
    start_at: int | None = None
    # Links shown under the Serial # field.
    serial_links: list[SerialLink] = field(
        default_factory=lambda: list(serial_links.DEFAULT_LINKS)
    )
    # Condition choices, in order; the first is the default for new lots.
    # Kept in data/conditions.yaml (see load_conditions), not config.json.
    conditions: list[ConditionOption] = field(
        default_factory=lambda: list(conditions.DEFAULT_CONDITIONS)
    )
    # Why conditions.yaml couldn't be read at startup, if it couldn't.
    conditions_error: str | None = field(default=None, compare=False)

    @property
    def auctions_dir(self) -> Path:
        """The auction Excel files."""
        return self.base_dir / "auctions"

    @property
    def conditions_path(self) -> Path:
        return self.data_dir / conditions.FILE_NAME

    @property
    def data_dir(self) -> Path:
        """The app's own JSON files (lot details, serial table)."""
        return self.base_dir / "data"

    def auction_photos_dir(self, auction_no: int) -> Path:
        """e.g. <photos_dir>/auction 41000 photos"""
        return self.photos_dir / PHOTO_FOLDER_NAME.format(auction=auction_no)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> Config:
        if not path.exists():
            config = cls()
            config.conditions_error = config.load_conditions()
            return config
        data = json.loads(path.read_text())
        # Older versions called the main folder "auctions_dir".
        base = data.get("base_dir") or data.get("auctions_dir") or _default_base_dir()
        config = cls(
            base_dir=Path(base),
            photos_dir=Path(data.get("photos_dir", _default_photos_dir())),
            step=int(data.get("step", AUCTION_STEP)),
            start_at=data.get("start_at"),
            serial_links=serial_links.from_json(data.get("serial_links")),
        )
        # 0.1.1 kept conditions in config.json; they move to conditions.yaml.
        config.conditions_error = config.load_conditions(data.get("conditions"))
        return config

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "base_dir": str(self.base_dir),
            "photos_dir": str(self.photos_dir),
            "step": self.step,
            "start_at": self.start_at,
            "serial_links": serial_links.to_json(self.serial_links),
        }
        path.write_text(json.dumps(data, indent=2))

    def load_conditions(self, legacy: object = None) -> str | None:
        """Read data/conditions.yaml into `conditions`.

        If the file doesn't exist yet it's created, from `legacy` (conditions
        an older version kept in config.json) or the current list. If it
        exists but can't be read, the current list is kept, the file is left
        untouched, and the problem is returned as a message.
        """
        path = self.conditions_path
        if path.exists():
            try:
                self.conditions = conditions.load_file(path)
            except ConditionsFileError as e:
                log.warning("%s", e)
                return str(e)
            return None
        if legacy is not None:
            self.conditions = conditions.from_json(legacy)
        self.save_conditions()
        return None

    def save_conditions(self) -> None:
        try:
            conditions.save_file(self.conditions_path, self.conditions)
        except OSError as e:
            log.warning("Couldn't write %s: %s", self.conditions_path, e)

    def move_old_files(self) -> None:
        """Move files from the old flat layout into auctions/ and data/.

        Only moves a file if nothing with that name is already at the new place.
        """
        if not self.base_dir.is_dir():
            return
        moves = []
        for p in self.base_dir.iterdir():
            if p.suffix == ".xlsx" and p.stem.isdigit():
                moves.append((p, self.auctions_dir / p.name))
            elif p.name == "serial_years.json" or p.name.endswith(" details.json"):
                moves.append((p, self.data_dir / p.name))
        for src, dest in moves:
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dest)
            log.info("Moved %s to %s", src.name, dest.parent)
