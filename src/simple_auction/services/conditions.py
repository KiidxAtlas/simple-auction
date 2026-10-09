"""The condition choices and their description text.

They live in data/conditions.yaml in the main folder, one per line:

    Like New: Appears unfired or barely used, no notable wear.
    Excellent: Light handling marks, bore bright.

Edit that file in any text editor (or the table in Settings); the app picks up
changes while it runs. A lot stores its condition as plain text, so lots keep
their condition even after it's renamed or removed from the list.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

FILE_NAME = "conditions.yaml"

FILE_HEADER = """\
# Lot conditions for Simple Auction.
#
# One per line:   Name: text added to the description
#   - The order here is the order in the Condition dropdown.
#   - The first one is the default for new lots.
#   - Picking a condition adds " - Name" to the title and
#     "Condition: Name. <text>" to the end of the description.
#   - Leave the text empty (just "Name:") to add only "Condition: Name."
#   - Put quotes around a name or text that contains a colon, e.g.
#     "Good: see notes": Some wear.
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
        "New condition, used but little, no noticible marring of wood or metal, bluing perfect(except at muzzle or sharp edges.)",
    ),
    ConditionOption(
        "Fine",
        "All original parts; over 30% original finish' sharp lettering, numerals and design on metal and wood; minor marks in wood; good bore.",
    ),
    ConditionOption(
        "Very Good",
        "In perfect working condition, no appreciable wear on working surfaces, no broken parts, no corrosion or pitting, only minor surface dents or scratches.",
    ),
    ConditionOption(
        "Good",
        "In safe working conditiion, minor wear on working surfaces, no broken parts, no corrosion or pitting that will interfere with proper functioning.",
    ),
    ConditionOption(
        "Fair",
        "In safe working condition but well worn, perhaps requiring replacement of minor parts or adjustments which should be indicated in adcertisement, no rust, but may have corrosion pits which do not render article unsafe or inoperable",
    ),
    ConditionOption(
        "Poor",
        "Major and minor parts replaced; major replacement parts required and extensive restoration needed; metal deeply pitted' pincipal lettering, numerals and design obliterated, wood badly scratched, bruised, cracked, or broken; mechanically inoperative; generally undesireable as a collector's firearm.",
    ),
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


def load_file(path: Path) -> list[ConditionOption]:
    """Read conditions.yaml. Raises ConditionsFileError with a readable
    message if the file is missing, isn't valid YAML, or has the wrong shape."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
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


def _scalar(text: str) -> str:
    """One YAML value, quoted only when it has to be (colons, '#', etc.)."""
    dumped = yaml.safe_dump(text, allow_unicode=True, width=1000)
    return dumped.removesuffix("\n").removesuffix("\n...").strip()


def save_file(path: Path, options: list[ConditionOption]) -> None:
    """Write conditions.yaml, one "Name: text" line each, under the header."""
    lines = [
        f"{_scalar(o.name)}: {_scalar(o.note)}" if o.note else f"{_scalar(o.name)}:"
        for o in options
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(FILE_HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)  # never leave a half-written file behind
