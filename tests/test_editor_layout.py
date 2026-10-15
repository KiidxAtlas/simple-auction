"""Editor alignment, readable CA labels, and backwards-compatible title wording."""

from dataclasses import replace

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QBoxLayout

from simple_auction.models import Lot
from simple_auction.services import network
from simple_auction.services.title_layout import update_title
from simple_auction.ui import theme
from simple_auction.ui.components.lot_form import LotForm


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def form(app):
    theme.apply(app)
    form = LotForm()
    yield form
    form.mark_saved()
    form.close()
    form.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    theme.apply(app)
    app.processEvents()


@pytest.mark.parametrize("photo_count", [0, 4])
@pytest.mark.parametrize("large_font", [False, True])
def test_identification_and_listing_match_with_photos_below_identification(
    app, form, tmp_path, photo_count, large_font
):
    theme.apply(
        app, dyslexic_font=large_font, font_size="large" if large_font else "medium"
    )
    photos = []
    for number in range(photo_count):
        path = tmp_path / f"photo-{number}.jpg"
        Image.new("RGB", (120, 80), "gray").save(path)
        photos.append(path)
    form.resize(1100, 950)
    form.load(Lot(1, title="Specimen", photos=photos), 1000)
    form.show()
    for _ in range(3):
        app.processEvents()
    identification, listing, photo_card = (
        form.identification_card,
        form.listing_card,
        form.photos_card,
    )
    assert form.top_cards.direction() == QBoxLayout.Direction.LeftToRight
    assert abs(identification.width() - listing.width()) <= 1
    assert identification.height() == listing.height()
    assert identification.y() == listing.y()
    assert (
        listing.mapTo(form, listing.rect().topLeft()).x()
        > identification.mapTo(form, identification.rect().topLeft()).x()
    )
    assert (
        photo_card.mapTo(form, photo_card.rect().topLeft()).y()
        >= identification.mapTo(form, identification.rect().bottomLeft()).y()
    )
    assert abs(photo_card.width() - identification.width()) <= 1
    assert form.consignment.content.isVisible()
    form.resize(520, 950)
    for _ in range(3):
        app.processEvents()
    assert form.top_cards.direction() == QBoxLayout.Direction.TopToBottom
    assert identification.width() == listing.width() == photo_card.width()
    assert form.scroll.horizontalScrollBar().maximum() == 0


def test_legality_is_beside_condition_and_curio_relic_is_in_identification(app, form):
    from PySide6.QtCore import QPoint

    form.resize(1100, 950)
    form.set_title_fields(["make", "title", "condition", "ca_legality", "c_and_r"])
    form.load(Lot(1, make="Colt", title="Specimen"), 1000)
    form.show()
    for _ in range(3):
        app.processEvents()
    assert form.identification_card.isAncestorOf(form.c_and_r)
    assert form.listing_card.isAncestorOf(form.condition)
    assert form.listing_card.isAncestorOf(form.ca_legality)
    condition = form.condition.mapTo(form.listing_card, QPoint())
    legality = form.ca_legality.mapTo(form.listing_card, QPoint())
    assert condition.y() == legality.y()
    assert legality.x() >= condition.x() + form.condition.width()
    form.ca_legality.setCurrentText("LEGAL FOR CA")
    form.ca_legality.activated.emit(form.ca_legality.currentIndex())
    form.c_and_r.click()
    lot = form.collect()
    assert lot.ca_legality == "Legal for CA" and lot.c_and_r
    assert "LEGAL FOR CA" in lot.title and "C&R ELIGIBLE" in lot.title


@pytest.mark.parametrize(
    ("canonical", "visible"),
    [("Legal for CA", "LEGAL FOR CA"), ("Not CA legal", "NOT LEGAL FOR CA")],
)
def test_legality_labels_keep_existing_storage_and_shared_contract(
    form, canonical, visible
):
    form.load(Lot(1, ca_legality=canonical), 1000)
    assert form.ca_legality.currentText() == visible
    assert form.ca_legality.currentData() == canonical
    saved = form.collect()
    assert saved.ca_legality == canonical
    assert network.validated_lot(network.lot_data(saved)).ca_legality == canonical
    form.ca_legality.setCurrentText("N/A")
    assert form.collect().ca_legality == "N/A"
    form.ca_legality.setCurrentText(visible)
    assert form.collect().ca_legality == canonical


@pytest.mark.parametrize(
    ("canonical", "old_words", "new_words"),
    [
        ("Legal for CA", "OK FOR CA", "LEGAL FOR CA"),
        ("Not CA legal", "NOT CA LEGAL", "NOT LEGAL FOR CA"),
    ],
)
@pytest.mark.parametrize("before_title", [False, True])
def test_old_legality_title_words_are_replaced_once(
    canonical, old_words, new_words, before_title
):
    fields = (
        ["ca_legality", "make", "title"]
        if before_title
        else ["make", "title", "ca_legality"]
    )
    title = (
        f"{old_words} Colt Specimen" if before_title else f"Colt Specimen {old_words}"
    )
    expected = (
        f"{new_words} Colt Specimen" if before_title else f"Colt Specimen {new_words}"
    )
    lot = Lot(1, title=title, make="Colt", ca_legality=canonical, title_fields=fields)
    updated = update_title(title, lot, fields, lot, fields)
    assert updated == expected
    saved = replace(lot, title=updated)
    assert update_title(updated, saved, fields, saved, fields) == expected
    assert update_title(title, lot, fields, lot, ["make", "title"]) == "Colt Specimen"


def test_migrating_title_wording_does_not_restore_deleted_qualifier():
    fields = ["make", "title", "ca_legality"]
    lot = Lot(
        1,
        title="Colt Specimen",
        make="Colt",
        ca_legality="Legal for CA",
        title_fields=fields,
    )
    assert update_title(lot.title, lot, fields, lot, fields) == lot.title
