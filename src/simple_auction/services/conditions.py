"""The condition choices (edited in Settings) and their description text.

A lot stores its condition as plain text, so lots keep their condition even
after it's renamed or removed from the list.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConditionOption:
    name: str  # e.g. "Excellent"; also the title suffix " - Excellent"
    note: str = ""  # the sentence after "Condition: Excellent." in descriptions


DEFAULT_CONDITIONS = [
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
