"""Recognise the maker named in a lot title."""

import re

# Maker name as lookup sites spell it -> other ways titles write it.
MAKERS: dict[str, list[str]] = {
    "Beretta": [],
    "Browning": [],
    "Colt": [],
    "CZ": ["Ceska Zbrojovka"],
    "FN": ["FN Herstal", "Fabrique Nationale"],
    "Glock": [],
    "Harrington & Richardson": ["H&R", "Harrington and Richardson"],
    "Heckler & Koch": ["H&K", "HK", "Heckler and Koch"],
    "Henry": ["Henry Repeating Arms"],
    "Ithaca": [],
    "Iver Johnson": [],
    "Kimber": [],
    "Marlin": [],
    "Mauser": [],
    "Mossberg": ["O.F. Mossberg"],
    "Remington": [],
    "Ruger": ["Sturm Ruger", "Sturm, Ruger"],
    "Savage Arms": ["Savage"],
    "SIG Sauer": ["Sig", "Sig Sauer", "SIG"],
    "Smith & Wesson": ["S&W", "Smith and Wesson"],
    "Springfield Armory": ["Springfield"],
    "Taurus": [],
    "Walther": [],
    "Weatherby": [],
    "Winchester": [],
}

_ALIASES = sorted(
    (
        (alias, maker)
        for maker, aliases in MAKERS.items()
        for alias in [maker, *aliases]
    ),
    key=lambda pair: -len(pair[0]),  # longest first: "Smith & Wesson" before "Smith"
)


def guess_maker(title: str) -> str | None:
    """The maker named earliest in the title, e.g. "1972 S&W Model 29" -> S&W."""
    best: tuple[int, str] | None = None
    for alias, maker in _ALIASES:
        m = re.search(rf"(?<![\w&]){re.escape(alias)}(?![\w&])", title, re.IGNORECASE)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), maker)
    return best[1] if best else None
