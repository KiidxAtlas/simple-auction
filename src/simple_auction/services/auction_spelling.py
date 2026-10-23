"""Guided title/description review; persistence stays on existing catalogue paths."""

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

from simple_auction.constants import TITLE_MAX_LENGTH
from simple_auction.services import catalogue, storage
from simple_auction.services.image import lot_photo_files
from simple_auction.services.spelling import word_spans


@dataclass(frozen=True)
class Issue:
    number: int
    field: str
    start: int
    end: int
    word: str


class Review:
    """One occurrence at a time; skipped occurrences do not alter the dictionary."""

    def __init__(self, lots, checker):
        self.lots = {lot.lot_number: deepcopy(lot) for lot in lots}
        self.checker = checker
        self.pending = []
        for lot in sorted(lots, key=lambda lot: lot.lot_number):
            serial_words = {word.casefold() for _, _, word in word_spans(lot.serial)}
            for field in ("title", "desc"):
                for start, end, word in word_spans(getattr(lot, field)):
                    if word.casefold() not in serial_words and not checker.correct(
                        word
                    ):
                        self.pending.append(
                            Issue(lot.lot_number, field, start, end, word)
                        )
        self.saved = 0

    def current(self):
        while self.pending and self.checker.correct(self.pending[0].word):
            self.pending.pop(0)
        return self.pending[0] if self.pending else None

    def skip(self):
        self.pending.pop(0)

    def add(self):
        issue = self.current()
        if self.checker.add(issue.word) is False:
            raise OSError("The dictionary could not be saved")

    def replace(self, text, save):
        issue = self.current()
        if not text.strip() or text == issue.word:
            raise ValueError("Choose or enter a different, nonempty replacement")
        old = self.lots[issue.number]
        source = getattr(old, issue.field)
        replacement = source[: issue.start] + text + source[issue.end :]
        # QLineEdit's maximum length counts UTF-16 code units, not Python code points.
        if (
            issue.field == "title"
            and len(replacement.encode("utf-16-le")) // 2 > TITLE_MAX_LENGTH
        ):
            raise ValueError(
                f"The replacement would exceed the {TITLE_MAX_LENGTH}-character title limit. Choose a shorter replacement."
            )
        updated = replace(old, **{issue.field: replacement})
        # Never advance or mutate the baseline until persistence succeeds.
        committed = save(deepcopy(old), updated)
        self.lots[issue.number] = committed
        self.saved += 1
        self.pending.pop(0)
        delta = len(text) - (issue.end - issue.start)
        self.pending = [
            replace(item, start=item.start + delta, end=item.end + delta)
            if item.number == issue.number and item.field == issue.field
            else item
            for item in self.pending
        ]


def load_local(workbook: Path, details: Path, photos: Path):
    lots = catalogue.load(workbook, details)
    for lot in lots:
        lot.photos = lot_photo_files(lot.lot_number, photos)
    return lots


def save_local(workbook, details, photos, expected, updated):
    """Reject changed/deleted lots; serialize comparison and existing safe save."""
    with storage.lock:
        current = next(
            (
                lot
                for lot in load_local(workbook, details, photos)
                if lot.lot_number == expected.lot_number
            ),
            None,
        )
        if current != expected:
            raise ValueError(
                "This lot changed or was deleted. Close spell check and reopen it before replacing."
            )
        paths, removed = catalogue.save(workbook, details, photos, updated)
        return replace(updated, photos=paths), removed
