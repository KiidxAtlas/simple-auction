"""Manual descriptions own their text; name formatting does not restore deletions."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication

from simple_auction.services import catalogue
from simple_auction.services.config import Config
from simple_auction.services.listing import title_case_name
from simple_auction.ui import main_page


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(main_page.source_update, "repo_root", lambda: None)
    monkeypatch.setattr(main_page, "is_frozen", lambda: False)
    page = main_page.MainPage(
        Config(base_dir=tmp_path / "catalogue", photos_dir=tmp_path / "photos")
    )
    page._ui_state = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    page.create_auction()
    page.form.set_desc_fields(["make", "model", "caliber"])
    yield page
    page._autosave.stop()
    page.form.mark_saved()
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.mark.parametrize(
    "edited",
    [
        "",
        "Only my own description.",
        "Make: Rem\nModel: Wing\nCaliber: 12\n\nCondition: Good. Personally inspected.",
    ],
)
def test_deleted_and_partially_edited_description_text_stays_saved(window, edited):
    form = window.form
    auction, number = window.auction_no, window.lot_no
    form.make.setText("remington")
    form.model.setText("870 wingmaster")
    form.caliber.setText("12 GA")
    form.condition.setCurrentText("Good")
    form._apply_title_fields()
    assert "Make: Remington" in form.desc.toPlainText()
    form.desc.setPlainText(edited)
    # Changes to source fields must not restore text the user removed or edited.
    form.make.setText("sig sauer")
    form.model.setText("p320")
    form.caliber.setText(".45 ACP")
    form.condition.setCurrentText("Excellent")
    form.make.editingFinished.emit()
    form.model.editingFinished.emit()
    assert form.desc.toPlainText() == edited
    assert window.flush()
    window.create_lot(auction)
    window.open_lot(auction, number)
    assert form.desc.toPlainText() == edited
    form.model.setText("P365")
    form.model.editingFinished.emit()
    assert form.desc.toPlainText() == edited
    assert window.flush()
    saved = catalogue.load(window._path(auction), window._details(auction))[0]
    assert saved.desc == edited
    assert saved.make == "Sig Sauer"
    assert saved.model == "P365"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("remington", "Remington"),
        ("sig sauer", "Sig Sauer"),
        ("870 wingmaster", "870 Wingmaster"),
        ("smith & wesson", "Smith & Wesson"),
        ("p320", "P320"),
        ("AR-15", "AR-15"),
        ("M&P", "M&P"),
        ("McMillan", "McMillan"),
        ("  sig sauer  ", "Sig Sauer"),
        ("", ""),
    ],
)
def test_name_capitalization_keeps_model_codes(value, expected):
    assert title_case_name(value) == expected


def test_names_capitalize_on_finish_and_autosave_before_focus_changes(window):
    form = window.form
    form.make.setText("sig sauer")
    form.model.setText("p320 xfive")
    form.serial.setText("abc-001x")
    # Autosave while still typing normalizes the saved names and generated title.
    assert window.flush()
    saved = catalogue.load(
        window._path(window.auction_no), window._details(window.auction_no)
    )[0]
    assert (saved.make, saved.model) == ("Sig Sauer", "P320 Xfive")
    assert "Sig Sauer P320 Xfive" in saved.title
    assert saved.serial == "abc-001x"
    form.make.editingFinished.emit()
    form.model.editingFinished.emit()
    assert form.make.text() == "Sig Sauer"
    assert form.model.text() == "P320 Xfive"
    assert form.title.text().count("Sig Sauer") == 1
