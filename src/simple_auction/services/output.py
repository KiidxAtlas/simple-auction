"""Daily output: which lots were started, and which had their details filled in.

Two stages are counted. Each lot counts once per day, the first time it
reaches a stage (see `OutputLog.track`):

* **started** - the lot holds meaningful saved information. Photos alone do
  not count, and neither do the generated defaults of a new lot or an empty
  research dossier.
* **info-filled** - the lot has a title, a condition and identifying details
  (make, model or serial). Photos, research and publication checks are not
  needed. Every info-filled lot is also started.

Both lists are saved in data/output.json. When the app is shared, the host
database is authoritative: `OutputLog.adopt` replaces the local copy with the
host's rows, so a deleted lot cannot come back from an old local copy.
"""

import hashlib
import hmac
import json
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from simple_auction.models import Lot
from simple_auction.services import dossier, storage

log = logging.getLogger(__name__)

FILE_NAME = "output.json"
VERSION = 2
# Typed into Settings → Research → key to unlock the history (Output) page.
# Only a salted, slow hash is kept here, so reading the source does not reveal
# the passphrase. To change it: pick a new passphrase and a random 16-byte
# salt, then store `access_hash(passphrase, salt).hex()` and `salt.hex()`.
ACCESS_ITERATIONS = 600_000
ACCESS_SALT = bytes.fromhex("ea963e61681a7bcf8a0b32723154efef")
ACCESS_HASH = bytes.fromhex(
    "0eb8be07ff414e415f536dee6013f7fa53d824c4afd49fa50e029232bc1ae18d"
)


def access_hash(word: str, salt: bytes = ACCESS_SALT) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", word.encode(), salt, ACCESS_ITERATIONS)


def is_access_word(text: str) -> bool:
    """Is this the passphrase that unlocks the history (Output) page?"""
    return bool(text) and hmac.compare_digest(
        access_hash(text, ACCESS_SALT), ACCESS_HASH
    )


def local_now() -> datetime:
    return datetime.now().astimezone()


def today() -> date:
    """The current day where the user is: "daily" output follows their clock."""
    return local_now().date()


def _text(value: object) -> bool:
    return bool(str(value).strip())


def _has_dossier(packet: dict) -> bool:
    # A new lot's empty dossier is the default, not work done on the lot.
    return bool(packet) and packet != dossier.empty()


def is_started(lot: Lot) -> bool:
    """True when the lot holds meaningful information beyond its number."""
    return (
        any(
            _text(value)
            for value in (
                lot.serial,
                lot.condition,
                lot.title,
                lot.desc,
                lot.owner,
                lot.book_no,
                lot.make,
                lot.model,
                lot.barrel_length,
                lot.caliber,
                lot.gun_type,
            )
        )
        or lot.year is not None
        or lot.c_and_r
        # "N/A" is the default legality; anything else was chosen.
        or lot.ca_legality not in {"", "N/A"}
        or any(_text(value) for value in lot.custom.values())
        or _has_dossier(lot.dossier)
    )


def is_info_filled(lot: Lot) -> bool:
    """True when the lot has a title, a condition and identifying details."""
    return (
        _text(lot.title)
        and _text(lot.condition)
        and (_text(lot.make) or _text(lot.model) or _text(lot.serial))
    )


def is_complete(lot: Lot, duplicate: bool = False) -> bool:
    """True when the lot has nothing left to do before publishing."""
    try:
        return not dossier.issues(lot, duplicate)
    except ValueError, TypeError:  # a damaged research packet is not complete
        return False


@dataclass(frozen=True)
class Completion:
    """One lot reaching a stage, and when (local time zone)."""

    auction: int
    lot: int
    at: datetime
    title: str = ""
    gun_type: str = ""

    @property
    def day(self) -> date:
        return self.at.date()


def _without(
    rows: list[Completion], auction: int, numbers: set[int] | None
) -> list[Completion]:
    return [
        c
        for c in rows
        if not (c.auction == auction and (numbers is None or c.lot in numbers))
    ]


def _staged(
    rows: list[Completion], lot: Lot, auction: int, present: bool, now: datetime
) -> list[Completion]:
    """Count the lot once while it is in the stage; drop it when it leaves."""
    if not present:
        return _without(rows, auction, {lot.lot_number})
    if any(c.auction == auction and c.lot == lot.lot_number for c in rows):
        return rows
    return [
        *rows,
        Completion(
            auction,
            lot.lot_number,
            now.astimezone().replace(microsecond=0),
            lot.title.strip(),
            lot.gun_type.strip(),
        ),
    ]


class OutputLog:
    """Started and info-filled lots in the order they happened, saved after
    every change. `completions` holds the info-filled lots (the legacy name)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.started: list[Completion] = []
        self.completions: list[Completion] = []
        self._load()

    # -- queries ------------------------------------------------------------

    def count_on(self, day: date) -> int:
        """Info-filled lots first reached on that day."""
        return sum(1 for c in self.completions if c.day == day)

    def started_on(self, day: date) -> int:
        """Started lots first reached on that day."""
        return sum(1 for c in self.started if c.day == day)

    def has(self, auction: int, lot: int) -> bool:
        """Is the lot counted as info-filled?"""
        return any(c.auction == auction and c.lot == lot for c in self.completions)

    # -- changes ------------------------------------------------------------

    def track(self, lot: Lot, auction: int, now: datetime | None = None) -> None:
        """Bring both stages in line with the lot as it is saved now."""
        moment = now or local_now()
        started = _staged(self.started, lot, auction, is_started(lot), moment)
        info = _staged(self.completions, lot, auction, is_info_filled(lot), moment)
        if started != self.started or info != self.completions:
            self.started, self.completions = started, info
            self._save()

    def record(self, lot: Lot, auction: int, now: datetime | None = None) -> bool:
        """Note that the lot is info-filled (and therefore started). A lot is
        only counted once until it is cleared again (see `discard`)."""
        if self.has(auction, lot.lot_number):
            return False
        moment = now or local_now()
        self.started = _staged(self.started, lot, auction, True, moment)
        self.completions = _staged(self.completions, lot, auction, True, moment)
        self._save()
        return True

    def discard(self, auction: int, lot_number: int) -> bool:
        """Take back an info-filled count because the lot is no longer filled."""
        kept = _without(self.completions, auction, {lot_number})
        if len(kept) == len(self.completions):
            return False
        self.completions = kept
        self._save()
        return True

    def forget(self, auction: int, numbers: Iterable[int] | None = None) -> bool:
        """Remove deleted lots, or a whole auction when numbers is None."""
        wanted = None if numbers is None else set(numbers)
        started = _without(self.started, auction, wanted)
        info = _without(self.completions, auction, wanted)
        if started == self.started and info == self.completions:
            return False
        self.started, self.completions = started, info
        self._save()
        return True

    def adopt(self, rows: dict) -> bool:
        """Replace the history with the host's rows, {"started": [...],
        "info": [...]}. The host decides what was counted and when."""
        try:
            started = [self._decode(row) for row in rows["started"]]
            info = [self._decode(row) for row in rows["info"]]
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            log.warning("Ignored malformed output rows from the host: %s", e)
            return False
        started.sort(key=lambda c: c.at)
        info.sort(key=lambda c: c.at)
        if started == self.started and info == self.completions:
            return False
        self.started, self.completions = started, info
        self._save()
        return True

    # -- file ---------------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_bytes())
            version = data["version"]
            if version == 1:
                # Version 1 only kept publication-ready lots. Those were
                # necessarily started and info-filled as well.
                info = [self._decode(row) for row in data["completions"]]
                started = list(info)
            elif version == VERSION:
                started = [self._decode(row) for row in data["started"]]
                info = [self._decode(row) for row in data["completions"]]
            else:
                raise ValueError(f"unsupported version {version}")
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            log.warning("Output history %s is unreadable: %s", self.path, e)
            self._set_aside()
            return
        self.started = sorted(started, key=lambda c: c.at)
        self.completions = sorted(info, key=lambda c: c.at)
        if version == 1:
            self._save()

    @staticmethod
    def _decode(row: dict) -> Completion:
        # Local time, whatever offset it was saved with (naive values are local).
        at = datetime.fromisoformat(row["at"]).astimezone()
        return Completion(
            int(row["auction"]),
            int(row["lot"]),
            at,
            str(row.get("title", "")),
            str(row.get("gun_type", "")),
        )

    def _set_aside(self) -> None:
        """Keep an unreadable file for inspection instead of overwriting it."""
        try:
            self.path.rename(
                self.path.with_name(f"{self.path.name}.invalid-{uuid.uuid4().hex}")
            )
        except OSError:
            log.exception("Could not move aside %s", self.path)

    @staticmethod
    def _rows(items: list[Completion]) -> list[dict]:
        return [
            {
                "auction": c.auction,
                "lot": c.lot,
                "at": c.at.isoformat(),
                "title": c.title,
                "gun_type": c.gun_type,
            }
            for c in items
        ]

    def rows(self) -> dict:
        """This computer's history in the shape the host accepts (dates kept)."""
        return {
            "started": self._rows(self.started),
            "info": self._rows(self.completions),
        }

    @staticmethod
    def decode_row(row: dict) -> Completion:
        return OutputLog._decode(row)

    def _save(self) -> bool:
        data = {
            "version": VERSION,
            "started": self._rows(self.started),
            "completions": self._rows(self.completions),
        }
        try:
            storage.atomic_write(self.path, json.dumps(data, indent=2).encode("utf-8"))
        except OSError as e:
            # Counting must never get in the way of saving a lot.
            log.warning("Couldn't write %s: %s", self.path, e)
            return False
        return True
