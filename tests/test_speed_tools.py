"""Duplicate lot, undo delete, go to lot and the toast action."""

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QWidget

from simple_auction.models import Lot
from simple_auction.services import catalogue
from simple_auction.services.config import Config
from simple_auction.ui import main_page
from simple_auction.ui.components.lot_sidebar import LotSidebar
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
    page._ui_state = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(page, "_confirm_delete", lambda what: True)
    yield page
    page._autosave.stop()
    page.form.mark_saved()
    page.close()
    page.deleteLater()
    app.processEvents()


def test_toast_action_runs_once_and_closes_the_toast(app):
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    toast = Toast(parent)
    calls = []
    toast.show_message("Deleted 1 lot", action=("Undo", lambda: calls.append(1)))
    assert toast.action.isVisible() and toast.action.text() == "Undo"
    assert not toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert parent.rect().contains(toast.geometry())
    toast.action.click()
    toast.action.click()
    assert calls == [1]
    assert not toast.isVisible()
    toast.show_message("Plain")
    assert not toast.action.isVisible()
    assert toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    parent.close()
    parent.deleteLater()


def test_an_expired_toast_forgets_its_action(app):
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    toast = Toast(parent)
    calls = []
    toast.show_message("x", action=("Undo", lambda: calls.append(1)))
    toast._timer.timeout.emit()
    toast.action.click()
    assert calls == []
    parent.close()
    parent.deleteLater()


def test_enter_in_search_opens_the_lot_with_that_number_or_the_first_match(app):
    sidebar = LotSidebar()
    sidebar.populate(
        {1000: [Lot(1000, title="Colt"), Lot(1001, title="Colt 1001 clone")]}
    )
    opened = []
    sidebar.lot_selected.connect(lambda a, n: opened.append((a, n)))
    sidebar.search.setText("1001")
    sidebar.search.returnPressed.emit()
    sidebar.search.setText("colt")
    sidebar.search.returnPressed.emit()
    sidebar.search.setText("nothing")
    sidebar.search.returnPressed.emit()
    assert opened == [(1000, 1001), (1000, 1000)]
    sidebar.deleteLater()


def test_duplicate_starts_a_new_lot_from_the_details_of_this_one(window):
    window.create_auction()
    auction, source = window.auction_no, window.lot_no
    form = window.form
    form.make.setText("Remington")
    form.model.setText("870")
    form.owner.setText("J. Smith")
    form.serial.setText("A123")
    form.condition.setCurrentIndex(0)
    form.c_and_r.setChecked(True)
    assert window.flush()
    window.duplicate_current()
    assert window.auction_no == auction and window.lot_no != source
    assert form.make.text() == "Remington"
    assert form.model.text() == "870"
    assert form.owner.text() == "J. Smith"
    assert form.c_and_r.isChecked()
    assert form.serial.text() == ""
    assert form.condition.currentText() == form.condition.itemText(0)
    assert window.flush()
    saved = {lot.lot_number: lot for lot in window._lots(auction)}
    assert saved[window.lot_no].make == "Remington"
    assert saved[source].serial == "A123"


def test_undo_brings_a_deleted_lot_back(window):
    window.create_auction()
    auction, first = window.auction_no, window.lot_no
    window.form.make.setText("Colt")
    window.form.serial.setText("S1")
    assert window.flush()
    window.create_lot(auction)
    second = window.lot_no
    window.delete_items([(auction, first)])
    assert [lot.lot_number for lot in window._lots(auction)] == [second]
    assert not window.toast.isHidden() and not window.toast.action.isHidden()
    window.toast.action.click()
    lots = {lot.lot_number: lot for lot in window._lots(auction)}
    assert sorted(lots) == sorted([first, second])
    assert lots[first].make == "Colt" and lots[first].serial == "S1"
    assert window.lot_no == first


def test_restore_refuses_a_lot_number_that_is_taken_again(tmp_path):
    book, details = tmp_path / "1000.xlsx", tmp_path / "1000.details.json"
    lot = Lot(1000, title="Colt")
    catalogue.add(book, details, [lot])
    with pytest.raises(ValueError):
        catalogue.restore(book, details, [lot], {})


def test_needs_attention_chip_counts_and_filters_incomplete_lots(app):
    sidebar = LotSidebar()
    sidebar.populate(
        {
            1000: [Lot(1000, title="Colt", condition="Good"), Lot(1001, title="Colt")],
            2000: [Lot(2000, title="Ruger", condition="Good")],
        }
    )
    assert sidebar.attention.text() == "Needs attention (1)"
    sidebar.attention.setChecked(True)
    visible = [
        parent.child(j).data(0, Qt.ItemDataRole.UserRole + 1)
        for parent in sidebar._auction_items()
        if not parent.isHidden()
        for j in range(parent.childCount())
        if not parent.child(j).isHidden()
    ]
    assert visible == [1001]
    assert sidebar._auction_items()[1].isHidden()
    sidebar.update_lot(1000, Lot(1001, title="Colt", condition="Good"))
    assert sidebar.attention.text() == "Needs attention (0)"
    sidebar.attention.setChecked(False)
    assert not sidebar._auction_items()[1].isHidden()
    sidebar.deleteLater()
