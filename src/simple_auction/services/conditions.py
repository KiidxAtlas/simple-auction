"""The condition choices and their description text.

They live in data/conditions.yaml in the main folder, one per line:

    Like New: Appears unfired or barely used, no notable wear.
    Excellent: Light handling marks, bore bright.

Edit that file in any text editor (or the table in Settings); the app picks up
changes while it runs. A lot stores its condition as plain text, so lots keep
their condition even after it's renamed or removed from the list.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

FILE_NAME = "conditions.yaml"

FILE_HEADER = """\
# Lot conditions for Simple Auction.
#
# One per line:   Name: text added to the description
#   - The order here is the order in the Condition dropdown.
#   - New lots start with no condition until one is picked.
#   - Picking a condition adds " - Name" to the title and
#     "Condition: Name. <text>" to the end of the description.
#   - Leave the text empty (just "Name:") to add only "Condition: Name."
#   - Put quotes around a name or text that contains a colon, e.g.
#     "Good: see notes": Some wear.
#   - Percentages such as 80% are fine. Descriptions starting with % are
#     treated as literal text too; generated descriptions are safely quoted.
#
# Save the file and the app updates right away.

"""


class ConditionsFileError(Exception):
    """conditions.yaml couldn't be read; the message says what's wrong."""


@dataclass(frozen=True)
class ConditionOption:
    name: str  # e.g. "Excellent"; also the title suffix " - Excellent"
    note: str = ""  # the sentence after "Condition: Excellent." in descriptions


DEFAULT_CONDITIONS = [
    ConditionOption(
        "Factory New",
        "All original parts; 100% original finish; in perfect condition in every respect in and out.",
    ),
    ConditionOption(
        "New",
        "Not previously sold at retail, in same condition as current factory production.",
    ),
    ConditionOption(
        "Perfect",
        'In New condition in every respect, (Many collectors & dealers use "As New" to describe this condition.)',
    ),
    ConditionOption(
        "Excellent",
        "New condition, used but little, no noticeable marring of wood or metal, bluing perfect (except at muzzle or sharp edges).",
    ),
    ConditionOption(
        "Fine",
        "All original parts; over 30% original finish; sharp lettering, numerals and design on metal and wood; minor marks in wood; good bore.",
    ),
    ConditionOption(
        "Very Good",
        "In perfect working condition, no appreciable wear on working surfaces, no broken parts, no corrosion or pitting, only minor surface dents or scratches.",
    ),
    ConditionOption(
        "Good",
        "In safe working condition, minor wear on working surfaces, no broken parts, no corrosion or pitting that will interfere with proper functioning.",
    ),
    ConditionOption(
        "Fair",
        "In safe working condition but well worn, perhaps requiring replacement of minor parts or adjustments which should be indicated in advertisement, no rust, but may have corrosion pits which do not render article unsafe or inoperable.",
    ),
    ConditionOption(
        "Poor",
        "Major and minor parts replaced; major replacement parts required and extensive restoration needed; metal deeply pitted; principal lettering, numerals and design obliterated, wood badly scratched, bruised, cracked, or broken; mechanically inoperative; generally undesirable as a collector's firearm.",
    ),
]

# Only this exact, unmodified starter list is eligible for automatic migration.
# Custom names, notes, ordering, and intentionally empty lists are preserved.
LEGACY_DEFAULT_CONDITIONS = [
    ConditionOption("Like New", "Appears unfired or barely used, no notable wear."),
    ConditionOption("Excellent", "Light handling marks, bore bright."),
    ConditionOption("Good", "Normal wear and handling marks consistent with use."),
    ConditionOption("Fair", "Noticeable wear, finish loss or marks. See photos."),
]


def cleaned(options: list[ConditionOption]) -> list[ConditionOption]:
    """Drop rows without a name and repeated names (first one wins)."""
    seen: set[str] = set()
    out = []
    for option in options:
        name = " ".join(option.name.split())
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(ConditionOption(name, " ".join(option.note.split())))
    return out


def to_json(options: list[ConditionOption]) -> list[dict]:
    return [{"name": o.name, "note": o.note} for o in options]


def from_json(data: object) -> list[ConditionOption]:
    if not isinstance(data, list):
        return list(DEFAULT_CONDITIONS)
    return cleaned(
        [
            ConditionOption(str(d.get("name", "")), str(d.get("note", "")))
            for d in data
            if isinstance(d, dict)
        ]
    )


def _quote_percent_notes(source: str) -> str:
    """Accept leading % in the editable Name: text format, not YAML directives.

    YAML reserves % at the start of a scalar. Treat it as description text
    only after a mapping key; leave all other YAML syntax and errors intact.
    """
    return re.sub(
        r"^(?P<key>[ \t]*(?:[^\s:#\"'\n][^:\n]*|\"[^\"\n]*\"|'[^'\n]*'):[ \t]*)(?P<note>%[^\r\n]*)$",
        lambda match: match["key"] + _scalar(match["note"]),
        source,
        flags=re.MULTILINE,
    )


def load_file(path: Path) -> list[ConditionOption]:
    """Read conditions.yaml. Raises ConditionsFileError with a readable
    message if the file is missing, isn't valid YAML, or has the wrong shape."""
    try:
        data = yaml.safe_load(_quote_percent_notes(path.read_text(encoding="utf-8")))
    except OSError as e:
        raise ConditionsFileError(f"Couldn't read {path.name}: {e}") from e
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        problem = getattr(e, "problem", None) or "invalid YAML"
        raise ConditionsFileError(f"{path.name}{where}: {problem}") from e
    if data is None:
        return []
    if isinstance(data, dict):  # Name: text  (the normal form)
        rows = [(k, v) for k, v in data.items()]
    elif isinstance(data, list):  # - name: X / text: Y  (also accepted)
        rows = []
        for item in data:
            if isinstance(item, dict) and "name" in item:
                rows.append((item["name"], item.get("text", item.get("note"))))
            elif isinstance(item, str):
                rows.append((item, ""))
            else:
                raise ConditionsFileError(
                    f"{path.name}: each entry needs a name, like 'Good: some text'."
                )
    else:
        raise ConditionsFileError(f"{path.name}: expected one 'Name: text' per line.")
    return cleaned(
        [
            ConditionOption(
                "" if name is None else str(name), "" if text is None else str(text)
            )
            for name, text in rows
        ]
    )


def _scalar(text: str, *, quote: bool = False) -> str:
    """One YAML value, optionally always quoted for editable descriptions."""
    dumped = yaml.safe_dump(
        text, allow_unicode=True, width=1000, default_style='"' if quote else None
    )
    return dumped.removesuffix("\n").removesuffix("\n...").strip()


def save_file(path: Path, options: list[ConditionOption]) -> None:
    """Write conditions.yaml, one "Name: text" line each, under the header."""
    lines = [
        f"{_scalar(o.name)}: {_scalar(o.note, quote=True)}" if o.note else f"{_scalar(o.name)}:"
        for o in options
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(FILE_HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)  # never leave a half-written file behind
