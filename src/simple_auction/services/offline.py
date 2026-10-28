"""Keep working from the last shared catalogue while the host is unreachable.

Each host identity gets its own folder holding the last snapshot received and
an ordered outbox of edits made since. The network client replays the outbox
once the host answers; this module only stores and overlays it. Entries are
small JSON files written atomically, so an interrupted app never leaves a
half-written edit behind. Photos are referenced by content hash; their bytes
live in the client's photo cache.
"""

import copy
import json
import threading
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from simple_auction.models import Lot
from simple_auction.services import storage

_guard = threading.Lock()
_locks: dict[Path, threading.RLock] = {}
# Last snapshot revision written per folder, to avoid rewriting it every poll.
_written: dict[Path, object] = {}


def _lock(folder: Path) -> threading.RLock:
    # The GUI and a background sync use separate client objects for one folder.
    with _guard:
        return _locks.setdefault(folder, threading.RLock())


def empty_record(number: int) -> dict:
    """A new lot exactly as the host creates it."""
    data = asdict(Lot(number))
    data.pop("photos")
    return {**data, "photos": []}


def _lot_number(entry: dict) -> int:
    return entry["lot"] if entry["op"] == "new_lot" else entry["lot"]["lot_number"]


def moved(numbers: dict, auction: int, lot: int) -> tuple[int, int]:
    """Where a lot numbered offline ended up on the host. Lots keep their
    place within an auction the host gave a different number."""
    if (auction, lot) in numbers["lots"]:
        return tuple(numbers["lots"][(auction, lot)])
    target = numbers["auctions"].get(auction, auction)
    return target, lot - auction + target


def renumber_history(rows: dict, numbers: dict) -> dict:
    """Output history counted offline, under the numbers the host assigned."""
    result = {}
    for stage, items in rows.items():
        result[stage] = []
        for row in items:
            auction, lot = moved(numbers, int(row["auction"]), int(row["lot"]))
            result[stage].append({**row, "auction": auction, "lot": lot})
    return result


def _decode_numbers(data: dict) -> dict:
    return {
        "auctions": {int(k): v for k, v in data["auctions"].items()},
        "lots": {
            tuple(map(int, k.split("/"))): tuple(v) for k, v in data["lots"].items()
        },
    }


def _encode_numbers(numbers: dict) -> bytes:
    data = {
        "auctions": {str(k): v for k, v in numbers["auctions"].items()},
        "lots": {f"{a}/{n}": list(v) for (a, n), v in numbers["lots"].items()},
    }
    return json.dumps(data).encode()


class Store:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.lock = _lock(folder)
        self.outbox = folder / "outbox"
        self.conflicts = folder / "conflicts"
        self._snapshot = folder / "snapshot.json"
        self._numbers = folder / "renumbered.json"
        # Kept until this computer's output history was uploaded with them.
        self._history_numbers = folder / "history-renumbered.json"

    # -- last host snapshot -------------------------------------------------

    def cached(self) -> dict | None:
        try:
            return json.loads(self._snapshot.read_bytes())
        except FileNotFoundError:
            return None
        except ValueError:
            # A damaged copy is only a cache; the host still has the data.
            return None

    def remember(self, snapshot: dict) -> None:
        stamp = (snapshot["identity"], snapshot["revision"], snapshot.get("output"))
        with self.lock:
            if _written.get(self.folder) == stamp and self._snapshot.exists():
                return
            storage.atomic_write(
                self._snapshot, json.dumps(snapshot, allow_nan=False).encode()
            )
            _written[self.folder] = stamp

    # -- outbox -------------------------------------------------------------

    def pending(self) -> list[tuple[Path, dict]]:
        with self.lock:
            if not self.outbox.is_dir():
                return []
            return [
                (path, json.loads(path.read_bytes()))
                for path in sorted(self.outbox.glob("*.json"))
            ]

    def add(self, entry: dict) -> Path:
        with self.lock:
            names = [p.name for p in self.outbox.glob("*.json")]
            sequence = max((int(n.split("-")[0]) for n in names), default=0) + 1
            path = self.outbox / f"{sequence:012d}-{uuid4().hex}.json"
            storage.atomic_write(path, json.dumps(entry, allow_nan=False).encode())
            return path

    def remove(self, path: Path) -> None:
        with self.lock:
            path.unlink(missing_ok=True)

    def view(self) -> dict | None:
        """The last host snapshot with this computer's queued edits applied."""
        with self.lock:
            cached = self.cached()
            return None if cached is None else overlay(cached, self.pending())

    # -- numbers the host assigned to lots created offline ------------------

    def renumbered(self) -> dict:
        try:
            return _decode_numbers(json.loads(self._numbers.read_bytes()))
        except FileNotFoundError:
            return {"auctions": {}, "lots": {}}

    def save_renumbered(self, numbers: dict) -> None:
        with self.lock:
            storage.atomic_write(self._numbers, _encode_numbers(numbers))

    def finish_renumbering(self, numbers: dict) -> None:
        """The outbox is replayed: keep the numbers only for the output
        history, which still names lots by their offline numbers."""
        with self.lock:
            if numbers["auctions"] or numbers["lots"]:
                kept = self.history_numbers()
                kept["auctions"].update(numbers["auctions"])
                kept["lots"].update(numbers["lots"])
                storage.atomic_write(self._history_numbers, _encode_numbers(kept))
            self._numbers.unlink(missing_ok=True)

    def history_numbers(self) -> dict:
        try:
            return _decode_numbers(json.loads(self._history_numbers.read_bytes()))
        except FileNotFoundError:
            return {"auctions": {}, "lots": {}}

    def forget_history_numbers(self) -> None:
        with self.lock:
            self._history_numbers.unlink(missing_ok=True)

    # -- conflicts ----------------------------------------------------------

    def keep_conflict(self, path: Path, entry: dict, error: str, photo) -> Path:
        """Keep an edit the host refused, with its photos, for manual recovery."""
        folder = self.conflicts / path.stem
        if entry["op"] == "save_lot":
            number = entry["lot"]["lot_number"]
            for index, digest in enumerate(entry["photos"]):
                source = photo(digest)
                if source.is_file():
                    suffix = f"-{index}" if index else ""
                    storage.atomic_write(
                        folder / f"{number}{suffix}.jpg", source.read_bytes()
                    )
        storage.atomic_write(
            folder / "edit.json",
            json.dumps({**entry, "error": error}, indent=2).encode(),
        )
        return folder


def overlay(snapshot: dict, entries: list[tuple[Path, dict]]) -> dict:
    if not entries:
        return snapshot
    view = copy.deepcopy(snapshot)
    auctions = view["auctions"]
    for _, entry in entries:
        lots = auctions.setdefault(str(entry["auction"]), [])
        if entry["op"] == "new_auction":
            continue
        number = _lot_number(entry)
        if entry["op"] == "new_lot":
            if any(v["lot_number"] == number for v in lots):
                continue
            record = empty_record(number)
        else:
            record = {**entry["lot"], "photos": entry["photos"]}
        lots[:] = [v for v in lots if v["lot_number"] != number] + [record]
        lots.sort(key=lambda v: v["lot_number"])
    # A different revision makes the window redraw after each queued edit.
    view["revision"] = f"{snapshot['revision']}+{entries[-1][0].stem}"
    view["pending"] = len(entries)
    return view
