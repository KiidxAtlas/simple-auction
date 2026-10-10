"""Proxibid report -> buyer addresses -> Pirate Ship CSV.

The report's columns are confirmed by the user; no private platform API is used.
Each auction has its own saved batch. Packing measurements are optional in the
UI; each exported row represents one shipment, initially one per buyer.
"""

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from simple_auction.services import storage
from simple_auction.services.importer import Sheet

FIELDS = {
    "buyer_id": "Bidder / buyer ID",
    "name": "Full name",
    "first_name": "First name",
    "last_name": "Last name",
    "email": "Email",
    "address1": "Shipping address line 1",
    "address2": "Shipping address line 2",
    "city": "City",
    "state": "State / province",
    "zip": "ZIP / postal code",
    "country": "Country code",
    "lot": "Lot number",
    "title": "Lot title / description",
}
ALIASES = {
    "buyer_id": [
        "bidder number",
        "bidder no",
        "bidder id",
        "buyer id",
        "buyer number",
        "paddle number",
        "paddle",
        "bidder paddle number",
    ],
    "name": ["shipping name", "bidder name", "buyer name", "full name", "name"],
    "first_name": ["bidder first name", "buyer first name", "first name"],
    "last_name": ["bidder last name", "buyer last name", "last name"],
    "email": [
        "bidder email address",
        "bidder email",
        "buyer email",
        "email address",
        "email",
    ],
    "address1": [
        "shipping address line 1",
        "shipping address 1",
        "shipping address",
        "ship to address",
        "bidder shipping address",
        "address line 1",
        "address 1",
        "street address",
        "bidder address",
        "address",
    ],
    "address2": [
        "shipping address line 2",
        "shipping address 2",
        "address line 2",
        "address 2",
    ],
    "city": ["shipping city", "ship to city", "bidder city", "city"],
    "state": [
        "shipping state",
        "shipping province",
        "bidder state",
        "state",
        "province",
    ],
    "zip": [
        "shipping zip code",
        "shipping zip",
        "shipping postal code",
        "bidder zip code",
        "bidder zip",
        "zip code",
        "zip",
        "postal code",
    ],
    "country": ["shipping country", "bidder country", "country code", "country"],
    "lot": ["lot number", "lot no", "lot", "lot identifier"],
    "title": ["lot title", "lot description", "title", "description"],
}
ADDRESS_FIELDS = (
    "name",
    "email",
    "address1",
    "address2",
    "city",
    "state",
    "zip",
    "country",
)
CSV_HEADERS = [
    "Name",
    "Email",
    "Address Line 1",
    "Address Line 2",
    "City",
    "State",
    "Zip",
    "Country",
    "Weight (Pounds)",
    "Length",
    "Width",
    "Height",
    "Order ID",
]


class ShippingError(ValueError):
    pass


@dataclass
class Package:
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    lots: list[str] = field(default_factory=list)
    weight_oz: float = 0
    length: float = 0
    width: float = 0
    height: float = 0
    packed: bool = False
    exported_at: str = ""
    exported_file: str = ""


@dataclass
class Buyer:
    id: str
    name: str = ""
    email: str = ""
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = ""
    lots: dict[str, str] = field(default_factory=dict)
    packages: list[Package] = field(default_factory=list)
    pickup: bool = False


@dataclass
class Batch:
    auction: str
    source: str
    buyers: list[Buyer]


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def guess_mapping(headers: list[str]) -> dict[str, int | None]:
    normalized = [_norm(h) for h in headers]
    return {
        name: next(
            (
                normalized.index(_norm(alias))
                for alias in aliases
                if _norm(alias) in normalized
            ),
            None,
        )
        for name, aliases in ALIASES.items()
    }


def read_report(path: Path) -> Sheet:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    try:
        rows = [
            r
            for r in csv.reader(io.StringIO(text, newline=""), dialect, strict=True)
            if any(c.strip() for c in r)
        ]
    except csv.Error as e:
        raise ShippingError(f"Cannot read this CSV: {e}") from e
    if not rows:
        raise ShippingError("This CSV is empty.")
    # Some exports start with the auction title before the column headings.
    header = next(
        (
            i
            for i, r in enumerate(rows[:15])
            if guess_mapping(r)["lot"] is not None
            and any(
                guess_mapping(r)[key] is not None
                for key in ("buyer_id", "name", "first_name", "email")
            )
        ),
        0,
    )
    headers = [c.strip() for c in rows[header]]
    if len(headers) < 2 or not rows[header + 1 :]:
        raise ShippingError(
            "No auction rows found. Export the Winning Bidders Report as CSV."
        )
    return Sheet(headers=headers, rows=rows[header + 1 :])


def build_batch(
    sheet: Sheet,
    mapping: dict[str, int | None],
    auction: str,
    source: str,
    default_country: str,
) -> Batch:
    if not auction.strip():
        raise ShippingError("Enter a unique auction reference.")
    chosen = [i for i in mapping.values() if i is not None]
    if len(set(chosen)) != len(chosen):
        raise ShippingError("Each column can only be mapped once.")
    if mapping.get("lot") is None:
        raise ShippingError("Choose the lot number column.")
    if mapping.get("buyer_id") is None and mapping.get("email") is None:
        raise ShippingError(
            "Choose a bidder ID or email column to identify buyers safely."
        )
    if mapping.get("name") is None and mapping.get("first_name") is None:
        raise ShippingError("Choose a full name or first name column.")
    for name in ("address1", "city", "zip"):
        if mapping.get(name) is None:
            raise ShippingError(f"Choose the {FIELDS[name]} column.")

    def cell(row, name):
        index = mapping.get(name)
        return (
            str(row[index]).strip()
            if index is not None and index < len(row) and row[index] is not None
            else ""
        )

    buyers: dict[str, Buyer] = {}
    lot_owners: dict[str, str] = {}
    for number, row in enumerate(sheet.rows, 1):
        values = {name: cell(row, name) for name in FIELDS}
        identity = values["buyer_id"] or values["email"].lower()
        lot = values["lot"]
        if not identity or not lot:
            raise ShippingError(
                f"Data row {number}: missing buyer ID/email or lot number. No rows were imported."
            )
        values["name"] = values["name"] or " ".join(
            v for v in (values["first_name"], values["last_name"]) if v
        )
        values["country"] = (values["country"] or default_country).upper()
        if values["country"] in ("USA", "UNITED STATES", "UNITED STATES OF AMERICA"):
            values["country"] = "US"
        if (
            len(values["country"]) != 2
            or not values["country"].isascii()
            or not values["country"].isalpha()
        ):
            raise ShippingError(
                f"Data row {number}: use a two-letter country code (for example US or CA)."
            )
        buyer = buyers.get(identity)
        if buyer is None:
            buyer = Buyer(id=identity, **{k: values[k] for k in ADDRESS_FIELDS})
            buyers[identity] = buyer
        else:
            for name in ADDRESS_FIELDS:
                old, new = getattr(buyer, name), values[name]
                if old and new and old.casefold() != new.casefold():
                    raise ShippingError(
                        f"Data row {number}: buyer {identity} has conflicting {FIELDS[name]} values. Check the report before combining their lots."
                    )
                if new and not old:
                    setattr(buyer, name, new)
        if lot in lot_owners and lot_owners[lot] != identity:
            raise ShippingError(
                f"Data row {number}: lot {lot} belongs to more than one buyer."
            )
        if (
            lot in buyer.lots
            and buyer.lots[lot]
            and values["title"]
            and buyer.lots[lot] != values["title"]
        ):
            raise ShippingError(
                f"Data row {number}: conflicting descriptions for lot {lot}."
            )
        lot_owners[lot] = identity
        buyer.lots[lot] = buyer.lots.get(lot) or values["title"]
    if not buyers:
        raise ShippingError("No buyers found.")
    for buyer in buyers.values():
        buyer.packages = [Package(lots=list(buyer.lots))]
    return Batch(auction.strip(), source, list(buyers.values()))


def problems(
    buyer: Buyer, package: Package, *, include_measurements: bool = True
) -> list[str]:
    missing = [
        FIELDS[k]
        for k in ("name", "address1", "city", "zip", "country")
        if not getattr(buyer, k).strip()
    ]
    if buyer.country.upper() in ("US", "CA", "AU") and not buyer.state.strip():
        missing.append("State / province")
    errors = ["Missing: " + ", ".join(missing)] if missing else []
    country = buyer.country.strip()
    if country and (
        len(country) != 2 or not country.isascii() or not country.isalpha()
    ):
        errors.append("Country must be a two-letter code.")
    if not package.lots:
        errors.append("Assign at least one lot to this box.")
    assigned = [lot for p in buyer.packages for lot in p.lots]
    if len(set(assigned)) != len(assigned) or set(assigned) != set(buyer.lots):
        errors.append("Assign every lot to exactly one box.")
    if include_measurements and any(
        not math.isfinite(v) or v <= 0
        for v in (package.weight_oz, package.length, package.width, package.height)
    ):
        errors.append("Enter a positive weight and all three dimensions.")
    return errors


def ready_packages(
    batch: Batch, *, include_measurements: bool = True
) -> list[tuple[Buyer, Package]]:
    return [
        (b, p)
        for b in batch.buyers
        if not b.pickup
        for p in b.packages
        if (p.packed or not include_measurements)
        and not p.exported_at
        and not problems(b, p, include_measurements=include_measurements)
    ]


def package_status(
    buyer: Buyer, package: Package, *, include_measurements: bool = True
) -> str:
    if package.exported_at:
        return "Exported"
    if buyer.pickup:
        return "Local pickup"
    errors = problems(buyer, package, include_measurements=include_measurements)
    if (package.packed or not include_measurements) and not errors:
        return "Ready"
    return (
        "Check address / items"
        if errors and not include_measurements
        else ("Needs attention" if errors else "Needs packing")
    )


def batch_path(folder: Path, auction: str) -> Path:
    return folder / (
        hashlib.sha256(auction.strip().casefold().encode()).hexdigest()[:24] + ".json"
    )


def encode(batch: Batch) -> bytes:
    return json.dumps(
        {"version": 1, **asdict(batch)}, ensure_ascii=False, indent=2, allow_nan=False
    ).encode("utf-8")


def decode(raw: bytes) -> Batch:
    try:
        data = json.loads(raw)
        if data.pop("version") != 1:
            raise ValueError("unsupported shipping file version")
        buyers = []
        for item in data.pop("buyers"):
            packages = [Package(**p) for p in item.pop("packages")]
            buyers.append(Buyer(**item, packages=packages))
        batch = Batch(**data, buyers=buyers)
        if (
            not isinstance(batch.auction, str)
            or not batch.auction.strip()
            or not isinstance(batch.source, str)
            or not buyers
            or any(not b.id or not b.packages for b in buyers)
        ):
            raise ValueError("empty auction or buyers")
        if len({b.id for b in buyers}) != len(buyers):
            raise ValueError("duplicate buyers")
        ids = [p.id for b in buyers for p in b.packages]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate packages")
        for b in buyers:
            if (
                any(not isinstance(getattr(b, k), str) for k in ("id", *ADDRESS_FIELDS))
                or type(b.pickup) is not bool
                or not isinstance(b.lots, dict)
                or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in b.lots.items()
                )
            ):
                raise ValueError("invalid buyer fields")
            for p in b.packages:
                if (
                    not isinstance(p.id, str)
                    or not p.id
                    or not isinstance(p.exported_at, str)
                    or not isinstance(p.exported_file, str)
                    or type(p.packed) is not bool
                    or not isinstance(p.lots, list)
                    or any(not isinstance(lot, str) for lot in p.lots)
                    or any(
                        type(v) not in (int, float) or not math.isfinite(v) or v < 0
                        for v in (p.weight_oz, p.length, p.width, p.height)
                    )
                ):
                    raise ValueError("invalid package fields")
        return batch
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ShippingError(
            f"Cannot read shipping progress: {e}. The file has been left unchanged."
        ) from e


def save_batch(path: Path, batch: Batch) -> None:
    raw = encode(batch)
    decode(raw)
    storage.recover(storage.journal_path(path))
    if path.exists():
        decode(path.read_bytes())  # Never overwrite unreadable progress.
    storage.atomic_write(path, raw)


def load_batch(path: Path) -> Batch:
    storage.recover(storage.journal_path(path))
    return decode(path.read_bytes())


def export_batch(
    batch: Batch,
    progress_path: Path,
    output: Path,
    *,
    include_measurements: bool = True,
) -> Batch:
    """Commit the CSV and export ledger together; failed writes preserve both."""
    ready = ready_packages(batch, include_measurements=include_measurements)
    if not ready:
        raise ShippingError("No new shipments are ready to export.")
    if output.suffix.lower() != ".csv" or output.resolve() == progress_path.resolve():
        raise ShippingError("Choose a .csv destination for Pirate Ship.")
    # Recover before preparing changes, so a rollback cannot replace newer input.
    saved = load_batch(progress_path)
    if encode(saved) != encode(batch):
        raise ShippingError(
            "Shipping progress changed on disk. Reopen the auction before exporting."
        )
    if output.exists():
        raise ShippingError(
            "Choose a new CSV filename so previous shipping exports are preserved."
        )
    raw, updated = prepare_export(
        batch, str(output.resolve()), include_measurements=include_measurements
    )
    storage.commit(
        {output: raw, progress_path: encode(updated)},
        storage.journal_path(progress_path),
    )
    return updated


def prepare_export(
    batch: Batch, exported_file: str, *, include_measurements: bool = True
) -> tuple[bytes, Batch]:
    """Prepare a CSV and ledger; file and server callers commit them atomically."""
    ready = ready_packages(batch, include_measurements=include_measurements)
    if not ready:
        raise ShippingError("No new shipments are ready to export.")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        CSV_HEADERS if include_measurements else [*CSV_HEADERS[:8], "Order ID"]
    )
    for buyer, package in ready:
        measurements = (
            [package.weight_oz / 16, package.length, package.width, package.height]
            if include_measurements
            else []
        )
        writer.writerow(
            [
                *(getattr(buyer, k).strip() for k in ADDRESS_FIELDS),
                *measurements,
                f"{batch.auction}/{buyer.id}/{package.id}",
            ]
        )
    timestamp = datetime.now(UTC).isoformat()
    ids = {p.id for _, p in ready}
    updated = replace(
        batch,
        buyers=[
            replace(
                b,
                packages=[
                    replace(p, exported_at=timestamp, exported_file=exported_file)
                    if p.id in ids
                    else p
                    for p in b.packages
                ],
            )
            for b in batch.buyers
        ],
    )
    return stream.getvalue().encode("utf-8-sig"), updated
