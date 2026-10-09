"""Open each dialog for real, so a typo in one fails here, not in the
installed app (which has no console to show the error)."""

import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from simple_auction.services.updates import UpdateInfo
from simple_auction.ui import strings

SRC = Path(__file__).parents[1] / "src" / "simple_auction"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _dispose(app, dialog) -> None:
    """Delete through Qt, before the app goes away at the end of the run."""
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_every_ui_string_used_exists():
    used = {
        name
        for path in SRC.rglob("*.py")
        for name in re.findall(r"\bstrings\.([A-Z][A-Z0-9_]*)", path.read_text())
    }
    missing = sorted(name for name in used if not hasattr(strings, name))
    assert missing == []


@pytest.mark.parametrize(
    "info",
    [
        None,  # failed check
        UpdateInfo("0.0.1", "https://x/SimpleAuction-Setup-0.0.1.exe", "", False),
        UpdateInfo(
            "99.0.0",
            "https://x/SimpleAuction-Setup-99.0.0.exe",
            "## Added\n\n- Things",
            True,
            "a" * 64,
        ),
    ],
    ids=["failed", "up-to-date", "update-available"],
)
def test_update_dialog_opens_in_every_state(app, info, monkeypatch):
    from simple_auction.ui import update_dialog
    from simple_auction.ui.update_dialog import UpdateDialog

    # No real GitHub request from tests.
    monkeypatch.setattr(update_dialog.UpdateCheckThread, "start", lambda self: None)
    dialog = UpdateDialog(None, info)
    if info is None:
        # What a failed check shows, with its reason.
        dialog._on_check_complete(None, "Couldn't reach GitHub (timed out).")
    dialog.show()
    app.processEvents()
    _dispose(app, dialog)


def test_import_dialog_opens(app, tmp_path):
    from simple_auction.services.importer import Sheet
    from simple_auction.ui.import_dialog import ImportDialog

    sheet = Sheet(headers=["Lot", "Title"], rows=[[41000, "Colt"]])
    dialog = ImportDialog(
        tmp_path / "old.xlsx", sheet, [], lambda n: set(), 41000, 1000
    )
    dialog.show()
    app.processEvents()
    assert len(dialog.lots()) == 1
    _dispose(app, dialog)


@pytest.mark.parametrize("state", ["failed", "up-to-date", "available", "local-edits"])
def test_source_update_dialog_opens_in_every_state(app, state, monkeypatch, tmp_path):
    from simple_auction.services.source_update import SourceStatus
    from simple_auction.ui import source_update_dialog
    from simple_auction.ui.source_update_dialog import SourceUpdateDialog

    # No real git fetch from tests.
    monkeypatch.setattr(source_update_dialog.SourceCheckThread, "start", lambda s: None)
    dialog = SourceUpdateDialog(tmp_path)
    status = {
        "failed": None,
        "up-to-date": SourceStatus(behind=0),
        "available": SourceStatus(behind=2, changes=["Add import", "Fix updates"]),
        "local-edits": SourceStatus(behind=1, changes=["Fix"], local_changes=True),
    }[state]
    dialog._on_checked(status, "network down" if status is None else "")
    dialog.show()
    app.processEvents()
    _dispose(app, dialog)
