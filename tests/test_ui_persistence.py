import threading
import time

import pytest
from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from simple_auction.models import Lot
from simple_auction.services import catalogue, excel, storage
from simple_auction.services.config import Config
from simple_auction.ui import main_page, strings
from simple_auction.ui.background import run_io


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(main_page.source_update, "repo_root", lambda: None)
    monkeypatch.setattr(main_page, "is_frozen", lambda: False)
    config = Config(base_dir=tmp_path / "catalogue", photos_dir=tmp_path / "photos")
    page = main_page.MainPage(config)
    yield page
    page._autosave.stop()
    page.form.mark_saved()
    page.close()
    page.deleteLater()
    app.processEvents()


def test_worker_keeps_gui_events_alive_and_blocks_edits(app):
    parent = QWidget()
    parent.show()
    gui_thread = threading.get_ident()
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(parent.isEnabled()))
    timer.start()

    def operation():
        time.sleep(0.08)
        return threading.get_ident()

    try:
        worker_thread = run_io(parent, "Saving…", operation)
        assert worker_thread != gui_thread
        assert len(ticks) >= 2
        assert not any(ticks)
        assert parent.isEnabled()
    finally:
        timer.stop()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_worker_propagates_error_and_restores_ui(app):
    parent = QWidget()

    def fail():
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        run_io(parent, "Saving…", fail)
    assert parent.isEnabled()
    parent.deleteLater()
    app.processEvents()


def test_create_edit_flush_navigate_and_delete_work_end_to_end(window, monkeypatch):
    window.create_auction()
    auction_no, lot_no = window.auction_no, window.lot_no
    assert auction_no is not None and lot_no is not None
    window.form.title.setText("First lot")
    assert window.form.is_dirty()
    assert window.flush()
    assert not window.form.is_dirty()
    assert excel.load_auction(window._path(auction_no))[0].title == "First lot"
    window.create_lot(auction_no)
    assert window.lot_no != lot_no
    window.open_lot(auction_no, lot_no)
    assert window.form.title.text() == "First lot"
    monkeypatch.setattr(window, "_confirm_delete", lambda what: True)
    window.delete_items([(auction_no, lot_no)])
    assert window.auction_no is None
    assert lot_no not in {
        lot.lot_number for lot in excel.load_auction(window._path(auction_no))
    }


def test_failed_save_preserves_dirty_form_and_reports_actual_error(window, monkeypatch):
    window.create_auction()
    window.form.title.setText("Unsaved changes")
    before = window._path(window.auction_no).read_bytes()

    def fail(*args):
        raise UnidentifiedImageError("bad-photo.jpg is not an image")

    monkeypatch.setattr(catalogue, "save", fail)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[1:]))
    assert not window._leave_lot()
    assert window.form.is_dirty()
    assert window.form.title.text() == "Unsaved changes"
    assert window._path(window.auction_no).read_bytes() == before
    assert not window._io_busy and window.isEnabled()
    assert messages[-1][0] == strings.ERROR_TITLE
    assert "bad-photo.jpg" in messages[-1][1]
    assert "Excel" not in messages[-1][1]


def test_workbook_write_failure_uses_workbook_warning_and_retries(window, monkeypatch):
    window.create_auction()
    window.form.title.setText("Unsaved")

    def fail(*args):
        raise excel.ExcelLockedError(window._path(window.auction_no))

    monkeypatch.setattr(catalogue, "save", fail)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[1:]))
    assert not window._leave_lot()
    assert window._autosave.isActive()
    assert window.form.is_dirty()
    assert messages[-1][0] == strings.EXCEL_LOCKED_TITLE


def test_photo_paths_are_not_changed_after_failed_commit_and_retry_succeeds(
    window, tmp_path, monkeypatch
):
    window.create_auction()
    lot = window.form.collect()
    images = window._images_dir(window.auction_no)
    images.mkdir(parents=True)
    first, second = images / f"{lot.lot_number}.jpg", images / f"{lot.lot_number}-1.jpg"
    Image.new("RGB", (100, 100), "red").save(first)
    Image.new("RGB", (100, 100), "blue").save(second)
    lot.photos = [first, second]
    window._show(window.auction_no, lot)
    window.form.set_photos([second])
    window.form.title.setText("Changed")
    original = {p: p.read_bytes() for p in (first, second)}
    path = window._path(window.auction_no)
    real_write = storage.atomic_write

    def fail(path_, data):
        if path_ == path:
            raise PermissionError(13, "denied", str(path))
        real_write(path_, data)

    monkeypatch.setattr(storage, "atomic_write", fail)
    assert not window.flush()
    assert window.form.collect().photos == [second]
    assert {p: p.read_bytes() for p in (first, second)} == original
    monkeypatch.setattr(storage, "atomic_write", real_write)
    # Keep recycle-bin operations isolated from the user's real Trash.
    monkeypatch.setattr(window, "_trash", lambda path: True)
    assert window.flush()
    assert window.form.collect().photos == [first]
    assert first.read_bytes() == original[second]
    assert not second.exists()


def test_refresh_reuses_unchanged_auctions_and_reads_off_gui_thread(
    window, monkeypatch
):
    window.create_auction()
    real = excel.load_auction
    reads = []
    gui_thread = threading.get_ident()

    def record(path):
        reads.append(threading.get_ident())
        return real(path)

    monkeypatch.setattr(excel, "load_auction", record)
    window.refresh()
    assert reads == []
    excel.save_lot(
        window._path(window.auction_no), Lot(lot_number=window.lot_no, title="External")
    )
    window.refresh()
    assert len(reads) == 1 and reads[0] != gui_thread


def test_settings_recovery_cancel_leaves_damaged_file_alone(app, tmp_path, monkeypatch):
    from simple_auction.__main__ import _load_config

    path = tmp_path / "config.json"
    path.write_bytes(b"damaged")

    def cancel(box):
        box.button(QMessageBox.StandardButton.Cancel).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", cancel)
    assert _load_config(path) is None
    assert path.read_bytes() == b"damaged"
    assert list(tmp_path.iterdir()) == [path]


def test_settings_recovery_dialog_restores_backup(app, tmp_path, monkeypatch):
    from simple_auction.__main__ import _load_config

    path = tmp_path / "config.json"
    original = Config(base_dir=tmp_path / "catalogue", photos_dir=tmp_path / "pictures")
    original.save(path)
    original.save(path)
    path.write_bytes(b"damaged")

    def restore(box):
        next(
            button
            for button in box.buttons()
            if button.text() == strings.CONFIG_RESTORE
        ).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", restore)
    recovered = _load_config(path)
    assert recovered.base_dir == original.base_dir
    assert recovered.photos_dir == original.photos_dir
    assert next(tmp_path.glob("config.json.invalid-*")).read_bytes() == b"damaged"
