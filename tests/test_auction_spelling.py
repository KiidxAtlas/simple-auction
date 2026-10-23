from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from simple_auction.constants import TITLE_MAX_LENGTH
from simple_auction.models import Lot
from simple_auction.services import auction_spelling, catalogue
from simple_auction.ui.auction_spellcheck_dialog import AuctionSpellcheckDialog


class Checker:
    def __init__(self):
        self.words = set()

    def correct(self, word):
        return word != "wrng" or word in self.words

    def suggest(self, word):
        return ["wrong"]

    def add(self, word):
        self.words.add(word)


def test_occurrence_offsets_skip_and_explicit_save():
    review = auction_spelling.Review(
        [
            Lot(2, title="wrng"),
            Lot(1, title="😀 wrng wrng", desc="wrng", serial="ZXABC"),
        ],
        Checker(),
    )
    assert review.current().number == 1
    calls = []

    def save(old, updated):
        calls.append((old, updated))
        return updated

    review.replace("wrong", save)
    assert len(calls) == 1
    assert calls[0][0].title == "😀 wrng wrng"
    assert review.current().start == 8
    review.skip()
    assert review.current().field == "desc"
    review.add()
    assert review.current() is None
    assert review.lots[1].title == "😀 wrong wrng"
    assert review.lots[1].serial == "ZXABC"
    assert review.lots[2].title == "wrng"


def test_failed_save_keeps_occurrence_and_baseline():
    review = auction_spelling.Review([Lot(1, title="wrng")], Checker())

    def fail(*args):
        raise OSError("locked")

    with pytest.raises(OSError, match="locked"):
        review.replace("wrong", fail)
    assert review.current().word == "wrng"
    assert review.lots[1].title == "wrng"
    assert review.saved == 0


@pytest.mark.parametrize("deleted", [False, True])
def test_local_stale_or_deleted_lot_rejected(tmp_path, deleted):
    workbook, details, photos = (
        tmp_path / "1.xlsx",
        tmp_path / "1.json",
        tmp_path / "photos",
    )
    catalogue.add(workbook, details, [Lot(1, title="wrng", serial="ABC123")])
    expected = auction_spelling.load_local(workbook, details, photos)[0]
    if deleted:
        catalogue.delete(workbook, details, photos, {1})
    else:
        catalogue.save(
            workbook, details, photos, replace(expected, owner="Other editor")
        )
    with pytest.raises(ValueError, match="changed or was deleted"):
        auction_spelling.save_local(
            workbook, details, photos, expected, replace(expected, title="wrong")
        )
    remaining = catalogue.load(workbook, details)
    assert remaining == [] if deleted else remaining[0].owner == "Other editor"


def test_local_replacement_preserves_other_fields_and_sidecar(tmp_path):
    workbook, details, photos = (
        tmp_path / "1.xlsx",
        tmp_path / "1.json",
        tmp_path / "photos",
    )
    original = Lot(1, title="wrng", serial="ABC123", custom={"finish": "blue"})
    catalogue.add(workbook, details, [original, Lot(2, title="untouched")])
    expected = auction_spelling.load_local(workbook, details, photos)[0]
    updated, removed = auction_spelling.save_local(
        workbook, details, photos, expected, replace(expected, title="wrong")
    )
    assert removed == {}
    assert updated.title == "wrong"
    loaded = catalogue.load(workbook, details)
    assert loaded[0] == replace(original, title="wrong")
    assert loaded[1].title == "untouched"


def test_dialog_context_suggestions_skip_add_and_failure(monkeypatch):
    app = QApplication.instance() or QApplication([])
    review = auction_spelling.Review(
        [Lot(1, title="😀 wrng wrng", desc="wrng")], Checker()
    )
    calls = []
    dialog = AuctionSpellcheckDialog(
        3, review, lambda old, new: calls.append(new) or new
    )
    assert dialog.context.textCursor().selectedText() == "wrng"
    assert dialog.suggestions.currentText() == "wrong"
    dialog.replace_button.click()
    assert len(calls) == 1
    assert dialog.context.textCursor().selectedText() == "wrng"
    dialog.skip_button.click()
    assert "Description" in dialog.location.text()
    dialog.add_button.click()
    assert "complete" in dialog.location.text()
    assert not dialog.replace_button.isEnabled()
    dialog.close()
    app.processEvents()

    def fail(*args):
        raise OSError("locked")

    review = auction_spelling.Review([Lot(1, title="wrng")], Checker())
    dialog = AuctionSpellcheckDialog(3, review, fail)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog.replace_button.click()
    assert warnings and review.saved == 0
    assert dialog.context.toPlainText() == "wrng"
    dialog.close()


def test_over_limit_title_replacement_keeps_issue_and_never_saves():
    title = "a" * (TITLE_MAX_LENGTH - 5) + " wrng"
    review = auction_spelling.Review([Lot(1, title=title)], Checker())
    issue = review.current()
    calls = []
    with pytest.raises(ValueError, match="title limit"):
        review.replace("wrong", lambda *args: calls.append(args))
    assert calls == []
    assert review.current() == issue
    assert review.lots[1].title == title
    assert review.saved == 0
    review.replace("bad", lambda old, updated: updated)
    assert review.lots[1].title.endswith(" bad")


def test_title_limit_counts_qt_utf16_units_but_description_is_not_limited():
    title = "😀" + "a" * (TITLE_MAX_LENGTH - 7) + " wrng"
    review = auction_spelling.Review([Lot(1, title=title, desc="wrng")], Checker())
    with pytest.raises(ValueError, match="title limit"):
        review.replace("wrong", lambda old, updated: updated)
    review.skip()
    review.replace("x" * (TITLE_MAX_LENGTH + 1), lambda old, updated: updated)
    assert len(review.lots[1].desc) == TITLE_MAX_LENGTH + 1


@pytest.mark.parametrize("serial", ["wrng", "WRNG", "wrng ABC", "wrng-ABC"])
def test_alphabetic_serial_tokens_are_excluded_without_hiding_substrings(serial):
    class Unknown:
        def correct(self, word):
            return False

    review = auction_spelling.Review(
        [Lot(1, title="wrng notwrng", desc="WRNG", serial=serial)], Unknown()
    )
    assert [issue.word for issue in review.pending] == ["notwrng"]
    assert review.lots[1].serial == serial
