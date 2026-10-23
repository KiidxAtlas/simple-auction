from threading import get_ident
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from simple_auction.models import Lot
from simple_auction.services import catalogue, network
from simple_auction.services.config import Config
from simple_auction.ui import auction_spellcheck_dialog, main_page, spellcheck


class Checker:
    def correct(self, word):
        return word != "wrng"

    def suggest(self, word):
        return ["wrong"]


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("stale", [False, True])
def test_button_saves_reviewed_occurrence_with_conflict_guard(
    tmp_path, monkeypatch, shared, stale
):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_page.source_update, "repo_root", lambda: None)
    monkeypatch.setattr(main_page, "is_frozen", lambda: False)
    gui_thread = get_ident()
    scanned_threads = []

    class RecordingChecker(Checker):
        def correct(self, word):
            scanned_threads.append(get_ident())
            return super().correct(word)

    monkeypatch.setattr(
        spellcheck,
        "install_spellcheck",
        lambda app: SimpleNamespace(checker=RecordingChecker()),
    )
    config = Config(base_dir=tmp_path / "catalogue", photos_dir=tmp_path / "photos")
    page = main_page.MainPage(config)
    try:
        catalogue.add(
            page._path(1),
            page._details(1),
            [Lot(1, title="wrng", desc="wrng"), Lot(2, title="wrng")],
        )
        if shared:
            database = network.Database(config)
            page.client = network.LocalClient(database, tmp_path / "cache")
        page.refresh()
        page.open_lot(1, 1)
        seen = []

        def execute(dialog):
            assert dialog.review.current().word == "wrng"
            assert scanned_threads and scanned_threads[0] != gui_thread
            if stale:
                if shared:
                    expected = page.client.snapshot()["auctions"]["1"][0]
                    lot = page.client.materialize(expected)
                    lot.owner = "Other editor"
                    page.client.save_lot(1, lot, expected)
                else:
                    lot = catalogue.load(page._path(1), page._details(1))[0]
                    lot.owner = "Other editor"
                    catalogue.save(
                        page._path(1), page._details(1), page._images_dir(1), lot
                    )
                with pytest.raises((ValueError, network.Conflict)):
                    dialog.review.replace("wrong", dialog.save)
                assert dialog.review.saved == 0
            else:
                dialog.review.replace("wrong", dialog.save)
                assert dialog.review.current().field == "desc"
                assert dialog.review.saved == 1
            seen.append(True)
            return 0

        monkeypatch.setattr(
            auction_spellcheck_dialog.AuctionSpellcheckDialog, "exec", execute
        )
        page.spellcheck_button.click()
        assert seen
        if shared:
            lots = [
                page.client.materialize(record)
                for record in page.client.snapshot()["auctions"]["1"]
            ]
        else:
            lots = catalogue.load(page._path(1), page._details(1))
        assert lots[0].title == ("wrng" if stale else "wrong")
        assert lots[0].desc == "wrng"
        assert lots[1].title == "wrng"
        if stale:
            assert lots[0].owner == "Other editor"
    finally:
        page._autosave.stop()
        page.form.mark_saved()
        page.close()
        page.deleteLater()
        app.processEvents()
