"""Spelling works across catalogue controls without automatically changing text."""

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from simple_auction.models import Lot
from simple_auction.ui.components.lot_form import LotForm
from simple_auction.ui.spellcheck import install_spellcheck


class RecordingSpelling:
    def __init__(self):
        self.revision = 0
        self.checked = []

    def correct(self, word):
        self.checked.append(word)
        return word.casefold() != "exellent"

    def suggest(self, word):
        return ["excellent"] if word.casefold() == "exellent" else []

    def ignore(self, word):
        self.revision += 1

    def add(self, word):
        self.revision += 1


def test_catalogue_context_suggestion_edits_and_undoes_across_fields():
    app = QApplication.instance() or QApplication([])
    checker = RecordingSpelling()
    manager = install_spellcheck(app, checker)
    form = LotForm()
    form.load(
        Lot(
            1,
            title="An exellent example",
            serial="serailtypo",
            make="makertypo",
            model="modeltypo",
        ),
        1000,
    )
    form.resize(1100, 850)
    form.show()
    form.title.setFocus()
    QTest.qWait(350)
    original = form.title.text()
    assert "exellent" in original
    form.title.setCursorPosition(original.index("exellent") + 3)
    opened = []

    def choose_suggestion():
        menu = app.activePopupWidget()
        if not isinstance(menu, QMenu):
            return
        opened.append(menu)
        try:
            action = next(
                action
                for action in menu.actions()
                if action.text().replace("&", "") == "excellent"
            )
            action.trigger()
        finally:
            menu.close()

    QTimer.singleShot(0, choose_suggestion)
    point = form.title.cursorRect().center()
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, point, form.title.mapToGlobal(point)
    )
    QApplication.sendEvent(form.title, event)
    assert opened
    assert form.title.text() == original.replace("exellent", "excellent")
    form.title.undo()
    assert form.title.text() == original
    assert form.collect().serial == "serailtypo"
    for field in (
        form.serial,
        form.make,
        form.model,
        form.caliber,
        form.barrel_length,
        form.book_no,
        form.gun_type.lineEdit(),
        form.owner,
        form.title,
    ):
        assert field.property("spellcheck") is not False
        adapter = manager.attach(field)
        assert adapter is not None
        field.setText("exellent")
        QTest.qWait(250)
        assert adapter.qt_spans == [(0, 8)]
        adapter.replace("exellent", 0, 8, "excellent")
        assert field.text() == "excellent"
        field.undo()
        assert field.text() == "exellent"
    assert "exellent" in [word.casefold() for word in checker.checked]
    form.mark_saved()
    form.close()
    form.deleteLater()
    manager.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_revealing_api_key_does_not_enable_spelling_but_notes_are_checked(
    tmp_path, monkeypatch
):
    from simple_auction.services import api_key
    from simple_auction.services.config import Config
    from simple_auction.ui.dossier_dialog import DossierDialog
    from simple_auction.ui.settings import SECTION_RESEARCH, SettingsDialog

    app = QApplication.instance() or QApplication([])
    checker = RecordingSpelling()
    manager = install_spellcheck(app, checker)
    monkeypatch.setattr(api_key, "saved", lambda: None)
    settings = SettingsDialog(
        Config(base_dir=tmp_path, photos_dir=tmp_path / "photos"), []
    )
    settings.show_section(SECTION_RESEARCH)
    settings.key.setText("credentialtypo")
    settings.show_key.setChecked(True)
    settings.show()
    settings.key.setFocus()
    QTest.qWait(250)
    assert settings.key.property("spellcheck") is False
    assert "credentialtypo" not in checker.checked
    settings.close()
    notes = DossierDialog(Lot(1))
    notes.notes.setPlainText("An exellent example")
    notes.show()
    notes.notes.setFocus()
    QTest.qWait(250)
    assert "exellent" in checker.checked
    notes.close()
    settings.deleteLater()
    notes.deleteLater()
    manager.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
