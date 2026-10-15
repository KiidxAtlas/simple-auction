import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from simple_auction.models import Lot
from simple_auction.services import review_sheet


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lots(tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (120, 80), "red").save(photo)
    first = Lot(
        41002,
        title="First <draft>",
        owner="Alice",
        desc="Line one\nLine two",
        photos=[photo],
    )
    first.dossier = {
        "research": [
            {
                "question": "Confirm <year>?",
                "answer": "",
                "checked_on": "",
                "sources": [],
            },
            {"question": "Still open?", "answer": "", "checked_on": "", "sources": []},
            {
                "question": "Done",
                "answer": "Confirmed",
                "checked_on": "",
                "sources": [],
            },
        ]
    }
    return [
        first,
        Lot(41001, title="Other owner", owner="Bob"),
        Lot(41000, title="Earlier", owner="Alice"),
    ]


def test_owner_filter_and_stable_grouping(lots):
    assert review_sheet.owners(lots) == ["Alice", "Bob"]
    assert [
        (owner, [lot.lot_number for lot in items])
        for owner, items in review_sheet.grouped_lots(lots)
    ] == [("Alice", [41000, 41002]), ("Bob", [41001])]
    assert len(review_sheet.grouped_lots(lots, "Bob")) == 1
    assert review_sheet.grouped_lots(lots, "missing") == []


def test_document_includes_escaped_details_questions_and_embedded_photos(app, lots):
    document = review_sheet.build_document(41000, lots, owner="Alice")
    plain = document.toPlainText()
    assert "First <draft>" in plain
    assert "Other owner" not in plain
    assert "Line one\nLine two" in plain
    assert "Confirm <year>?" in plain
    assert "Still open?" in plain
    assert "Done" not in plain
    image = document.resource(
        QTextDocument.ResourceType.ImageResource, QUrl("review-image:1")
    )
    assert image is not None and not image.isNull()
    assert lots[0].title == "First <draft>"


def test_pdf_contains_multiple_pages_and_does_not_overwrite(app, lots, tmp_path):
    destination = tmp_path / "review.pdf"
    review_sheet.export_pdf(41000, lots, destination)
    data = destination.read_bytes()
    assert data.startswith(b"%PDF-") and len(data) > 1000
    assert b"/Type /Page" in data
    pdf = QPdfDocument()
    assert pdf.load(str(destination)) == QPdfDocument.Error.None_
    assert pdf.pageCount() == 3
    assert "Earlier" in pdf.getAllText(0).text()
    assert "First <draft>" in pdf.getAllText(1).text()
    assert "Other owner" in pdf.getAllText(2).text()
    pdf.close()
    with pytest.raises(review_sheet.ReviewSheetError, match="not replaced"):
        review_sheet.export_pdf(41000, lots, destination)
    assert destination.read_bytes() == data


def test_missing_photos_are_visible_and_empty_selection_is_rejected(app, tmp_path):
    lot = Lot(41000, photos=[tmp_path / "missing.jpg"])
    document = review_sheet.build_document(41000, [lot])
    assert "Photo unavailable" in document.toPlainText()
    assert "Unassigned" in document.toPlainText()
    with pytest.raises(review_sheet.ReviewSheetError, match="no lots"):
        review_sheet.export_pdf(41000, [], tmp_path / "empty.pdf")
    assert not (tmp_path / "empty.pdf").exists()


def test_dialog_owner_filter_and_empty_state(app, lots):
    from simple_auction.ui.review_sheet_dialog import ReviewSheetDialog

    dialog = ReviewSheetDialog(41000, lots)
    dialog.owner_combo.setCurrentIndex(2)
    assert "Other owner" in dialog.preview.toPlainText()
    assert "First <draft>" not in dialog.preview.toPlainText()
    dialog.close()
    dialog.deleteLater()
    empty = ReviewSheetDialog(41000, [])
    assert not empty.export_button.isEnabled()
    empty.close()
    empty.deleteLater()
    app.processEvents()


def test_backup_dialog_remote_backup_disabled(app, tmp_path):
    from simple_auction.services.config import Config
    from simple_auction.ui.backup_dialog import BackupDialog

    config = Config(base_dir=tmp_path, photos_dir=tmp_path / "photos")
    dialog = BackupDialog(config, remote_client=True)
    assert not dialog.backup_button.isEnabled()
    assert not dialog.activate_button.isEnabled()
    assert dialog.activation_requested is False
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_review_preview_follows_app_font_and_size_changes(app):
    from simple_auction.ui import theme
    from simple_auction.ui.review_sheet_dialog import ReviewSheetDialog

    theme.apply(app, dyslexic_font=True, font_size="large")
    dialog = ReviewSheetDialog(41000, [Lot(41000, title="Catalogue review")])
    try:
        dialog.show()
        app.processEvents()
        font = dialog.preview.document().defaultFont()
        assert "opendyslexic" in font.family().casefold()
        assert font.pixelSize() == 17
        theme.apply(app, dyslexic_font=False, font_size="small")
        app.processEvents()
        font = dialog.preview.document().defaultFont()
        assert "opendyslexic" not in font.family().casefold()
        assert font.pixelSize() == 12
    finally:
        dialog.close()
        dialog.deleteLater()
        theme.apply(app)
        app.processEvents()


def test_activation_is_explicit_preserves_previous_config_and_requires_restart(
    app, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from simple_auction.services.backup import RestoreResult
    from simple_auction.services.config import Config
    from simple_auction.ui.backup_dialog import BackupDialog

    current = Config(
        base_dir=tmp_path / "original", photos_dir=tmp_path / "original-photos"
    )
    restored = Config(
        base_dir=tmp_path / "restored" / "base",
        photos_dir=tmp_path / "restored" / "photos",
    )
    active_path = tmp_path / "active.json"
    current.save(active_path)
    original_bytes = active_path.read_bytes()
    real_save = Config.save
    monkeypatch.setattr(Config, "save", lambda self: real_save(self, active_path))
    dialog = BackupDialog(current)
    dialog.restored = RestoreResult(
        tmp_path / "restored", tmp_path / "restored" / "config.json", restored
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No
    )
    dialog._activate()
    assert active_path.read_bytes() == original_bytes
    assert not dialog.activation_requested
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    dialog._activate()
    assert dialog.activation_requested
    assert active_path.with_suffix(".json.bak").read_bytes() == original_bytes
    loaded, _ = Config._from_bytes(active_path.read_bytes())
    assert loaded.base_dir == restored.base_dir
    assert current.base_dir == tmp_path / "original"
    dialog.deleteLater()
    app.processEvents()
