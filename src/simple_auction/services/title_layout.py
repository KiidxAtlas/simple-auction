"""Which lot fields are written into the title and the description, in order.

The title is built around the user's own wording ("title"); the description
starts with one "Label: value" line per chosen field. Besides the built-in
lot fields, layouts may use custom fields defined in Settings; their keys are
"custom:<id>" and their values live in Lot.custom.
"""

import re
import uuid
from dataclasses import dataclass

from simple_auction.constants import TITLE_MAX_LENGTH
from simple_auction.models import Lot

FIELD_LABELS = {
    "make": "Make",
    "model": "Model",
    "caliber": "Caliber",
    "gun_type": "Type",
    "serial": "Serial number",
    "title": "Custom title text",
    "condition": "Condition",
    "ca_legality": "CA legality",
    "c_and_r": "C&R eligible",
    "year": "Year",
    "barrel_length": "Barrel length",
    "owner": "Owner",
    "book_no": "Book number",
}
# e.g. "Arsenal SAM7SF 7.62x39 Rifle SN: BE 53 1936 Excellent Condition OK FOR CA"
DEFAULT_FIELDS = (
    "make",
    "model",
    "caliber",
    "gun_type",
    "title",
    "serial",
    "condition",
    "ca_legality",
    "c_and_r",
)
# Earlier built-in defaults; a saved layout that's exactly one of these is
# upgraded to DEFAULT_FIELDS (see Config).
LEGACY_DEFAULT_FIELDS = ("make", "model", "serial", "title", "condition")
PREVIOUS_DEFAULT_FIELDS = DEFAULT_FIELDS[:-1]  # before C&R was added
# Description lines; the condition sentence is always added at the end
# separately (see listing.condition_desc), so it isn't one of these.
DEFAULT_DESC_FIELDS = ("make", "model", "caliber", "gun_type")
DESC_EXCLUDED = frozenset({"title", "condition"})
CA_LEGALITY = ("N/A", "Legal for CA", "Not CA legal")
GUN_TYPES = ("Rifle", "Shotgun", "Handgun")
CUSTOM_PREFIX = "custom:"
_CUSTOM_ID = re.compile(r"[a-z0-9]{1,32}")
MAX_CUSTOM_TEXT = 200


@dataclass(frozen=True)
class CustomField:
    """A field the user added in Settings: shown in the lot editor and
    usable in the title, written as "<prefix> <value>" (prefix optional)."""

    id: str
    label: str
    prefix: str = ""

    @property
    def key(self) -> str:
        return CUSTOM_PREFIX + self.id


def new_custom_id() -> str:
    return uuid.uuid4().hex[:12]


def is_custom_id(value: object) -> bool:
    return isinstance(value, str) and _CUSTOM_ID.fullmatch(value) is not None


def is_custom_key(key: object) -> bool:
    return (
        isinstance(key, str)
        and key.startswith(CUSTOM_PREFIX)
        and is_custom_id(key[len(CUSTOM_PREFIX) :])
    )


def custom_fields_from_json(data: object) -> list[CustomField]:
    """Validate the custom field definitions saved in config.json."""
    if data is None:
        return []
    if not isinstance(data, list):
        raise TypeError("custom_fields must be a list")
    fields = []
    for entry in data:
        if (
            not isinstance(entry, dict)
            or set(entry) - {"id", "label", "prefix"}
            or not is_custom_id(entry.get("id"))
            or not isinstance(entry.get("label"), str)
            or not entry["label"].strip()
            or len(entry["label"]) > MAX_CUSTOM_TEXT
            or not isinstance(entry.get("prefix", ""), str)
            or len(entry.get("prefix", "")) > MAX_CUSTOM_TEXT
        ):
            raise ValueError("custom_fields entries need an id and a label")
        fields.append(
            CustomField(entry["id"], entry["label"].strip(), entry.get("prefix", ""))
        )
    if len({f.id for f in fields}) != len(fields):
        raise ValueError("custom_fields ids must be unique")
    return fields


def custom_fields_to_json(fields: list[CustomField]) -> list[dict]:
    return [{"id": f.id, "label": f.label, "prefix": f.prefix} for f in fields]


def validate_values(values: object) -> dict[str, str]:
    """A lot's custom field values: {custom id: text}."""
    if not isinstance(values, dict) or any(
        not is_custom_id(k) or not isinstance(v, str) or len(v) > 100_000
        for k, v in values.items()
    ):
        raise ValueError("custom values must map field ids to text")
    return dict(values)


def validate(fields: object, custom: list[CustomField] | None = None) -> list[str]:
    """Check a layout. With `custom`, custom keys must also be defined there."""
    defined = None if custom is None else {f.key for f in custom}
    if (
        not isinstance(fields, list)
        or any(
            not isinstance(key, str)
            or not (
                key in FIELD_LABELS
                or (is_custom_key(key) and (defined is None or key in defined))
            )
            for key in fields
        )
        or len(set(fields)) != len(fields)
        or fields.count("title") != 1
    ):
        raise ValueError(
            "title_fields must contain unique known fields and Custom title text"
        )
    return list(fields)


def validate_desc(fields: object, custom: list[CustomField] | None = None) -> list[str]:
    """Check the description fields (unique, known, no title/condition)."""
    defined = None if custom is None else {f.key for f in custom}
    if (
        not isinstance(fields, list)
        or any(
            not isinstance(key, str)
            or key in DESC_EXCLUDED
            or not (
                key in FIELD_LABELS
                or (is_custom_key(key) and (defined is None or key in defined))
            )
            for key in fields
        )
        or len(set(fields)) != len(fields)
    ):
        raise ValueError("desc_fields must contain unique known fields")
    return list(fields)


def labels(custom: list[CustomField] = ()) -> dict[str, str]:
    """{field key: label} for every field, built-in and custom."""
    return dict(FIELD_LABELS) | {f.key: f.label for f in custom}


def prefixes(custom: list[CustomField]) -> dict[str, str]:
    """{title key: text written before the value} for custom fields."""
    return {f.key: f.prefix.strip() for f in custom}


def field_text(lot: Lot, key: str) -> str:
    """A field's plain value (empty for N/A CA legality, a lot that isn't
    C&R eligible, or unknown fields)."""
    if is_custom_key(key):
        return lot.custom.get(key[len(CUSTOM_PREFIX) :], "").strip()
    value = getattr(lot, key, None)
    if key == "c_and_r":
        return "Yes" if value is True else ""
    text = "" if value is None else str(value).strip()
    return "" if key == "ca_legality" and text == "N/A" else text


def desc_lines(lot: Lot, fields: list[str], label_for: dict[str, str]) -> list[str]:
    """The generated start of the description: "Make: Colt", one per filled field."""
    return [
        f"{label_for.get(key, key)}: {text}"
        for key in fields
        if (text := field_text(lot, key))
    ]


def update_desc(desc: str, replace_labels: list[str], lines: list[str]) -> str:
    """Put `lines` at the top of the description, removing earlier generated
    lines (any line starting "<label>:" for the given labels). Everything
    else the user wrote is kept."""
    rest = desc
    unique = sorted({x for x in replace_labels if x}, key=len, reverse=True)
    if unique:
        alts = "|".join(re.escape(x) for x in unique)
        rest = re.sub(rf"^(?:{alts}):.*(?:\n|$)", "", rest, flags=re.MULTILINE)
    rest = re.sub(r"\n{3,}", "\n\n", rest).strip()
    head = "\n".join(lines)
    return "\n\n".join(part for part in (head, rest) if part)


# How titles are written, matching auction listings like
# "Arsenal SAM7SF 7.62x39 Rifle SN: BE 53 1936 Excellent Condition OK FOR CA".
CA_TITLE_TEXT = {"Legal for CA": "OK FOR CA", "Not CA legal": "NOT CA LEGAL"}
C_AND_R_TITLE_TEXT = "C&R ELIGIBLE"
# Fields that alone don't make a title (a lot with just a condition stays
# untitled until something describes the item).
_QUALIFIERS = frozenset({"condition", "ca_legality", "c_and_r"})


def _value(lot: Lot, key: str, prefix_for: dict[str, str], legacy: bool) -> str:
    """A field as written in the title. `legacy` is the older style
    ("S/N: X", plain condition and CA legality), recognised when replacing
    the generated parts of titles written before."""
    text = field_text(lot, key)
    if not text:
        return ""
    if is_custom_key(key):
        prefix = prefix_for.get(key, "")
        return f"{prefix} {text}" if prefix else text
    if key == "serial":
        return f"S/N: {text}" if legacy else f"SN: {text}"
    if key == "barrel_length":
        return f"Barrel length: {text}"
    if key == "c_and_r":
        return C_AND_R_TITLE_TEXT
    if legacy:
        return text
    if key == "condition":
        return text if text.casefold().endswith("condition") else f"{text} Condition"
    if key == "ca_legality":
        return CA_TITLE_TEXT.get(text, text)
    return text


def _edges(
    lot: Lot, fields: list[str], prefix_for: dict[str, str], legacy: bool = False
) -> tuple[str, str]:
    pivot = fields.index("title")

    def join(keys):
        return " ".join(
            filter(None, (_value(lot, k, prefix_for, legacy) for k in keys))
        )

    return join(fields[:pivot]), join(fields[pivot + 1 :])


def _strip(rest: str, prefix: str, suffix: str, joiner: str) -> str | None:
    """`rest` without the generated start/end, or None if neither is there."""
    folded, matched = rest.casefold(), False
    if suffix:
        if folded == suffix.casefold():
            return ""
        if folded.endswith((joiner + suffix).casefold()):
            rest = rest[: -len(suffix) - len(joiner)].strip()
            folded, matched = rest.casefold(), True
    if prefix and (
        folded == prefix.casefold() or folded.startswith(prefix.casefold() + " ")
    ):
        rest = rest[len(prefix) :].strip()
        matched = True
    return rest if matched else None


def update_title(
    title: str,
    old: Lot,
    old_fields: list[str],
    new: Lot,
    fields: list[str],
    prefix_for: dict[str, str] | None = None,
    old_prefix_for: dict[str, str] | None = None,
    max_length: int = TITLE_MAX_LENGTH,
) -> str:
    """Replace only generated edges, retaining the user's words in between.

    `prefix_for` maps custom field keys to the text written before their
    value; `old_prefix_for` is what the current title was built with
    (defaults to `prefix_for`). Titles in the older style ("S/N:", a dash
    before the condition) are recognised and rewritten in the current one.
    """
    prefix_for = prefix_for or {}
    old_prefix_for = prefix_for if old_prefix_for is None else old_prefix_for
    rest = title.strip()
    layout = old.title_fields if old.title_fields is not None else old_fields
    attempts = [(layout, False, " "), (layout, True, " - ")]
    if old.title_fields is None:
        attempts.append((list(LEGACY_DEFAULT_FIELDS), True, " - "))
    # The reading that removes the most generated text wins (the first on a
    # tie), so an older title isn't mistaken for a partial match.
    best = None
    for old_layout, legacy, joiner in attempts:
        prefix, suffix = _edges(old, old_layout, old_prefix_for, legacy)
        stripped = _strip(rest, prefix, suffix, joiner)
        if stripped is not None and (best is None or len(stripped) < len(best)):
            best = stripped
    if best is not None:
        rest = best
    before, after = _edges(new, fields, prefix_for)
    pivot = fields.index("title")
    describes = any(
        _value(new, k, prefix_for, False)
        for k in fields[pivot + 1 :]
        if k not in _QUALIFIERS
    )
    base = " ".join(part for part in (before, rest) if part)
    # A condition alone should not create a title for an otherwise empty lot.
    if not base and not describes:
        return ""
    if not base:
        return after[:max_length]
    tail = f" {after}" if after else ""
    if len(tail) >= max_length:
        return (base + tail)[:max_length]
    return base[: max_length - len(tail)].rstrip() + tail
