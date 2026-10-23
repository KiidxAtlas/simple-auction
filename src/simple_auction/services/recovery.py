"""Persistent deletion history. Archives are committed before destructive file writes.

Local history lives beside the lot sidecars; shared history uses the host's own
transaction. No archived absolute paths are ever used as restore destinations.
"""

import base64
import json
import re
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from simple_auction.services import storage


def initialize(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS recovery (id TEXT PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL, auction INTEGER NOT NULL, payload TEXT NOT NULL)"
    )


@contextmanager
def connect(folder):
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(folder / "recovery.sqlite3")) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            initialize(db)
            yield db
    except sqlite3.Error as e:
        raise ValueError(f"Recovery archive unavailable; operation stopped: {e}") from e


def archive(db, kind, auction, payload):
    identity = uuid4().hex
    db.execute(
        "INSERT INTO recovery VALUES (?,?,?,?,?)",
        (
            identity,
            datetime.now(UTC).isoformat(),
            kind,
            auction,
            json.dumps(payload, allow_nan=False),
        ),
    )
    return identity


def entries(db):
    return [
        dict(zip(("id", "created", "kind", "auction"), row, strict=True))
        for row in db.execute(
            "SELECT id,created,kind,auction FROM recovery ORDER BY created DESC"
        )
    ]


def get(db, identity):
    row = db.execute(
        "SELECT kind,auction,payload FROM recovery WHERE id=?", (identity,)
    ).fetchone()
    if row is None:
        raise ValueError("Recovery entry is missing")
    return row[0], row[1], json.loads(row[2])


def photo_data(photos):
    return {
        p.name: base64.b64encode(data).decode("ascii") for p, data in photos.items()
    }


def decode_photos(payload):
    result = {}
    for name, raw in payload.get("photos", {}).items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[0-9]+(?:-[0-9]+)?\.jpg", name
        ):
            raise ValueError("Unsafe archived photo name")
        result[name] = base64.b64decode(raw, validate=True)
    return result


def archive_local(details, kind, lots, photos, *, workbook=None):
    candidate = details.stem.split(" ")[0]
    if not candidate.isdigit() and workbook is not None:
        candidate = workbook.stem
    # Nonstandard service callers can still export history, but cannot restore
    # without an unambiguous auction identity.
    auction = int(candidate) if candidate.isdigit() else 0
    records = []
    for lot in lots:
        data = asdict(lot)
        data.pop("photos")
        records.append(data)
    with connect(details.parent) as db:
        return archive(
            db, kind, auction, {"lots": records, "photos": photo_data(photos)}
        )


def list_local(config):
    with storage.lock, connect(config.data_dir) as db:
        return entries(db)


def restore_local(config, identity):
    from simple_auction.services import catalogue, excel, lot_details, network

    with storage.lock, connect(config.data_dir) as db:
        kind, auction, payload = get(db, identity)
        network.number(auction)
        if kind not in {"lots", "auction"}:
            raise ValueError(
                "Export previous revisions instead of replacing current work."
            )
        workbook = excel.auction_path(config.auctions_dir, auction)
        details = lot_details.details_path(config.data_dir, auction)
        storage.recover(storage.journal_path(workbook))
        if kind == "auction" and (
            workbook.exists()
            or details.exists()
            or config.auction_photos_dir(auction).exists()
        ):
            raise ValueError(
                "Auction number is already in use; nothing was overwritten."
            )
        if kind == "lots" and not workbook.exists():
            raise ValueError("Restore the deleted auction first.")
        lots = [network.validated_lot(v) for v in payload["lots"]]
        numbers = {v.lot_number for v in lots}
        photos = decode_photos(payload)
        if kind == "lots" and any(
            int(name.split(".")[0].split("-")[0]) not in numbers for name in photos
        ):
            raise ValueError("Archived photo does not belong to the deleted lots")
        targets = {
            config.auction_photos_dir(auction) / name: raw
            for name, raw in photos.items()
        }
        catalogue.restore(workbook, details, lots, targets)
        return auction


def export_snapshot(payload, destination):
    """Export text and photos into a new folder only, without overwriting work."""
    photos = decode_photos(payload)
    destination.mkdir(parents=True, exist_ok=False)
    changes = {destination / name: raw for name, raw in photos.items()}
    text = {k: v for k, v in payload.items() if k != "photos"}
    changes[destination / "snapshot.json"] = json.dumps(
        text, ensure_ascii=False, indent=2
    ).encode("utf-8")
    storage.commit(changes, destination / ".export.transaction")
    return len(photos)


def export_local(config, identity, destination):
    with storage.lock, connect(config.data_dir) as db:
        _, _, payload = get(db, identity)
        return export_snapshot(payload, destination)
