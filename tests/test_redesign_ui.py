"""The redesigned catalogue and shipping controls do what they promise."""

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from simple_auction.models import Lot
from simple_auction.services import shipping
from simple_auction.services.config import Config
from simple_auction.services.importer import Sheet
from simple_auction.ui import main_page, theme
from simple_auction.ui.components.lot_form import LotForm
from simple_auction.ui.components.lot_sidebar import LotSidebar, missing_fields
from simple_auction.ui.shipping_page import ShippingPage
from simple_auction.ui.toast import Toast


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
    yield page
    page._autosave.stop()
    page.form.mark_saved()
    page.close()
    page.deleteLater()
    app.processEvents()


def _visible_lots(sidebar: LotSidebar) -> list[int]:
    return [
        parent.child(j).data(0, Qt.ItemDataRole.UserRole + 1)
        for parent in sidebar._auction_items()
        if not parent.isHidden()
        for j in range(parent.childCount())
        if not parent.child(j).isHidden()
    ]


def test_sidebar_search_filters_lots_and_explains_no_match(app):
    sidebar = LotSidebar()
    sidebar.populate(
        {
            1000: [Lot(1000, title="Colt Python"), Lot(1001, title="Mantel clock")],
            2000: [Lot(2000, title="Winchester 70")],
        }
    )
    sidebar.search.setText("colt")
    assert _visible_lots(sidebar) == [1000]
    assert sidebar.empty_hint.isHidden()
    sidebar.search.setText("2000")  # auction or lot number
    assert _visible_lots(sidebar) == [2000]
    sidebar.search.setText("nothing like this")
    assert _visible_lots(sidebar) == []
    assert not sidebar.empty_hint.isHidden()
    assert "No lots match" in sidebar.empty_hint.text()
    sidebar.search.clear()
    assert _visible_lots(sidebar) == [1000, 1001, 2000]
    sidebar.deleteLater()


def test_incomplete_lots_are_marked_until_title_and_condition_are_set(app):
    assert missing_fields(Lot(1)) == ["Title", "Condition"]
    assert missing_fields(Lot(1, title="Colt")) == ["Condition"]
    assert missing_fields(Lot(1, title="Colt", condition="Good")) == []
    sidebar = LotSidebar()
    sidebar.populate({1000: [Lot(1000)]})
    sidebar.update_lot(1000, Lot(1000, title="Colt", condition="Good"))
    child = sidebar._lot_item(1000, 1000)
    assert child.data(0, Qt.ItemDataRole.UserRole + 4) == []
    sidebar.deleteLater()


def test_previous_and_next_buttons_walk_lots_in_the_auction(window):
    window.create_auction()
    auction, first = window.auction_no, window.lot_no
    window.create_lot(auction)
    second = window.lot_no
    window.create_lot(auction)
    third = window.lot_no
    form = window.form
    assert form.prev_btn.isEnabled() and not form.next_btn.isEnabled()
    form.prev_btn.click()
    assert window.lot_no == second
    form.prev_btn.click()
    assert window.lot_no == first
    assert not form.prev_btn.isEnabled() and form.next_btn.isEnabled()
    form.next_btn.click()
    form.next_btn.click()
    assert window.lot_no == third
    # The sidebar follows the editor.
    assert (
        window.sidebar.tree.currentItem().data(0, Qt.ItemDataRole.UserRole + 1) == third
    )


def test_heading_shows_the_lot_title_and_export_targets_its_auction(app):
    form = LotForm()
    form.load(Lot(41002), 41000)
    assert form.heading.text() == "Untitled lot"
    assert "41000" in form.subtitle.text() and "41002" in form.subtitle.text()
    assert "41000" in form.export_action.text()
    form.title.setText("Colt Python")
    assert form.heading.text() == "Colt Python"
    form.mark_saved()
    form.deleteLater()


def test_blank_gun_type_reads_none_in_the_list_but_leaves_the_field_empty(app):
    from PySide6.QtWidgets import QStyleOptionViewItem

    form = LotForm()
    form.load(Lot(41002, gun_type="Rifle"), 41000)
    combo = form.gun_type
    option = QStyleOptionViewItem()
    combo.itemDelegate().initStyleOption(option, combo.model().index(0, 0))
    assert option.text == "None"
    combo.setCurrentIndex(0)
    combo.activated.emit(0)
    assert combo.currentText() == ""
    assert form.collect().gun_type == ""
    form.mark_saved()
    form.deleteLater()


def test_photos_dropped_on_the_editor_are_added(app, tmp_path):
    photo = tmp_path / "front.jpg"
    Image.new("RGB", (4, 4)).save(photo)
    form = LotForm()
    form.load(Lot(1), 1000)
    mime = QMimeData()
    mime.setUrls(
        [
            QUrl.fromLocalFile(str(photo)),
            QUrl.fromLocalFile(str(tmp_path / "notes.txt")),
        ]
    )
    event = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    form.photo_drop.dropEvent(event)
    assert form.collect().photos == [Path(photo)]
    assert form.is_dirty()
    form.mark_saved()
    form.deleteLater()


def test_serial_lookup_buttons_wait_for_a_serial(app):
    from simple_auction.services.serial_links import SerialLink

    form = LotForm()
    form.set_serial_links([SerialLink("Lindcott", "https://example.test/{serial}")])
    form.load(Lot(1), 1000)
    ((button, _link),) = form._link_buttons
    assert not button.isEnabled()
    form.serial.setText("A123")
    assert button.isEnabled()
    form.mark_saved()
    form.deleteLater()


def test_consignment_disclosure_keeps_values_and_legality_controls_stay_visible(app):
    from PySide6.QtTest import QSignalSpy, QTest

    form = LotForm()
    form.load(Lot(1), 1000)
    form.show()
    app.processEvents()
    edits = QSignalSpy(form.changed)
    assert form.consignment.content.isVisible()
    assert form.c_and_r.isVisible()
    assert form.ca_legality.isVisible()
    assert form.identification_card.isAncestorOf(form.c_and_r)
    assert form.listing_card.isAncestorOf(form.ca_legality)
    assert form.serial_tools.isVisible()
    form.consignment.set_expanded(False)
    form.consignment.toggle.setFocus()
    QTest.keyClick(form.consignment.toggle, Qt.Key.Key_Space)
    assert form.consignment.content.isVisible()
    assert edits.count() == 0
    form.owner.setText("Private collection")
    form.book_no.setText("B42")
    form.ca_legality.setCurrentText("LEGAL FOR CA")
    form.c_and_r.setChecked(True)
    form.consignment.toggle.click()
    lot = form.collect()
    assert (lot.owner, lot.book_no) == ("Private collection", "B42")
    assert lot.ca_legality == "Legal for CA" and lot.c_and_r
    form.load(lot, 1000)
    assert form.consignment.toggle.isChecked()
    assert form.c_and_r.isChecked()
    assert form.ca_legality.currentText() == "LEGAL FOR CA"
    form.load(Lot(2), 1000)
    assert form.consignment.toggle.isChecked()
    assert not form.c_and_r.isChecked()
    assert form.ca_legality.currentText() == "N/A"
    form.close()
    form.deleteLater()


def test_serial_sources_are_always_visible_without_copy_button(app):
    form = LotForm()
    from simple_auction.services.serial_links import DEFAULT_LINKS

    form.set_serial_links(DEFAULT_LINKS)
    form.load(Lot(1), 1000)
    form.show()
    app.processEvents()
    assert form.serial_tools.isVisible()
    assert all(
        button.isVisible() and not button.isEnabled()
        for button, _link in form._link_buttons
    )
    form.serial.setText("A123")
    assert all(
        button.isVisible() and button.isEnabled()
        for button, _link in form._link_buttons
    )
    from PySide6.QtWidgets import QPushButton

    assert all(
        button.text() != "Copy serial"
        for button in form.serial_tools.findChildren(QPushButton)
    )
    form.serial.clear()
    assert form.serial_tools.isVisible()
    assert all(not button.isEnabled() for button, _link in form._link_buttons)
    form.close()
    form.deleteLater()


def _settle(app, rounds: int = 30) -> None:
    for _ in range(rounds):
        app.processEvents()


def test_new_lot_button_adds_a_lot_to_the_open_auction(window):
    window.create_auction()
    auction, first = window.auction_no, window.lot_no
    window.form.new_lot_btn.click()
    assert window.auction_no == auction
    assert window.lot_no == first + 1


@pytest.mark.parametrize("research", [False, True])
@pytest.mark.parametrize("size", [(1280, 800), (1024, 680), (760, 560)])
def test_lot_editor_reflows_instead_of_cutting_off(app, window, size, research):
    from simple_auction.services.serial_links import SerialLink

    links = [
        SerialLink(f"Lookup site {n}", "https://x.test/{serial}") for n in range(4)
    ]
    window.form.set_serial_links(links)
    window.show()
    window.create_auction()
    window.form.serial.setText("A123")
    window.form.research_btn.setChecked(research)
    window.resize(*size)
    _settle(app)
    form = window.form
    scroll = form.stack.currentWidget()
    # The editor never gets narrower than its fields need, and its content is
    # never wider than the visible area (nothing hidden off the right edge).
    assert form.width() >= theme.EDITOR_MIN_WIDTH
    assert scroll.widget().width() <= scroll.viewport().width()
    assert scroll.horizontalScrollBar().maximum() == 0
    for field in (form.serial, form.make, form.model, form.year, form.title):
        assert field.width() >= 140, field.placeholderText()
        assert field.height() >= field.minimumSizeHint().height()
    # Lookup buttons wrap under the serial instead of squeezing it.
    for button, _link in form._link_buttons:
        assert button.width() >= button.sizeHint().width()
        assert form.lookup_links.rect().contains(button.geometry())
    # All lot actions stay on screen.
    for button in (form.prev_btn, form.next_btn, form.new_lot_btn, form.more_btn):
        top_left = button.mapTo(scroll.viewport(), button.rect().topLeft())
        assert scroll.viewport().rect().contains(top_left)
        assert top_left.x() + button.width() <= scroll.viewport().width()


def test_sidebar_is_keyboard_accessible(app):
    from PySide6.QtTest import QTest

    sidebar = LotSidebar()
    sidebar.populate({1000: [Lot(1000)], 2000: [Lot(2000)]})
    assert sidebar.tree.focusPolicy() & Qt.FocusPolicy.TabFocus
    sidebar.show()
    auction = sidebar.tree.topLevelItem(0)
    sidebar.tree.setCurrentItem(auction)
    sidebar.tree.setFocus()
    expanded = auction.isExpanded()
    QTest.keyClick(sidebar.tree, Qt.Key.Key_Return)
    assert auction.isExpanded() != expanded
    sidebar.close()
    sidebar.deleteLater()


def test_shipping_queue_names_the_actual_problem(app, tmp_path):
    headers = [
        "Bidder Number",
        "Name",
        "Shipping Address",
        "City",
        "State",
        "Zip",
        "Lot",
    ]
    rows = [
        ["1", "No Street", "", "Reno", "NV", "89501", "7"],
        ["2", "No Zip", "1 Main", "Reno", "NV", "", "8"],
        ["3", "Fine", "1 Main", "Reno", "NV", "89501", "9"],
    ]
    batch = shipping.build_batch(
        Sheet(headers=headers, rows=rows),
        shipping.guess_mapping(headers),
        "A1",
        "s.csv",
        "US",
    )
    folder = tmp_path / "shipping"
    shipping.save_batch(shipping.batch_path(folder, batch.auction), batch)
    page = ShippingPage(folder)
    try:
        page.activate()
        labels = [page.buyers.item(row, 1).text() for row in range(3)]
        assert labels == ["No street address", "No postal code", "To pack"]
        assert "Missing" in page.buyers.item(0, 1).toolTip()
    finally:
        page._save_timer.stop()
        page.deleteLater()
        app.processEvents()


def test_toast_shows_and_hides_without_blocking(app):
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    toast = Toast(parent)
    toast.show_message("Exported to file.xlsx", ms=10)
    assert toast.isVisible() and toast.text() == "Exported to file.xlsx"
    assert parent.rect().contains(toast.geometry())
    assert toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    toast._timer.timeout.emit()
    assert not toast.isVisible()
    parent.close()
    parent.deleteLater()
    app.processEvents()


def test_icons_follow_the_theme(app):
    from PySide6.QtWidgets import QPushButton

    button = QPushButton()
    theme.apply(app, dark_mode=False)
    theme.set_icon(button, "settings")
    light = button.icon().cacheKey()
    theme.apply(app, dark_mode=True)
    assert button.icon().cacheKey() != light
    theme.apply(app, dark_mode=False)
    button.deleteLater()


def test_autofill_review_ticks_empty_fields_and_fills_the_lot(app):
    from simple_auction.services.title_layout import CustomField
    from simple_auction.ui.autofill_dialog import AutofillDialog

    caliber = CustomField("cal1", "Caliber")
    lot = Lot(1, make="Remington")
    suggestions = {"make": "Colt", "model": "Python", caliber.key: ".357"}
    dialog = AutofillDialog(suggestions, lot, [caliber])
    # Empty fields start ticked; replacing an existing value needs a tick.
    assert dialog.selected() == {"model": "Python", caliber.key: ".357"}
    _check, edit = dialog.rows["make"]
    edit.setText("Colt Firearms")
    edit.textEdited.emit("Colt Firearms")
    assert dialog.selected()["make"] == "Colt Firearms"
    dialog.deleteLater()

    form = LotForm()
    form.set_custom_fields([caliber])
    form.load(lot, 1000)
    form.apply_autofill({"model": "Python", caliber.key: ".357", "owner": "x"})
    collected = form.collect()
    assert (collected.model, collected.custom) == ("Python", {"cal1": ".357"})
    assert collected.owner == ""  # only fields auto-fill may set
    assert form.is_dirty()
    form.mark_saved()
    form.deleteLater()
