import base64
import json

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from simple_auction.models import Lot
from simple_auction.services import catalogue, dossier, excel, lot_details, network
from simple_auction.services.config import Config
from simple_auction.services.serial_links import DEFAULT_LINKS
from simple_auction.ui import main_page
from simple_auction.ui.components.lot_form import LotForm
from simple_auction.ui.dossier_dialog import DossierDialog
from simple_auction.ui.workflow_dialogs import DuplicateDialog, WorkQueueDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def finding(year="1901", url="https://example.org/records"):
    return {
        "year": year,
        "source_url": url,
        "checked_on": "2026-01-02",
        "notes": "Model not confirmed",
        "attachment": "",
    }


def test_old_records_and_packet_roundtrip_are_independent(tmp_path):
    path = tmp_path / "details.json"
    path.write_text('{"1":{"make":"Colt"}}')
    lots = [Lot(1), Lot(2)]
    lot_details.fill(path, lots)
    assert lots[0].dossier == lots[1].dossier == {}
    packet = dossier.empty()
    packet["findings"] = [finding(), finding("1902")]
    packet["findings"][0]["attachment"] = (
        "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4\nexample").decode()
    )
    lots[0].dossier = packet
    lot_details.save(path, lots[0])
    loaded = [Lot(1), Lot(2)]
    lot_details.fill(path, loaded)
    assert loaded[0].dossier == packet
    assert dossier.conflicting_years(loaded[0].dossier)
    loaded[0].dossier["findings"][0]["notes"] = "Changed"
    assert packet["findings"][0]["notes"] == "Model not confirmed"
    assert loaded[1].dossier == {}


@pytest.mark.parametrize(
    "change",
    [
        {"status": "Pretend verified"},
        {"review_approved": "yes"},
        {"required_shots": ["Serial", "Serial"]},
        {"version": 2},
        {"findings": [finding(url="file:///private/file")]},
        {"findings": [finding() | {"attachment": "data:application/pdf;base64,!!!"}]},
        {
            "research": [
                {
                    "question": "q",
                    "answer": "a",
                    "checked_on": "2026-01-02",
                    "sources": [{"title": "x", "url": "javascript:alert(1)"}],
                }
            ]
        },
    ],
)
def test_invalid_packet_rejected_before_standalone_and_shared_save(tmp_path, change):
    lot = Lot(1, dossier=dossier.empty() | change)
    with pytest.raises((ValueError, TypeError)):
        lot_details.prepare(tmp_path / "details.json", [lot])
    with pytest.raises((ValueError, TypeError)):
        network.validated_lot(network.lot_data(lot))


def test_corrupt_packet_is_not_overwritten(tmp_path):
    path = tmp_path / "details.json"
    original = json.dumps({"1": {"dossier": {"status": "bad"}}})
    path.write_text(original)
    with pytest.raises(lot_details.DetailsFileError):
        lot_details.save(path, Lot(1))
    assert path.read_text() == original


def test_readiness_and_duplicate_boundaries(tmp_path):
    packet = dossier.empty() | {
        "status": "Source checked",
        "required_shots": list(dossier.SHOTS),
        "review_approved": True,
        "research_complete": True,
    }
    lot = Lot(
        1,
        title="Colt Python",
        condition="Good",
        make="Colt",
        model="Python",
        serial="AB 123",
        photos=[tmp_path / "photo.jpg"],
        dossier=packet,
    )
    assert dossier.issues(lot) == []
    auctions = {
        1000: [lot, Lot(2, make="colt", serial="AB123")],
        2000: [
            Lot(3, make="Ruger", serial="AB123"),
            Lot(4, make="Colt", serial="AB-123"),
        ],
    }
    assert [
        (a, other.lot_number) for a, other in dossier.duplicates(lot, 1000, auctions)
    ] == [(1000, 2)]
    assert dossier.duplicates(Lot(1, serial="123"), 1000, auctions) == []
    assert any(target == "duplicates" for _label, target in dossier.issues(lot, True))
    packet["duplicate_notes"] = "Different model; serial independently confirmed"
    assert dossier.issues(lot, True) == []
    packet["findings"] = [finding(), finding("1902")]
    assert any("Conflicting" in label for label, _target in dossier.issues(lot))


def test_official_routing_and_copy_preserves_serial(app, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "simple_auction.ui.components.lot_form.QDesktopServices.openUrl",
        lambda url: opened.append(bytes(url.toEncoded()).decode("ascii")) or True,
    )
    form = LotForm()
    form.set_serial_links(DEFAULT_LINKS)
    form.load(Lot(1, make="Ruger", serial="001-AB 23"), 1000)
    next(
        button for button, link in form._link_buttons if link.name == "Ruger official"
    ).click()
    assert opened == ["https://ruger.com/dataProcess/serialHistory/?serial=001-AB%2023"]
    next(
        button for button, link in form._link_buttons if link.name == "Colt official"
    ).click()
    assert opened[-1] == "https://www.colt.com/serial-lookup/"
    assert QApplication.clipboard().text() == "001-AB 23"
    assert form.collect().serial == "001-AB 23"
    form.make.setText("Colt")
    assert all(button.isEnabled() for button, _link in form._link_buttons)
    assert [link.name for _button, link in form._link_buttons] == [
        "Lindcott Armory",
        "Colt official",
        "Ruger official",
        "Browning dating guide",
    ]
    form.mark_saved()
    form.deleteLater()


def test_evidence_dialog_cancel_and_separate_sources(app, tmp_path):
    lot = Lot(1)
    dialog = DossierDialog(lot)
    dialog.year.setText("1901–1903")
    dialog.source.setText("https://example.org/a")
    dialog._save_finding()
    dialog.year.setText("1905")
    dialog.source.setText("https://example.org/b")
    photo = tmp_path / "serial.png"
    Image.new("RGB", (20, 20), "blue").save(photo)
    dialog._attach(photo)
    dialog._save_finding()
    assert len(dialog.packet["findings"]) == 2
    assert "Conflicting" in dialog.conflict.text()
    assert dialog.packet["findings"][1]["attachment"].startswith(
        "data:image/png;base64,"
    )
    assert lot.dossier == {}
    dialog.reject()
    assert lot.dossier == {}
    dialog.deleteLater()


def test_comparables_keep_sold_and_asking_separate(app):
    dialog = DossierDialog(Lot(1))
    for kind, price in (("Sold", "900"), ("Asking", "1500")):
        dialog.comp_inputs["kind"].setCurrentText(kind)
        dialog.comp_inputs["price"].setText(price)
        dialog.comp_inputs["url"].setText("https://example.org/" + kind)
        dialog.comp_inputs["premium"].setText("Excluded" if kind == "Sold" else "N/A")
        dialog._save_comp()
    assert [(r["kind"], r["price"]) for r in dialog.packet["comparables"]] == [
        ("Sold", "900"),
        ("Asking", "1500"),
    ]
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.deleteLater()


def test_queue_targets_and_duplicate_review(app, monkeypatch):
    lot = Lot(1000, make="Colt", serial="123")
    queue = WorkQueueDialog({1000: [lot]})
    parent = queue.tree.topLevelItem(0)
    issue = next(
        parent.child(i)
        for i in range(parent.childCount())
        if "Missing title" in parent.child(i).text(1)
    )
    queue._open(issue)
    assert queue.target == (1000, 1000, "title")
    duplicate = DuplicateDialog([(2000, Lot(2001, title="Earlier lot"))])
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    duplicate._choose("separate")
    assert duplicate.choice is None
    duplicate.notes.setText("Distinct variant; checked markings")
    duplicate._choose("separate")
    assert duplicate.explanation == "Distinct variant; checked markings"
    queue.deleteLater()
    duplicate.deleteLater()


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


def test_research_capture_saved_with_lot_and_survives_reopen(window):
    window.create_auction()
    auction, number = window.auction_no, window.lot_no
    record = {
        "question": "Identify markings",
        "answer": "Unconfirmed variant",
        "checked_on": "2026-01-02",
        "sources": [{"title": "Record", "url": "https://example.org"}],
    }
    window.research.packet_saved.emit(record)
    loaded = catalogue.load(window._path(auction), window._details(auction))[0]
    assert loaded.dossier["research"] == [record]
    window.create_lot(auction)
    window.open_lot(auction, number)
    assert window.form.collect().dossier["research"] == [record]


def test_shared_database_roundtrip_keeps_packet_and_old_fields(tmp_path):
    cfg = Config(base_dir=tmp_path / "catalogue", photos_dir=tmp_path / "photos")
    excel.create_auction(excel.auction_path(cfg.auctions_dir, 1000))
    packet = dossier.empty()
    packet["findings"] = [finding()]
    catalogue.add(
        excel.auction_path(cfg.auctions_dir, 1000),
        lot_details.details_path(cfg.data_dir, 1000),
        [Lot(1000, make="Colt", dossier=packet)],
    )
    db = network.Database(cfg)
    snapshot = db.dispatch("snapshot", {})
    record = snapshot["auctions"]["1000"][0]
    assert record["dossier"] == packet
    assert (
        network.validated_lot(
            {k: v for k, v in record.items() if k != "photos"}
        ).dossier
        == packet
    )


def test_final_dialog_save_keeps_pending_source_comparable_and_question(app):
    dialog = DossierDialog(Lot(1))
    dialog.year.setText("1901–1903")
    dialog.source.setText("https://example.org/factory")
    dialog.comp_inputs["kind"].setCurrentText("Sold")
    dialog.comp_inputs["url"].setText("https://example.org/sale")
    dialog.comp_inputs["price"].setText("900")
    dialog.research_question.setText("Can the consignor confirm matching numbers?")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.packet["findings"][0]["year"] == "1901–1903"
    assert dialog.packet["comparables"][0]["price"] == "900"
    assert dialog.packet["research"][0]["answer"] == ""
    from simple_auction.services.review_sheet import unresolved_questions

    assert unresolved_questions(Lot(1, dossier=dialog.packet)) == [
        "Can the consignor confirm matching numbers?"
    ]
    dialog.deleteLater()


def test_invalid_pending_source_keeps_dialog_open(app, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    dialog = DossierDialog(Lot(1))
    dialog.source.setText("https://example.org:invalid")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.packet["findings"] == []
    dialog.deleteLater()


def test_review_approval_invalidated_by_material_edits_not_packet_approval(
    app, tmp_path
):
    form = LotForm()
    form.load(
        Lot(1, title="A specimen", make="Colt", model="Python", serial="ABC"), 1000
    )
    approved = dossier.empty() | {
        "status": "Documented",
        "review_approved": True,
        "research_complete": True,
        "required_shots": list(dossier.SHOTS),
    }
    form.set_dossier(approved)
    assert form.collect().dossier["review_approved"] is True
    form.desc.setPlainText("Reviewed listing, now changed")
    assert form.collect().dossier["review_approved"] is False
    assert form.collect().dossier["status"] == "Documented"
    form.set_dossier(approved)
    form.serial.setText("ABCD")
    assert form.collect().dossier["status"] == "Unverified"
    assert form.collect().dossier["research_complete"] is False
    assert form.collect().dossier["review_approved"] is False
    form.set_dossier(approved)
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (20, 20)).save(photo)
    form.add_photos([photo])
    assert form.collect().dossier["required_shots"] == []
    assert form.collect().dossier["review_approved"] is False
    form.mark_saved()
    form.deleteLater()
