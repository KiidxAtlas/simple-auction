import csv
import io
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from simple_auction.services import shipping
from simple_auction.services.config import Config
from simple_auction.services.importer import Sheet
from simple_auction.ui import main_page
from simple_auction.ui.shipping_import_dialog import ShippingImportDialog
from simple_auction.ui.shipping_page import ShippingPage

HEADERS = [
    "Bidder Number",
    "Name",
    "Email",
    "Shipping Address",
    "City",
    "State",
    "Zip",
    "Lot",
    "Description",
]
ROWS = [
    [
        "0042",
        "Jane Doe",
        "jane@example.test",
        "12 Main St",
        "Boston",
        "MA",
        "02108",
        "12A",
        "Vase",
    ],
    [
        "0042",
        "Jane Doe",
        "jane@example.test",
        "12 Main St",
        "Boston",
        "MA",
        "02108",
        "45",
        "Clock",
    ],
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app, tmp_path):
    sheet = Sheet(headers=HEADERS, rows=ROWS)
    batch = shipping.build_batch(
        sheet, shipping.guess_mapping(HEADERS), "Auction 1", "source.csv", "US"
    )
    folder = tmp_path / "shipping"
    shipping.save_batch(shipping.batch_path(folder, batch.auction), batch)
    page = ShippingPage(folder)
    page.activate()
    page.show()
    app.processEvents()
    yield page
    page._save_timer.stop()
    page.close()
    page.deleteLater()
    app.processEvents()


def test_column_preview_and_cancel_do_not_write_anything(app, tmp_path):
    dialog = ShippingImportDialog(
        tmp_path / "source.csv", Sheet(headers=HEADERS, rows=ROWS)
    )
    dialog.show()
    app.processEvents()
    assert dialog.batch.buyers[0].zip == "02108"
    assert dialog.preview.rowCount() == 1
    dialog.columns["lot"].setCurrentIndex(0)
    assert dialog.batch is None
    assert not dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()
    dialog.reject()
    assert list(tmp_path.iterdir()) == []
    dialog.deleteLater()
    app.processEvents()


def test_import_pack_split_export_reload_pipeline(page, tmp_path, monkeypatch):
    # Exercise real file-dialog handlers using a confirmed column dialog.
    path = tmp_path / "actual-report.csv"
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(HEADERS)
    writer.writerows(ROWS)
    path.write_text(stream.getvalue())
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    monkeypatch.setattr(
        ShippingImportDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: messages.append(a[-1]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a: messages.append(a[-1]))
    page.import_button.click()
    assert page.batch.auction == "actual-report"
    assert len(page.batch.buyers) == 1
    page.add_box.click()
    assert len(page.batch.buyers[0].packages) == 2
    assert page.packages.currentIndex() == 1
    page.lots.item(1).setCheckState(Qt.CheckState.Checked)
    buyer = page.batch.buyers[0]
    assert buyer.packages[0].lots == ["12A"]
    assert buyer.packages[1].lots == ["45"]
    for index in (0, 1):
        page.packages.setCurrentIndex(index)
        for key, value in (
            ("weight_lb", 2.03125),
            ("length", 12),
            ("width", 8),
            ("height", 6),
        ):
            page.measurements[key].setText(str(value))
        page.ready_next.click()
    assert page.export_button.isEnabled()
    output = tmp_path / "pirate.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(output), ""))
    page.export_button.click()
    assert (
        len(list(csv.DictReader(io.StringIO(output.read_text(encoding="utf-8-sig")))))
        == 2
    )
    assert not page.export_button.isEnabled()
    assert not page.measurements["weight_lb"].isEnabled()
    assert page.address["name"].isReadOnly()
    assert str(output) in page.validation.text()
    assert shipping.load_batch(page.path) == page.batch
    page.import_button.click()  # same auction cannot discard packing/export history
    assert "already has saved" in messages[-1]
    assert all(p.exported_at for p in page.batch.buyers[0].packages)


def test_completed_report_does_not_reappear_over_confirmation(tmp_path):
    report = tmp_path / "report.csv"
    with report.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADERS)
        writer.writerows(ROWS)
    # Use the real application and nested dialog loops. QTest.qWait alone lets
    # deleteLater run early and misses the delayed modal window seen by users.
    script = textwrap.dedent(
        """
        import os
        from pathlib import Path
        import sys
        import traceback
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QFileDialog, QProgressDialog
        from simple_auction.services import shipping
        from simple_auction.ui.shipping_import_dialog import ShippingImportDialog
        from simple_auction.ui.shipping_page import ShippingPage

        app = QApplication([])
        report = Path(sys.argv[1])
        page = ShippingPage(report.parent / "shipping")
        page.show()
        QFileDialog.getOpenFileName = lambda *args: (str(report), "")
        original_exec = ShippingImportDialog.exec

        def confirm(dialog):
            def check():
                try:
                    assert not any(
                        isinstance(widget, QProgressDialog) and widget.isVisible()
                        for widget in app.topLevelWidgets()
                    ), "Completed progress dialog reappeared"
                    assert app.activeModalWidget() is dialog
                    assert page.isEnabled()
                    assert dialog.preview.rowCount() == 1
                    dialog.buttons.button(dialog.buttons.StandardButton.Ok).click()
                except BaseException:
                    traceback.print_exc()
                    os._exit(1)

            # Stay in confirmation beyond Qt's default four-second show timer.
            QTimer.singleShot(4500, check)
            return original_exec(dialog)

        ShippingImportDialog.exec = confirm

        def start():
            try:
                page.import_report()
                assert len(page.batch.buyers) == 1
                assert len(page.batch.buyers[0].lots) == 2
                assert shipping.load_batch(page.path) == page.batch
                assert page.isEnabled()
                page.close()
                app.quit()
            except BaseException:
                traceback.print_exc()
                os._exit(1)

        QTimer.singleShot(0, start)
        sys.exit(app.exec())
        """
    )
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(Path(shipping.__file__).resolve().parents[2]),
    }
    result = subprocess.run(
        [sys.executable, "-c", script, str(report)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_edits_reset_packed_state_and_autosave_survives_reload(page):
    for spin in page.measurements.values():
        spin.setText("10")
    page.ready_next.click()
    assert page.export_button.isEnabled()
    page.address["zip"].setText("")
    assert not page.batch.buyers[0].packages[0].packed
    assert not page.export_button.isEnabled()
    assert "postal code" in page.validation.text()
    page.address["zip"].setText("02108")
    page.pickup.setChecked(True)
    assert not page.measurements["weight_lb"].isEnabled()
    assert page.flush()
    assert page.reload(page.folder)
    assert page.batch.buyers[0].pickup
    assert page.address["zip"].text() == "02108"


def test_removing_box_moves_its_lots_and_search_filters(page):
    page.add_box.click()
    page.lots.item(1).setCheckState(Qt.CheckState.Checked)
    page.remove_box.click()
    buyer = page.batch.buyers[0]
    assert len(buyer.packages) == 1
    assert set(buyer.packages[0].lots) == set(buyer.lots)
    page.search.setText("12A")
    assert not page.buyers.isRowHidden(0)
    page.search.setText("unknown")
    assert page.buyers.isRowHidden(0)


def test_autosave_writes_progress_and_failed_save_keeps_edits(page, monkeypatch):
    from PySide6.QtTest import QTest

    page.address["address2"].setText("Suite 7")
    QTest.qWait(650)
    assert not page.dirty
    assert shipping.load_batch(page.path).buyers[0].address2 == "Suite 7"
    previous = page.path.read_bytes()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(shipping, "save_batch", fail)
    page.address["address2"].setText("Suite 8")
    assert not page.flush(warn=False)
    assert page.dirty
    assert page.address["address2"].text() == "Suite 8"
    assert page.path.read_bytes() == previous
    assert "disk full" in page.notice.text()


def test_header_switch_preserves_catalogue_and_save_failure_stays_in_shipping(
    app, tmp_path, monkeypatch
):
    monkeypatch.setattr(main_page.source_update, "repo_root", lambda: None)
    monkeypatch.setattr(main_page, "is_frozen", lambda: False)
    window = main_page.MainPage(
        Config(base_dir=tmp_path, photos_dir=tmp_path / "photos")
    )
    window.show()
    try:
        window.create_auction()
        window.form.title.setText("Preserve my lot")
        current = window.lot_no
        window.shipping_button.click()
        assert window.pages.currentWidget() is window.shipping
        assert not window.splitter.isVisible()
        assert not window.form.is_dirty()
        assert window.shipping_button.text() == "Back to Catalogue"
        window.shipping_button.click()
        assert window.pages.currentWidget() is window.splitter
        assert window.lot_no == current
        assert window.form.title.text() == "Preserve my lot"
        window.shipping_button.click()
        monkeypatch.setattr(window.shipping, "flush", lambda **kw: False)
        window.shipping_button.click()
        assert window.pages.currentWidget() is window.shipping
        assert not window.close()
    finally:
        monkeypatch.setattr(window.shipping, "flush", lambda **kw: True)
        window._autosave.stop()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_failed_catalogue_save_prevents_header_switch(app, tmp_path, monkeypatch):
    monkeypatch.setattr(main_page.source_update, "repo_root", lambda: None)
    monkeypatch.setattr(main_page, "is_frozen", lambda: False)
    window = main_page.MainPage(
        Config(base_dir=tmp_path, photos_dir=tmp_path / "photos")
    )
    try:
        monkeypatch.setattr(window, "_leave_lot", lambda: False)
        window.shipping_button.click()
        assert window.pages.currentWidget() is window.splitter
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_every_box_must_be_weighed_and_measured_before_export(page):
    assert page.packing_panel.isVisible()
    assert page.box_controls.isVisible()
    assert page.ready_next.isVisible()
    assert not hasattr(page, "include_measurements")
    assert not page.export_button.isEnabled()
    assert "weight" in page.validation.text()
    for edit in page.measurements.values():
        edit.setText("10")
    assert not page.export_button.isEnabled()  # still needs Mark ready
    page.ready_next.click()
    assert page.export_button.isEnabled()
    assert "1 box" in page.export_button.text()


def test_import_preview_hides_columns_until_requested(app, tmp_path):
    dialog = ShippingImportDialog(
        tmp_path / "report.csv", Sheet(headers=HEADERS, rows=ROWS)
    )
    dialog.show()
    app.processEvents()
    try:
        assert dialog.preview.rowCount() == 1
        assert not dialog.mapping_panel.isVisible()
        dialog.mapping_button.click()
        assert dialog.mapping_panel.isVisible()
        dialog.columns["zip"].setCurrentIndex(0)
        assert not dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_unknown_columns_open_mapping_and_block_import(app, tmp_path):
    dialog = ShippingImportDialog(
        tmp_path / "report.csv",
        Sheet(headers=["Unknown", "Columns"], rows=[["a", "b"]]),
    )
    dialog.show()
    app.processEvents()
    try:
        assert dialog.mapping_panel.isVisible()
        assert not dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()
        assert "lot number" in dialog.summary.text()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_ready_and_next_and_status_filters(page):
    from dataclasses import replace

    buyer = replace(
        page.batch.buyers[0],
        id="0050",
        name="Sam Taylor",
        lots={"81": "Bowl"},
        packages=[shipping.Package(lots=["81"])],
    )
    page.batch.buyers.append(buyer)
    page._fill_buyers()
    for spin in page.measurements.values():
        spin.setText("10")
    assert page.ready_next.isEnabled()
    page.ready_next.click()
    assert page.batch.buyers[0].packages[0].packed
    assert page._buyer().id == "0050"
    page.status_filter.setCurrentIndex(page.status_filter.findData("ready"))
    assert page._buyer().id == "0042"
    assert page.buyers.isRowHidden(1)
    page.status_filter.setCurrentIndex(page.status_filter.findData("attention"))
    assert page._buyer().id == "0050"
    page.search.setText("nobody")
    assert not page.editor.isEnabled()


def test_dropping_csv_runs_the_import_flow(page, tmp_path, monkeypatch):
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent

    report = tmp_path / "dropped.csv"
    with report.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADERS)
        writer.writerows(ROWS)
    monkeypatch.setattr(
        ShippingImportDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(report))])
    event = QDropEvent(
        QPointF(30, 30),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    page.dropEvent(event)
    assert event.isAccepted()
    assert page.batch.auction == "dropped"
    assert len(page.batch.buyers[0].lots) == 2
    assert shipping.load_batch(page.path) == page.batch


def test_typing_pounds_tab_order_and_export(page, tmp_path, monkeypatch):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit

    weight = page.measurements["weight_lb"]
    assert all(isinstance(edit, QLineEdit) for edit in page.measurements.values())
    weight.setFocus()
    QTest.keyClicks(weight, "2.5")
    QTest.keyClick(weight, Qt.Key.Key_Up)
    assert weight.text() == "2.5"
    assert page.batch.buyers[0].packages[0].weight_oz == 40
    for previous, key, value in (
        ("weight_lb", "length", "12"),
        ("length", "width", "8"),
        ("width", "height", "6"),
    ):
        QTest.keyClick(page.measurements[previous], Qt.Key.Key_Tab)
        assert page.measurements[key].hasFocus()
        QTest.keyClicks(page.measurements[key], value)
    QTest.keyClick(page.measurements["height"], Qt.Key.Key_Return)
    assert page.batch.buyers[0].packages[0].packed
    output = tmp_path / "pounds.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
    page.export_button.click()
    rows = list(csv.DictReader(io.StringIO(output.read_text(encoding="utf-8-sig"))))
    assert rows[0]["Weight (Pounds)"] == "2.5"
    assert "Weight (Ounces)" not in rows[0]
    assert shipping.load_batch(page.path).buyers[0].packages[0].weight_oz == 40


def test_existing_ounce_weight_displays_in_pounds_without_mutating_it(page):
    package = page.batch.buyers[0].packages[0]
    package.weight_oz = 32.5
    page._fill_editor()
    assert page.measurements["weight_lb"].text() == "2.03125"
    page.measurements["length"].setText("12")
    assert package.weight_oz == 32.5
    assert page.flush()
    assert page.reload(page.folder)
    assert page.measurements["weight_lb"].text() == "2.03125"
    assert page.batch.buyers[0].packages[0].weight_oz == 32.5


@pytest.mark.parametrize("invalid", ["", "-1", "nan", "1e3"])
def test_incomplete_weight_cannot_export_old_measurement(page, invalid):
    for edit in page.measurements.values():
        edit.setText("10")
    page.ready_next.click()
    assert page.export_button.isEnabled()
    page.measurements["weight_lb"].setText(invalid)
    assert not page.export_button.isEnabled()
    assert not page.ready_next.isEnabled()
    assert page.batch.buyers[0].packages[0].weight_oz == 0
    assert page.flush()


def test_layout_keeps_packing_actions_visible_at_normal_and_narrow_widths(page):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QBoxLayout

    for width, direction in (
        (1120, QBoxLayout.Direction.LeftToRight),
        (900, QBoxLayout.Direction.TopToBottom),
    ):
        page.resize(width, 670)
        QTest.qWait(30)
        assert page.detail_columns.direction() == direction
        for widget in (
            page.measurements["weight_lb"],
            page.measurements["height"],
            page.ready_next,
            page.export_button,
        ):
            rectangle = widget.rect()
            top_left = widget.mapTo(page, rectangle.topLeft())
            bottom_right = widget.mapTo(page, rectangle.bottomRight())
            assert page.rect().contains(top_left)
            assert page.rect().contains(bottom_right)
