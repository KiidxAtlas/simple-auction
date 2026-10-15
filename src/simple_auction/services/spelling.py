"""Local, offline English spelling; no text or dictionary words leave this device.

The bundled pyspellchecker English dictionary is augmented with auction vocabulary
and a personal dictionary beside config.json. This module deliberately has no Qt,
Config or network dependency. Widget owners must exclude passwords and identifiers.
"""

import json
import re
from collections import OrderedDict
from pathlib import Path

from spellchecker import SpellChecker

from simple_auction.services import storage
from simple_auction.services.makers import MAKERS

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
_EXCLUDED = re.compile(
    r"(?:\b[a-z][a-z0-9+.-]*://|\bwww\.)[^\s<>]+"
    r"|[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+"
    r"|\b[\w'’./:+-]*\d[\w'’./:+-]*"
    r"|\b\w*_\w*\b",
    re.IGNORECASE,
)
_VOCABULARY = [
    "auction",
    "auctioneer",
    "auctioneers",
    "catalog",
    "catalogue",
    "cataloguing",
    "consignment",
    "consignor",
    "consignee",
    "firearm",
    "firearms",
    "gunsmith",
    "gunsmithing",
    "handgun",
    "handguns",
    "rifle",
    "rifles",
    "shotgun",
    "shotguns",
    "revolver",
    "revolvers",
    "pistol",
    "pistols",
    "rimfire",
    "centerfire",
    "centrefire",
    "bore",
    "bores",
    "borehole",
    "caliber",
    "calibre",
    "blued",
    "bluing",
    "parkerized",
    "parkerizing",
    "reblued",
    "checkered",
    "checkering",
    "chequered",
    "chequering",
    "buttstock",
    "forend",
    "forearm",
    "stockless",
    "muzzleloader",
    "muzzleloading",
    "flintlock",
    "percussion",
    "breech",
    "breechloader",
    "breechloading",
    "bolt",
    "boltgun",
    "semiautomatic",
    "detachable",
    "magazine",
    "magazines",
    "rifling",
    "rifled",
    "smoothbore",
    "choke",
    "chokes",
    "fullstock",
    "halfstock",
    "doublebarrel",
    "overunder",
    "underlever",
    "sidelock",
    "boxlock",
    "hammerless",
    "proofmark",
    "proofmarks",
    "proofed",
    "buttplate",
    "recoil",
    "pad",
    "sights",
    "scope",
    "scoped",
    "scopes",
    "reticle",
    "bayonet",
    "scabbard",
    "holster",
    "lanyard",
    "sling",
    "swivels",
    "unfired",
    "unfitted",
    "unmarked",
    "unnumbered",
    "matching",
    "nonmatching",
    "aftermarket",
    "milsurp",
    "collectible",
    "collectable",
    "collectibles",
    "collectables",
    "patina",
    "pitting",
    "woodwork",
    "metalwork",
    "NRA",
    "NIB",
    "NIP",
    "NOS",
    "FFL",
    "C&R",
    "LR",
    "ACP",
    "Luger",
    "Magnum",
    "NATO",
]


def word_spans(text: str) -> list[tuple[int, int, str]]:
    """Return prose words with Python character offsets, not Qt UTF-16 offsets.

    Apostrophes stay in words; URLs, emails, numeric/model tokens and snake_case
    identifiers are excluded as units rather than underlining their letter parts.
    Uppercase prose is intentionally not exempt from spelling checks.
    """
    excluded = list(_EXCLUDED.finditer(text))
    result = []
    index = 0
    for match in _WORD.finditer(text):
        while index < len(excluded) and excluded[index].end() <= match.start():
            index += 1
        if index < len(excluded) and excluded[index].start() < match.end():
            continue
        result.append((match.start(), match.end(), match.group()))
    return result


def _normal(word: str) -> str:
    return word.replace("’", "'").casefold()


def _is_word(word: str) -> bool:
    return _WORD.fullmatch(word) is not None


def _remember(cache: OrderedDict, key: str, value, limit: int):
    cache[key] = value
    cache.move_to_end(key)
    if len(cache) > limit:
        cache.popitem(last=False)
    return value


class Spelling:
    """Offline English spellchecking with bounded per-instance result caches.

    Missing dictionaries are normal. Damaged/unreadable ones never prevent typing
    but are re-read (and reported) on Add, never silently replaced. ``revision``
    changes only after session state changes or a personal word commits to disk.
    """

    def __init__(self, path: Path | None = None):
        self.path = (
            Path(path)
            if path is not None
            else Path.home() / ".config" / "simple-auction" / "spelling.json"
        )
        self._checker = SpellChecker(language="en")
        seeds = set(_VOCABULARY)
        for maker, aliases in MAKERS.items():
            for name in (maker, *aliases):
                seeds.update(word for _, _, word in word_spans(name))
        self._checker.word_frequency.load_words(_normal(word) for word in seeds)
        self._ignored: set[str] = set()
        self._personal: set[str] = set()
        self._revision = 0
        self._checks: OrderedDict[str, bool] = OrderedDict()
        self._suggestions: OrderedDict[str, tuple[str, ...]] = OrderedDict()
        try:
            _, self._personal = self._read_personal()
        except OSError, ValueError:
            # Add retries and surfaces the actual error, without destroying data.
            pass
        self._checker.word_frequency.load_words(self._personal)

    @property
    def revision(self) -> int:
        return self._revision

    def _read_personal(self) -> tuple[dict, set[str]]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}, set()
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ValueError(
                f"Cannot read personal spelling dictionary: {self.path}"
            ) from exc
        if not isinstance(data, dict) or not isinstance(data.get("words"), list):
            raise ValueError(f"Invalid personal spelling dictionary: {self.path}")  # noqa: TRY004 - invalid file data, not an API type error
        words = data["words"]
        if any(not isinstance(word, str) or not _is_word(word) for word in words):
            raise ValueError(
                f"Invalid word in personal spelling dictionary: {self.path}"
            )
        return data, {_normal(word) for word in words}

    def _changed(self) -> None:
        self._revision += 1
        self._checks.clear()
        self._suggestions.clear()

    def correct(self, word: str) -> bool:
        key = _normal(word)
        if key in self._checks:
            self._checks.move_to_end(key)
            return self._checks[key]
        root = key.removesuffix("'s")
        correct = (
            not _is_word(word)
            or len(word) > 48
            or key in self._ignored
            or key in self._personal
            or root in self._ignored
            or root in self._personal
            or bool(self._checker.known([key, root]))
        )
        return _remember(self._checks, key, correct, 2048)

    def suggest(self, word: str) -> list[str]:
        if self.correct(word) or len(word) > 32:
            return []
        key = _normal(word)
        if key not in self._suggestions:
            candidates = self._checker.candidates(key) or set()
            ordered = sorted(
                candidates,
                key=lambda candidate: (
                    -self._checker.word_frequency[candidate],
                    candidate,
                ),
            )[:8]
            _remember(self._suggestions, key, tuple(ordered), 256)
        else:
            self._suggestions.move_to_end(key)
        suggestions = self._suggestions[key]
        if word.isupper():
            return [suggestion.upper() for suggestion in suggestions]
        if word[:1].isupper():
            return [suggestion.capitalize() for suggestion in suggestions]
        return list(suggestions)

    def ignore(self, word: str) -> None:
        if not _is_word(word):
            return
        key = _normal(word)
        if key not in self._ignored:
            self._ignored.add(key)
            self._changed()

    def add(self, word: str) -> None:
        """Persist a word atomically or raise OSError/ValueError, never fake success."""
        if not _is_word(word):
            raise ValueError("Only a single word can be added to the dictionary")
        key = _normal(word)
        # Share the existing process-wide file lock and merge any other writer's
        # words/metadata rather than replacing our startup snapshot.
        with storage.lock:
            data, personal = self._read_personal()
            personal.add(key)
            data["words"] = sorted(personal)
            storage.atomic_write(
                self.path,
                (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
            if personal != self._personal:
                self._personal = personal
                self._checker.word_frequency.load_words(personal)
                self._changed()
