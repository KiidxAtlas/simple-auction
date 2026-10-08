"""Serial number -> year of manufacture, from a table you maintain.

The table is a JSON file (serial_years.json in the auctions folder):

    {"rules": [
        {"maker": "Winchester", "model": "Model 94",
         "prefix": "", "start": 2600000, "end": 2700000, "year": 1955}
    ]}

A serial matches a rule when it starts with `prefix` (case-insensitive) and
the digits after it fall within start..end. Spaces and dashes are ignored.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

SERIAL_TABLE = "serial_years.json"

_TEMPLATE = {
    "_help": (
        "Add one rule per serial range. A serial matches when it starts with "
        "'prefix' and the digits after it are between 'start' and 'end'."
    ),
    "_example": {
        "maker": "Maker",
        "model": "Model",
        "prefix": "AB",
        "start": 1000,
        "end": 1999,
        "year": 1960,
    },
    "rules": [],
}


@dataclass(frozen=True)
class SerialRule:
    maker: str
    start: int
    end: int
    year: int
    model: str = ""
    prefix: str = ""


@dataclass(frozen=True)
class LookupResult:
    year: int
    maker: str
    model: str = ""

    @property
    def title(self) -> str:
        return f"{self.maker} {self.model}".strip()


def table_path(folder: Path) -> Path:
    return folder / SERIAL_TABLE


def ensure_table(path: Path) -> None:
    """Create an empty table with an example, if there isn't one."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_TEMPLATE, indent=2))


def load_rules(path: Path) -> list[SerialRule]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [
        SerialRule(
            maker=str(r["maker"]),
            model=str(r.get("model", "")),
            prefix=str(r.get("prefix", "")),
            start=int(r["start"]),
            end=int(r["end"]),
            year=int(r["year"]),
        )
        for r in data.get("rules", [])
    ]


def normalize(serial: str) -> str:
    return re.sub(r"[\s-]", "", serial).upper()


def lookup_serial(serial: str, rules: list[SerialRule]) -> list[LookupResult]:
    """Every rule the serial matches (normally zero or one)."""
    s = normalize(serial)
    results: list[LookupResult] = []
    for rule in rules:
        prefix = normalize(rule.prefix)
        rest = s[len(prefix) :]
        if not s.startswith(prefix) or not rest.isdigit():
            continue
        if rule.start <= int(rest) <= rule.end:
            hit = LookupResult(rule.year, rule.maker, rule.model)
            if hit not in results:
                results.append(hit)
    return results
