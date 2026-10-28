import json
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication

from simple_auction.models import Lot
from simple_auction.services import lot_details, network
from simple_auction.services.config import Config, ConfigFileError
from simple_auction.services.title_layout import DEFAULT_FIELDS, update_title
from simple_auction.ui.components.lot_form import LotForm
from simple_auction.ui.settings import SettingsDialog


@pytest.fixture
def app(monkeypatch):
    from simple_auction.ui import settings

    monkeypatch.setattr(settings.api_key, "saved", lambda: None)
    return QApplication.instance() or QApplication([])


def test_title_reorder_and_disable_preserve_custom_words():
    old = Lot(1, make="Colt", model="1911", serial="ABC", condition="Good")
    fields = list(DEFAULT_FIELDS)
    # A title in the older style is recognised and rewritten.
    title = "Colt 1911 S/N: ABC Government - Good"
    new_fields = ["condition", "title", "model", "make"]
    result = update_title(title, old, fields, old, new_fields)
    assert result == "Good Condition Government 1911 Colt"
    saved = replace(old, title_fields=new_fields)
    assert update_title(result, saved, new_fields, saved, new_fields) == result
    assert update_title(result, saved, new_fields, saved, ["title"]) == "Government"


def test_default_title_matches_the_house_style():
    fields = list(DEFAULT_FIELDS)
    lot = Lot(
        1,
        make="Arsenal",
        model="SAM7SF",
        caliber="7.62x39",
        gun_type="Rifle",
        serial="BE 53 1936",
        condition="Excellent",
        ca_legality="Legal for CA",
    )
    title = update_title("", Lot(1), fields, lot, fields)
    assert title == (
        "Arsenal SAM7SF 7.62x39 Rifle SN: BE 53 1936 Excellent Condition LEGAL FOR CA"
    )
    saved = replace(lot, title=title, title_fields=fields)
    # Own words go after the type; edits replace only the generated parts.
    with_words = update_title(
        "Arsenal SAM7SF 7.62x39 Rifle w/ scope SN: BE 53 1936 Excellent Condition LEGAL FOR CA",
        saved,
        fields,
        replace(saved, condition="Very Good", ca_legality="Not CA legal"),
        fields,
    )
    assert with_words == (
        "Arsenal SAM7SF 7.62x39 Rifle w/ scope SN: BE 53 1936 "
        "Very Good Condition NOT LEGAL FOR CA"
    )
    # A serial alone is enough for a title; a condition alone isn't.
    assert update_title("", Lot(1), fields, Lot(1, serial="X1"), fields) == "SN: X1"
    assert update_title("", Lot(1), fields, Lot(1, condition="Good"), fields) == ""


def test_title_optional_values_and_edits():
    fields = ["make", "title", "barrel_length", "ca_legality"]
    old = Lot(1, make="Colt")
    title = update_title("Government", Lot(1), fields, old, fields)
    assert title == "Colt Government"
    new = replace(old, barrel_length="5 inches", ca_legality="Not CA legal")
    title = update_title(title, old, fields, new, fields)
    assert title == "Colt Government Barrel length: 5 inches NOT LEGAL FOR CA"
    cleared = replace(new, barrel_length="", ca_legality="N/A")
    assert update_title(title, new, fields, cleared, fields) == "Colt Government"


def test_c_and_r_is_added_to_and_removed_from_the_title():
    fields = list(DEFAULT_FIELDS)
    lot = Lot(1, make="Mosin", model="91/30", condition="Good")
    title = update_title("", Lot(1), fields, lot, fields)
    assert title == "Mosin 91/30 Good Condition"
    eligible = replace(lot, c_and_r=True)
    title = update_title(title, lot, fields, eligible, fields)
    assert title == "Mosin 91/30 Good Condition C&R"
    assert update_title(title, eligible, fields, lot, fields) == (
        "Mosin 91/30 Good Condition"
    )
    # C&R alone doesn't make a title.
    assert update_title("", Lot(1), fields, Lot(1, c_and_r=True), fields) == ""


def test_the_previous_default_title_layout_gains_c_and_r(tmp_path):
    from simple_auction.services.title_layout import PREVIOUS_DEFAULT_FIELDS

    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {"base_dir": str(tmp_path), "title_fields": list(PREVIOUS_DEFAULT_FIELDS)}
        )
    )
    assert Config.load(path).title_fields == list(DEFAULT_FIELDS)


def test_title_length_and_empty_condition_only():
    fields = list(DEFAULT_FIELDS)
    lot = Lot(1, condition="Good")
    assert update_title("", Lot(1), fields, lot, fields) == ""
    title = update_title("x" * 150, Lot(1), fields, lot, fields)
    assert len(title) == 100
    assert title.endswith(" Good Condition")


def test_deleted_title_parts_stay_deleted_until_their_value_changes():
    fields = list(DEFAULT_FIELDS)
    lot = Lot(1, make="Colt", model="Python", serial="X1", condition="Good")
    title = update_title("Nice gun", Lot(1), fields, lot, fields)
    assert title == "Colt Python Nice gun SN: X1 Good Condition"
    saved = replace(lot, title_fields=fields)
    edited = "Python Nice gun SN: X1"  # the make and condition were deleted
    assert update_title(edited, saved, fields, saved, fields) == edited
    changed = replace(saved, make="Ruger", condition="Fair")
    assert update_title(edited, saved, fields, changed, fields) == (
        "Ruger Python Nice gun SN: X1 Fair Condition"
    )
    # Other parts are still recognised and replaced, not added again.
    assert update_title(
        edited, saved, fields, replace(saved, model="1911"), fields
    ) == ("1911 Nice gun SN: X1")


def test_editor_does_not_put_back_deleted_generated_text(app):
    form = LotForm()
    from simple_auction.services.conditions import ConditionOption

    form.set_conditions([ConditionOption("Good", "Configured note.")])
    form.set_desc_fields(["make", "model"])
    form.load(Lot(1), 41000)
    form.make.setText("Colt")
    form.model.setText("Python")
    form.title.setText("Nice gun")
    form.condition.setCurrentIndex(form.condition.findText("Good"))
    form._apply_title_fields()
    assert form.title.text() == "Colt Python Nice gun Good Condition"
    assert form.desc.toPlainText().startswith("Make: Colt\nModel: Python\n\n")
    assert "Condition: Good." in form.desc.toPlainText()
    # Delete the make and condition from the title, and the Make line and
    # condition sentence from the description.
    form.title.setText("Python Nice gun")
    form.title.editingFinished.emit()
    form.desc.setPlainText("Model: Python\n\nBlued.")
    form._apply_title_fields()  # e.g. finishing another field
    assert form.title.text() == "Python Nice gun"
    assert form.desc.toPlainText() == "Model: Python\n\nBlued."
    saved = form.collect_for_save()
    assert saved.title == "Python Nice gun"
    reopened = LotForm()
    reopened.load(saved, 41000)
    reopened._apply_title_fields()
    assert reopened.title.text() == "Python Nice gun"
    assert reopened.desc.toPlainText() == "Model: Python\n\nBlued."
    # Changed title fields still update, but deleted description text stays gone.
    form.make.setText("Ruger")
    form._apply_title_fields()
    assert form.title.text() == "Ruger Python Nice gun"
    assert form.desc.toPlainText() == "Model: Python\n\nBlued."
    for f in (form, reopened):
        f.mark_saved()
        f.deleteLater()


def test_config_title_fields_roundtrip_and_legacy(tmp_path):
    path = tmp_path / "config.json"
    config = Config(base_dir=tmp_path, title_fields=["title", "make", "barrel_length"])
    config.save(path)
    assert Config.load(path).title_fields == config.title_fields
    path.write_text(json.dumps({"base_dir": str(tmp_path)}))
    assert Config.load(path).title_fields == list(DEFAULT_FIELDS)
    # The old built-in default is upgraded; it was never chosen by the user.
    from simple_auction.services.title_layout import LEGACY_DEFAULT_FIELDS

    old = {"base_dir": str(tmp_path), "title_fields": list(LEGACY_DEFAULT_FIELDS)}
    path.write_text(json.dumps(old))
    assert Config.load(path).title_fields == list(DEFAULT_FIELDS)


@pytest.mark.parametrize(
    "fields", [["make"], ["title", "title"], ["title", "unknown"], "title"]
)
def test_invalid_layout_does_not_overwrite_config(tmp_path, fields):
    path = tmp_path / "config.json"
    raw = json.dumps({"title_fields": fields})
    path.write_text(raw)
    with pytest.raises(ConfigFileError, match="title_fields"):
        Config.load(path)
    assert path.read_text() == raw


def test_optional_details_and_layout_roundtrip(tmp_path):
    path = tmp_path / "details.json"
    original = Lot(
        1,
        barrel_length="18 inches",
        ca_legality="Legal for CA",
        c_and_r=True,
        title_fields=["title", "barrel_length"],
    )
    lot_details.save(path, original)
    loaded = [Lot(1), Lot(2)]
    lot_details.fill(path, loaded)
    assert loaded[0] == original
    assert loaded[1].barrel_length == ""
    assert loaded[1].ca_legality == "N/A"
    lot_details.save(path, Lot(1))
    lot_details.fill(path, loaded)
    assert loaded[0] == Lot(1)


def test_invalid_saved_layout_is_reported(tmp_path):
    path = tmp_path / "details.json"
    path.write_text('{"1": {"title_fields": ["unknown"]}}')
    with pytest.raises(lot_details.DetailsFileError, match="title layout"):
        lot_details.save(path, Lot(1))


def test_shared_lots_support_new_fields_and_old_records():
    lot = Lot(
        1,
        barrel_length="5 inches",
        ca_legality="Not CA legal",
        c_and_r=True,
        title_fields=["title", "ca_legality"],
    )
    assert network.validated_lot(network.lot_data(lot)) == lot
    legacy = network.lot_data(Lot(1))
    for key in ("barrel_length", "ca_legality", "c_and_r", "title_fields"):
        legacy.pop(key)
    assert network.validated_lot(legacy) == Lot(1)
    with pytest.raises(ValueError, match="C&R"):
        network.validated_lot({**legacy, "c_and_r": "yes"})
    legacy["ca_legality"] = "maybe"
    with pytest.raises(ValueError, match="CA legality"):
        network.validated_lot(legacy)


def test_settings_order_checkboxes_and_cancel(app, tmp_path):
    config = Config(base_dir=tmp_path)
    dialog = SettingsDialog(config, [])
    assert dialog.nav.item(2).text() == "Listing fields"
    rows = dialog.title_fields_list
    assert rows.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove
    # The model's moveRows operation is also used by Qt internal drag-and-drop.
    from PySide6.QtCore import QModelIndex

    # Default order: make, model, caliber, type, [own wording], serial,
    # condition, CA legality, C&R. Move "make" below "condition", untick caliber.
    assert rows.model().moveRows(QModelIndex(), 0, 1, QModelIndex(), 7)
    rows.item(1).setCheckState(Qt.CheckState.Unchecked)  # Caliber
    assert dialog.title_fields() == [
        "model",
        "gun_type",
        "title",
        "serial",
        "condition",
        "make",
        "ca_legality",
        "c_and_r",
    ]
    dialog.reject()
    assert config.title_fields == list(DEFAULT_FIELDS)
    dialog.close()


def test_lot_editor_defaults_optional_fields_and_reorder(app):
    form = LotForm()
    form.load(Lot(1), 41000)
    assert form.barrel_length.text() == ""
    assert form.ca_legality.currentText() == "N/A"
    form.title.setText("Government")
    form.make.setText("Colt")
    form.make.editingFinished.emit()
    assert form.title.text() == "Colt Government"
    form.set_title_fields(["title", "make", "barrel_length", "ca_legality"])
    assert form.title.text() == "Government Colt"
    form.barrel_length.setText("5 inches")
    form.barrel_length.editingFinished.emit()
    form.ca_legality.setCurrentText("NOT LEGAL FOR CA")
    form.ca_legality.activated.emit(form.ca_legality.currentIndex())
    assert (
        form.title.text() == "Government Colt Barrel length: 5 inches NOT LEGAL FOR CA"
    )
    saved = form.collect()
    assert saved.barrel_length == "5 inches"
    assert saved.ca_legality == "Not CA legal"
    form.set_title_fields(["title", "make", "barrel_length", "ca_legality", "c_and_r"])
    form.c_and_r.click()
    assert form.title.text() == (
        "Government Colt Barrel length: 5 inches NOT LEGAL FOR CA C&R"
    )
    assert form.collect().c_and_r is True
    form.c_and_r.click()
    assert (
        form.title.text() == "Government Colt Barrel length: 5 inches NOT LEGAL FOR CA"
    )
    form.set_title_fields(["title", "make", "barrel_length", "ca_legality"])
    saved = form.collect()
    # Reopening with another configuration must replace the old generated edges.
    other = LotForm()
    other.set_title_fields(["make", "title"])
    other.load(saved, 41000)
    assert other.title.text() == "Colt Government"
    other.close()
    form.close()


def test_disabling_condition_in_title_keeps_description(app):
    form = LotForm()
    form.load(
        Lot(1, title="Colt - Good", condition="Good", desc="Condition: Good."),
        41000,
    )
    form.set_title_fields(["title"])
    assert form.title.text() == "Colt"
    form.title.editingFinished.emit()
    assert form.title.text() == "Colt"
    assert "Condition: Good." in form.desc.toPlainText()
    form.close()


def test_custom_fields_build_titles_and_prefix_changes_replace_old_text():
    from simple_auction.services.title_layout import CustomField, prefixes

    caliber = CustomField("cal1", "Caliber", "Cal:")
    fields = ["make", "title", caliber.key]
    lot = Lot(1, make="Colt", custom={"cal1": ".45 ACP"})
    title = update_title("Government", Lot(1), fields, lot, fields, prefixes([caliber]))
    assert title == "Colt Government Cal: .45 ACP"
    renamed = CustomField("cal1", "Caliber", "Caliber")
    saved = replace(lot, title_fields=fields)
    assert (
        update_title(
            title,
            saved,
            fields,
            saved,
            fields,
            prefixes([renamed]),
            prefixes([caliber]),
        )
        == "Colt Government Caliber .45 ACP"
    )
    # An empty value adds nothing, and a field without prefix adds just the value.
    plain = CustomField("cal1", "Caliber")
    assert update_title("Government", Lot(1), fields, Lot(1), fields) == "Government"
    assert (
        update_title("Government", Lot(1), fields, lot, fields, prefixes([plain]))
        == "Colt Government .45 ACP"
    )


def test_custom_fields_persist_in_settings_details_and_shared_lots(tmp_path):
    from simple_auction.services.title_layout import CustomField

    caliber = CustomField("cal1", "Caliber", "Cal:")
    path = tmp_path / "config.json"
    Config(
        base_dir=tmp_path,
        custom_fields=[caliber],
        title_fields=["title", caliber.key],
    ).save(path)
    loaded = Config.load(path)
    assert loaded.custom_fields == [caliber]
    assert loaded.title_fields == ["title", caliber.key]
    # A layout naming a field that isn't defined is rejected, not guessed at.
    raw = json.loads(path.read_text())
    raw["custom_fields"] = []
    path.write_text(json.dumps(raw))
    with pytest.raises(ConfigFileError):
        Config.load(path)

    details = tmp_path / "1 details.json"
    lot_details.save(details, Lot(1, custom={"cal1": ".45 ACP"}))
    filled = [Lot(1)]
    lot_details.fill(details, filled)
    assert filled[0].custom == {"cal1": ".45 ACP"}

    shared = Lot(1, custom={"cal1": ".45 ACP"})
    assert network.validated_lot(network.lot_data(shared)) == shared
    legacy = network.lot_data(Lot(1))
    legacy.pop("custom")
    assert network.validated_lot(legacy) == Lot(1)
    with pytest.raises(ValueError):
        network.validated_lot({**network.lot_data(Lot(1)), "custom": {"x y": 1}})


def test_settings_add_rename_and_remove_custom_fields(app, tmp_path):
    dialog = SettingsDialog(Config(base_dir=tmp_path), [])
    try:
        editor = dialog.custom_editor
        editor.add_button.click()
        editor.inputs["label"].setText("Caliber")
        editor.inputs["prefix"].setText("Cal:")
        (field,) = dialog.custom_fields()
        assert (field.label, field.prefix) == ("Caliber", "Cal:")
        # A new field is listed in both columns: ticked for the description,
        # unticked (available) for the title.
        assert dialog.desc_fields()[-1] == field.key
        assert field.key not in dialog.title_fields()
        dialog.title_order.set_checked(field.key, True)
        assert dialog.title_fields()[-1] == field.key
        assert "Caliber" in dialog.title_order.item(field.key).text()
        assert "Cal: your Caliber" in dialog.preview_title.text()
        assert "Caliber: your Caliber" in dialog.preview_desc.text()
        editor.inputs["label"].setText("Calibre")
        assert "Calibre" in dialog.title_order.item(field.key).text()
        assert "Calibre" in dialog.desc_order.item(field.key).text()
        editor.remove_button.click()
        assert dialog.custom_fields() == []
        assert field.key not in dialog.title_fields()
        assert field.key not in dialog.desc_fields()
        assert dialog.title_order.item(field.key) is None
        assert dialog.desc_order.item(field.key) is None
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_lot_editor_shows_custom_fields_and_puts_them_in_the_title(app):
    from simple_auction.services.title_layout import CustomField

    caliber = CustomField("cal1", "Caliber", "Cal:")
    form = LotForm()
    assert form.custom_card.isHidden()
    form.set_custom_fields([caliber])
    form.set_title_fields(["make", "title", caliber.key])
    form.load(
        Lot(
            1,
            make="Colt",
            title="Colt Government Cal: .45 ACP",
            custom={"cal1": ".45 ACP", "gone": "kept"},
        ),
        1000,
    )
    assert not form.custom_card.isHidden()
    edit = form._custom_inputs["cal1"]
    assert edit.text() == ".45 ACP"
    form._apply_title_fields()
    assert form.title.text() == "Colt Government Cal: .45 ACP"
    edit.setText(".38 Special")
    form._apply_title_fields()
    assert form.title.text() == "Colt Government Cal: .38 Special"
    # Values of fields no longer defined stay with the lot.
    assert form.collect().custom == {"cal1": ".38 Special", "gone": "kept"}
    form.set_custom_fields([])
    form.set_title_fields(["make", "title"])
    assert form.custom_card.isHidden()
    assert form.title.text() == "Colt Government"
    assert form.collect().custom == {"cal1": ".38 Special", "gone": "kept"}
    form.mark_saved()
    form.deleteLater()


def test_description_fields_are_written_in_order_and_replaced_on_change(app):
    from simple_auction.services.title_layout import (
        CustomField,
        desc_lines,
        labels,
        update_desc,
    )

    caliber = CustomField("cal1", "Caliber")
    lot = Lot(1, make="Colt", serial="E1", custom={"cal1": ".357"})
    lines = desc_lines(lot, ["serial", caliber.key, "make", "year"], labels([caliber]))
    assert lines == ["Serial number: E1", "Caliber: .357", "Make: Colt"]
    desc = update_desc("Blued.", [], lines)
    assert desc == "Serial number: E1\nCaliber: .357\nMake: Colt\n\nBlued."
    # Rewriting replaces only the generated lines and keeps the user's text.
    again = update_desc(desc, ["Serial number", "Caliber", "Make"], ["Make: Colt"])
    assert again == "Make: Colt\n\nBlued."

    form = LotForm()
    form.set_custom_fields([caliber])
    form.set_title_fields(["title"])
    form.set_desc_fields(["make", caliber.key])
    form.load(Lot(1, desc="Blued finish."), 1000)
    form.make.setText("Colt")
    form._custom_inputs["cal1"].setText(".357 Magnum")
    form._apply_title_fields()
    assert form.desc.toPlainText() == (
        "Make: Colt\nCaliber: .357 Magnum\n\nBlued finish."
    )
    form.set_desc_fields([caliber.key])
    assert form.desc.toPlainText() == "Caliber: .357 Magnum\n\nBlued finish."
    form.mark_saved()
    form.deleteLater()


def test_description_layout_persists_and_rejects_title_and_condition(tmp_path):
    path = tmp_path / "config.json"
    Config(base_dir=tmp_path, desc_fields=["year", "make"]).save(path)
    assert Config.load(path).desc_fields == ["year", "make"]
    raw = json.loads(path.read_text())
    raw["desc_fields"] = ["condition"]
    path.write_text(json.dumps(raw))
    with pytest.raises(ConfigFileError):
        Config.load(path)


def test_the_previous_default_description_layout_is_upgraded(tmp_path):
    from simple_auction.services.title_layout import (
        DEFAULT_DESC_FIELDS,
        PREVIOUS_DEFAULT_DESC_FIELDS,
    )

    path = tmp_path / "config.json"
    raw = {"base_dir": str(tmp_path), "desc_fields": list(PREVIOUS_DEFAULT_DESC_FIELDS)}
    path.write_text(json.dumps(raw))
    assert Config.load(path).desc_fields == list(DEFAULT_DESC_FIELDS)
    assert "make" not in DEFAULT_DESC_FIELDS and "model" not in DEFAULT_DESC_FIELDS
    # A layout the user chose themselves is kept, even with make and model.
    raw["desc_fields"] = ["make", "model"]
    path.write_text(json.dumps(raw))
    assert Config.load(path).desc_fields == ["make", "model"]


def test_lot_editor_builds_the_house_style_title_from_its_fields(app):
    form = LotForm()
    form.load(Lot(1), 1000)
    for edit, value in (
        (form.make, "Arsenal"),
        (form.model, "SAM7SF"),
        (form.caliber, "7.62x39"),
        (form.serial, "BE 53 1936"),
    ):
        edit.setText(value)
    form.gun_type.setCurrentText("Rifle")
    form.barrel_length.setText("16 inches")
    form.ca_legality.setCurrentText("LEGAL FOR CA")
    form.condition.setCurrentText("Excellent")
    form._apply_title_fields()
    assert form.title.text() == (
        "Arsenal SAM7SF 7.62x39 Rifle SN: BE 53 1936 Excellent Condition LEGAL FOR CA"
    )
    lot = form.collect()
    assert (lot.caliber, lot.gun_type) == ("7.62x39", "Rifle")
    # Caliber, type and barrel length head the description; make and model
    # are only in the title.
    assert form.desc.toPlainText().startswith(
        "Caliber: 7.62x39\nType: Rifle\nBarrel length: 16 inches"
    )
    assert "Make:" not in form.desc.toPlainText()
    assert "Model:" not in form.desc.toPlainText()
    form.mark_saved()
    form.deleteLater()


def test_caliber_and_type_persist_in_details_and_shared_lots(tmp_path):
    path = tmp_path / "1 details.json"
    lot_details.save(path, Lot(1, caliber="12 GA", gun_type="Shotgun"))
    filled = [Lot(1)]
    lot_details.fill(path, filled)
    assert (filled[0].caliber, filled[0].gun_type) == ("12 GA", "Shotgun")
    shared = Lot(1, caliber="12 GA", gun_type="Shotgun")
    assert network.validated_lot(network.lot_data(shared)) == shared
    legacy = network.lot_data(Lot(1))
    for key in ("caliber", "gun_type"):
        legacy.pop(key)
    assert network.validated_lot(legacy) == Lot(1)
