"""Validated, portable research evidence and publication checks for a lot."""

import base64
import json
import re
from copy import deepcopy
from urllib.parse import urlsplit

from simple_auction.models import Lot

STATUSES = ("Unverified", "Source checked", "Documented")
SHOTS = ("Overall", "Opposite side", "Markings", "Serial", "Defects")
RECORD_FIELDS = {
    "findings": {"year", "source_url", "checked_on", "notes", "attachment"},
    "research": {"question", "answer", "checked_on", "sources"},
    "comparables": {
        "url",
        "sale_date",
        "price",
        "currency",
        "premium",
        "condition",
        "notes",
        "kind",
    },
}


def empty() -> dict:
    return {
        "version": 1,
        "status": "Unverified",
        "findings": [],
        "research": [],
        "comparables": [],
        "review_approved": False,
        "research_complete": False,
        "required_shots": [],
        "duplicate_notes": "",
        "relisted_from": "",
    }


def safe_url(value: str) -> bool:
    if (
        not isinstance(value, str)
        or any(c.isspace() or ord(c) < 32 for c in value)
        or "\\" in value
    ):
        return False
    try:
        parts = urlsplit(value)
        return (
            parts.scheme in {"https", "http"}
            and bool(parts.hostname)
            and not parts.username
            and not parts.password
            and parts.port != 0
        )
    except ValueError:
        return False


def validate(value: object) -> dict:
    if not isinstance(value, dict):
        raise TypeError("Research packet must be an object")
    data = empty() | deepcopy(value)
    if (
        set(data) != set(empty())
        or type(data["version"]) is not int
        or data["version"] != 1
    ):
        raise ValueError("Unsupported research packet version or fields")
    if data["status"] not in STATUSES:
        raise ValueError("Invalid identification status")
    for key in ("review_approved", "research_complete"):
        if type(data[key]) is not bool:
            raise ValueError(f"Invalid {key}")
    if len(json.dumps(data, allow_nan=False).encode("utf-8")) > 12 * 1024 * 1024:
        raise ValueError("Research packet exceeds 12 MB; remove unused attachments")
    for key in ("duplicate_notes", "relisted_from"):
        if not isinstance(data[key], str) or len(data[key]) > 100_000:
            raise ValueError(f"Invalid {key}")
    shots = data["required_shots"]
    if (
        not isinstance(shots, list)
        or any(not isinstance(s, str) or s not in SHOTS for s in shots)
        or len(shots) != len(set(shots))
    ):
        raise ValueError("Invalid completed photo checklist")
    for key, fields in RECORD_FIELDS.items():
        records = data[key]
        if not isinstance(records, list) or len(records) > 500:
            raise ValueError(f"Too many or invalid {key}")
        for record in records:
            if not isinstance(record, dict) or set(record) != fields:
                raise ValueError(f"Invalid {key} record")
            for name, text in record.items():
                if name == "sources":
                    if not isinstance(text, list) or len(text) > 100:
                        raise ValueError("Invalid research sources")
                    for source in text:
                        if (
                            not isinstance(source, dict)
                            or set(source) != {"title", "url"}
                            or any(
                                not isinstance(t, str) or len(t) > 100_000
                                for t in source.values()
                            )
                            or not safe_url(source["url"])
                        ):
                            raise ValueError("Invalid research source")
                elif not isinstance(text, str) or len(text) > (
                    3_000_000 if name == "attachment" else 100_000
                ):
                    raise ValueError(f"Invalid {key} text")
                if name == "attachment" and text:
                    prefix, separator, encoded = text.partition(",")
                    if not separator or prefix not in {
                        "data:application/pdf;base64",
                        "data:image/jpeg;base64",
                        "data:image/png;base64",
                        "data:image/webp;base64",
                    }:
                        raise ValueError("Invalid supporting attachment")
                    try:
                        raw = base64.b64decode(encoded, validate=True)
                    except ValueError as error:
                        raise ValueError(
                            "Invalid supporting attachment encoding"
                        ) from error
                    if len(raw) > 2 * 1024 * 1024:
                        raise ValueError("Supporting attachment exceeds 2 MB")
            url = record.get("url", record.get("source_url", ""))
            if url and not safe_url(url):
                raise ValueError("Source links must be HTTP or HTTPS URLs")
            if key == "comparables" and record["kind"] not in {"Sold", "Asking"}:
                raise ValueError("Comparable must be Sold or Asking")
    return data


def conflicting_years(data: dict) -> bool:
    return (
        len({r["year"].strip() for r in data.get("findings", []) if r["year"].strip()})
        > 1
    )


def serial_key(lot: Lot) -> tuple[str, str] | None:
    # Keep punctuation in serials: do not silently equate distinct identifiers.
    make = " ".join(lot.make.casefold().split())
    serial = re.sub(r"\s+", "", lot.serial).casefold()
    return (make, serial) if make and serial else None


def duplicates(
    lot: Lot, auction: int, auctions: dict[int, list[Lot]]
) -> list[tuple[int, Lot]]:
    key = serial_key(lot)
    if key is None:
        return []
    return [
        (number, other)
        for number, lots in auctions.items()
        for other in lots
        if (number, other.lot_number) != (auction, lot.lot_number)
        and serial_key(other) == key
    ]


def issues(lot: Lot, duplicate: bool = False) -> list[tuple[str, str]]:
    data = validate(lot.dossier)
    result = []
    for label, value, target in (
        ("Title", lot.title, "title"),
        ("Condition", lot.condition, "condition"),
        ("Make", lot.make, "make"),
        ("Model", lot.model, "model"),
    ):
        if not value.strip():
            result.append((f"Missing {label.lower()}", target))
    if not lot.photos:
        result.append(("Missing photos", "photos"))
    elif len(data["required_shots"]) < len(SHOTS):
        result.append(("Review important photo checklist", "photos"))
    if data["status"] == "Unverified":
        result.append(("Identification unverified", "evidence"))
    if conflicting_years(data):
        result.append(("Conflicting identification dates — review sources", "evidence"))
    if not data["research_complete"]:
        result.append(("Research unfinished", "evidence"))
    if any(
        record["question"].strip() and not record["answer"].strip()
        for record in data["research"]
    ):
        result.append(("Unanswered research / consignor questions", "evidence"))
    if not data["review_approved"]:
        result.append(("Listing awaiting approval", "evidence"))
    if duplicate and not (
        data["duplicate_notes"].strip() or data["relisted_from"].strip()
    ):
        result.append(("Duplicate make/serial needs review", "duplicates"))
    return result
