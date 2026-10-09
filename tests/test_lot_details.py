from simple_auction.models import Lot
from simple_auction.services import lot_details
from simple_auction.services.listing import (
    make_model_desc,
    prefixed_title,
    title_prefix,
)


def test_save_fill_delete_roundtrip(tmp_path):
    path = lot_details.details_path(tmp_path, 41000)
    lot_details.save(path, Lot(41000, make="Remington", model="870"))
    lot_details.save(path, Lot(41001, make="Colt"))
    lots = [Lot(41000), Lot(41001), Lot(41002)]
    lot_details.fill(path, lots)
    assert [(x.make, x.model) for x in lots] == [
        ("Remington", "870"),
        ("Colt", ""),
        ("", ""),
    ]
    lot_details.delete(path, {41000})
    lots = [Lot(41000)]
    lot_details.fill(path, lots)
    assert lots[0].make == ""


def test_no_file_written_for_lots_without_details(tmp_path):
    path = lot_details.details_path(tmp_path, 41000)
    lot_details.save(path, Lot(41000))
    assert not path.exists()


def test_title_starts_with_make_model_serial_and_stays_in_sync():
    t = prefixed_title("12ga Pump - Good", "", "Remington", "870", "")
    assert t == "Remington 870 12ga Pump - Good"
    # Serial added: goes after the model, typed words and condition kept.
    old = title_prefix("Remington", "870", "")
    t = prefixed_title(t, old, "Remington", "870", "A123456M")
    assert t == "Remington 870 S/N: A123456M 12ga Pump - Good"
    # Model edited: the old start is replaced, not stacked.
    old = title_prefix("Remington", "870", "A123456M")
    t = prefixed_title(t, old, "Remington", "870 Wingmaster", "A123456M")
    assert t == "Remington 870 Wingmaster S/N: A123456M 12ga Pump - Good"
    # Serial cleared.
    old = title_prefix("Remington", "870 Wingmaster", "A123456M")
    assert prefixed_title(t, old, "Remington", "870 Wingmaster", "") == (
        "Remington 870 Wingmaster 12ga Pump - Good"
    )


def test_title_prefix_order_and_label():
    assert title_prefix("Colt", "1911", "C123") == "Colt 1911 S/N: C123"
    assert title_prefix("", "", "C123") == "S/N: C123"
    assert title_prefix("Colt", "", "") == "Colt"
    assert title_prefix("", "", "") == ""


def test_title_already_starting_with_the_fields_is_not_doubled():
    assert prefixed_title("Colt 1911 Government", "", "Colt", "1911", "") == (
        "Colt 1911 Government"
    )


def test_desc_lines_at_top_replaced_in_place():
    d = make_model_desc("Blued finish.\n\nCondition: Good. x", "Colt", "1911")
    assert d == "Make: Colt\nModel: 1911\n\nBlued finish.\n\nCondition: Good. x"
    d = make_model_desc(d, "Colt", "1911A1")
    assert d.count("Model:") == 1 and d.startswith("Make: Colt\nModel: 1911A1\n\n")
    assert make_model_desc(d, "", "") == "Blued finish.\n\nCondition: Good. x"
