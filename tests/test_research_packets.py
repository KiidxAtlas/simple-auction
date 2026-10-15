"""Research capture and reviewed identification, without external AI calls."""

from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from simple_auction.models import Lot
from simple_auction.services.research import (
    COMPARABLES_REQUEST,
    comparable_lot,
    describe_lot,
    safe_source_url,
)
from simple_auction.ui.autofill_dialog import AutofillDialog
from simple_auction.ui.components import research_panel as panel_module
from simple_auction.ui.components.research_panel import ResearchPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app, monkeypatch):
    lot = Lot(
        12,
        serial="SECRET-SERIAL",
        make="Colt",
        model="Python",
        title="private title",
        desc="private notes",
        owner="private owner",
    )
    panel = ResearchPanel(lambda: lot)
    panel.reset(12)
    monkeypatch.setattr(panel_module._Job, "start", lambda self: None)
    yield panel
    panel.reset(None)
    panel.deleteLater()
    app.processEvents()


def complete(panel, app, answer="A documented answer"):
    job = panel._job
    job.text.emit(answer)
    job.done.emit(
        [("Reference", "https://example.com/result"), ("Unsafe", "file:///etc/passwd")]
    )
    job.finished.emit()
    app.processEvents()


def test_completed_answer_requires_explicit_save_and_captures_sources(panel, app):
    packets = []
    panel.packet_saved.connect(packets.append)
    panel.research_lot()
    assert not panel.save_packet_btn.isEnabled()
    panel.save_packet()
    assert packets == []
    complete(panel, app)
    assert packets == []
    assert panel.save_packet_btn.isEnabled()
    panel.save_packet_btn.click()
    assert len(packets) == 1
    assert packets[0]["answer"] == "A documented answer"
    assert packets[0]["sources"] == [
        {"title": "Reference", "url": "https://example.com/result"}
    ]
    assert len(packets[0]["checked_on"]) == 10
    panel.save_packet()
    assert len(packets) == 1


def test_partial_stopped_answer_cannot_be_captured(panel, app):
    packets = []
    panel.packet_saved.connect(packets.append)
    panel.research_lot()
    panel._job.text.emit("Partial answer")
    app.processEvents()
    panel._ask_or_stop()
    panel._job.finished.emit()
    app.processEvents()
    panel.save_packet()
    assert packets == []
    assert not panel.save_packet_btn.isEnabled()


def test_failed_answer_cannot_be_saved_and_reset_ignores_old_job(panel, app):
    panel.research_lot()
    old_job = panel._job
    old_job.text.emit("Partial")
    old_job.failed.emit("Service failed")
    old_job.finished.emit()
    app.processEvents()
    assert not panel.save_packet_btn.isEnabled()
    panel.research_lot()
    old_job = panel._job
    panel.reset(13)
    old_job.done.emit([])
    old_job.finished.emit()
    app.processEvents()
    assert panel._turns == []


def test_comparables_uses_fresh_chat_and_allowlisted_lot(panel):
    panel._chat._previous_id = "conversation-with-private-serial"
    panel.comparables_btn.click()
    job = panel._job
    assert job._chat is not panel._chat
    assert not job._chat.include_photos
    _, request = job._chat._request(job._question, job._lot)
    assert "previous_interaction_id" not in request
    assert "SECRET-SERIAL" not in str(request)
    assert "private" not in str(request)
    assert "Sold" in job._question and "Asking" in job._question
    assert job._question == COMPARABLES_REQUEST
    assert job._lot.serial == "" and job._lot.photos == []


def test_sanitized_context_excludes_custom_free_text_and_photos():
    lot = Lot(
        2,
        serial="secret",
        desc="secret",
        title="secret",
        photos=[Path("secret")],
        custom={"private": "secret"},
        make="Colt",
    )
    sanitized = comparable_lot(lot)
    assert "secret" not in describe_lot(sanitized)
    assert sanitized.make == "Colt"
    assert not sanitized.custom and not sanitized.photos


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/a",
        "javascript:alert(1)",
        "https://user:password@example.com",
        "https://example.com/\nfoo",
        "https://[bad",
        "https://example.com:bad",
    ],
)
def test_unsafe_source_urls_rejected(url):
    assert not safe_source_url(url)


def test_source_opening_rechecks_links(panel, monkeypatch):
    opened = []
    monkeypatch.setattr(panel_module.QDesktopServices, "openUrl", opened.append)
    panel._open_source(QUrl("file:///tmp/private"))
    panel._open_source(QUrl("https://example.com/source"))
    assert [u.toString() for u in opened] == ["https://example.com/source"]


def test_photo_identification_requires_disclosure_consent(panel, monkeypatch, tmp_path):
    lot = panel._lot_provider()
    lot.photos = [tmp_path / "markings.png"]
    prompts = []

    def cancel(*args):
        prompts.append(args[2])
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    panel.identify_btn.click()
    assert panel._job is None
    assert "Google Gemini" in prompts[0] and "O/0" in prompts[0]
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    panel.photos_toggle.setChecked(False)
    panel.identify_btn.click()
    assert panel._job._autofill
    assert panel._chat.include_photos


def test_review_shows_photo_current_value_and_requires_overwrite_opt_in(app, tmp_path):
    path = tmp_path / "markings.png"
    image = QImage(40, 40, QImage.Format.Format_RGB32)
    image.fill(0)
    assert image.save(str(path))
    lot = Lot(2, make="Existing", serial="O123", photos=[path])
    dialog = AutofillDialog({"make": "Suggested", "serial": "0123"}, lot, [])
    assert dialog.selected() == {}
    labels = dialog.findChildren(QLabel)
    assert any("Existing" in label.text() for label in labels)
    assert any("O/0" in label.text() for label in labels)
    assert any(
        label.accessibleName().startswith("Reference photo:")
        and not label.pixmap().isNull()
        for label in labels
    )
    dialog.rows["make"][0].setChecked(True)
    assert dialog.selected() == {"make": "Suggested"}
    dialog.reject()
    assert lot.make == "Existing" and lot.serial == "O123"
    dialog.deleteLater()


def test_reading_controls_keep_full_answers_and_capture_collapsed_sources(panel, app):
    packets = []
    panel.packet_saved.connect(packets.append)
    panel.research_lot()
    first_answer = "Earlier identification remains uncertain."
    complete(panel, app, first_answer)
    assert panel.history_btn.isHidden()
    assert not panel.sources_btn.isHidden()
    assert "Reference" not in panel.transcript.toPlainText()
    panel.sources_btn.click()
    assert "Reference" in panel.transcript.toPlainText()
    panel._ask("What should I check?")
    latest_answer = "Check the markings. " * 150 + "Date still unconfirmed."
    complete(panel, app, latest_answer)
    assert not panel.history_btn.isHidden()
    assert not panel.sources_btn.isChecked()
    visible = panel.transcript.toPlainText()
    assert first_answer not in visible
    assert latest_answer.strip() in visible
    panel.history_btn.click()
    assert first_answer in panel.transcript.toPlainText()
    panel.history_btn.click()
    assert first_answer not in panel.transcript.toPlainText()
    panel.sources_btn.click()
    document = panel.transcript.document().toHtml()
    assert 'href="https://example.com/result"' in document
    assert "file:///etc/passwd" not in document
    panel.sources_btn.click()
    panel.save_packet_btn.click()
    assert packets[0]["answer"] == latest_answer
    assert packets[0]["sources"] == [
        {"title": "Reference", "url": "https://example.com/result"}
    ]
    assert panel.save_packet_btn.isHidden()


def test_research_tools_disclose_without_starting_requests_and_reset_closes_them(
    panel, app
):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    panel.show()
    app.processEvents()
    assert panel.extra_tools.isHidden()
    assert panel.photos_toggle.isVisible()
    assert panel.save_packet_btn.isHidden()
    panel.tools_btn.setFocus()
    QTest.keyClick(panel.tools_btn, Qt.Key.Key_Space)
    assert panel.extra_tools.isVisible()
    assert panel._job is None
    panel.photos_toggle.setChecked(False)
    panel.research_lot()
    assert not panel._job._chat.include_photos
    assert all(
        not button.isEnabled()
        for button in (panel.autofill_btn, panel.identify_btn, panel.comparables_btn)
    )
    complete(panel, app)
    assert panel.save_packet_btn.isVisible()
    assert panel.autofill_btn.isEnabled()
    panel.sources_btn.click()
    panel.reset(13)
    assert panel.extra_tools.isHidden()
    assert not panel.history_btn.isChecked()
    assert not panel.sources_btn.isChecked()
    assert panel.history_btn.isHidden() and panel.sources_btn.isHidden()
    assert panel.save_packet_btn.isHidden()
    assert panel.transcript.toPlainText() == ""
    assert not panel.photos_toggle.isChecked()
    panel.close()


@pytest.mark.parametrize("width", [300, 420])
def test_research_controls_fit_narrow_panel_with_history_and_tools(panel, app, width):
    from PySide6.QtCore import QPoint

    panel.research_lot()
    complete(panel, app)
    panel._ask("Tell me more")
    complete(panel, app)
    panel.resize(width, 800)
    panel.show()
    panel.tools_btn.click()
    for _ in range(5):
        app.processEvents()
    assert panel.width() == width
    for widget in (
        panel.history_btn,
        panel.sources_btn,
        panel.tools_btn,
        panel.save_packet_btn,
        panel.autofill_btn,
        panel.identify_btn,
        panel.comparables_btn,
        panel.photos_toggle,
        panel.question,
        panel.ask_btn,
    ):
        assert widget.isVisible()
        point = widget.mapTo(panel, QPoint())
        assert point.x() >= 0
        assert point.x() + widget.width() <= width
        assert widget.height() >= widget.minimumSizeHint().height()
    assert panel.transcript.height() >= 140
    panel.close()


def test_research_photo_opt_in_defaults_off_for_every_lot(panel, app):
    assert panel.photos_toggle.text() == "Include photos in research"
    assert not panel.photos_toggle.isChecked()
    assert not panel._chat.include_photos
    panel.research_lot()
    assert not panel._job._chat.include_photos
    complete(panel, app)
    panel.photos_toggle.setChecked(True)
    panel.research_lot()
    assert panel._job._chat.include_photos
    complete(panel, app)
    panel.reset(13)
    assert not panel.photos_toggle.isChecked()
    assert not panel._chat.include_photos


def test_photo_control_above_tools_and_identification_to_the_right(panel, app):
    from PySide6.QtCore import QPoint

    panel.resize(500, 850)
    panel.show()
    app.processEvents()
    assert panel.extra_tools.isHidden()
    assert panel.identify_btn.isVisible()
    photos = panel.photos_toggle.mapTo(panel, QPoint())
    tools = panel.tools_btn.mapTo(panel, QPoint())
    identify = panel.identify_btn.mapTo(panel, QPoint())
    assert photos.y() + panel.photos_toggle.height() <= tools.y()
    assert (
        panel.layout().indexOf(panel.tools_row)
        == panel.layout().indexOf(panel.photos_toggle) + 1
    )
    assert identify.y() == tools.y()
    assert identify.x() >= tools.x() + panel.tools_btn.width()
