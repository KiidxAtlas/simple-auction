import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font

from simple_auction.models import Lot
from simple_auction.services import excel


def test_save_load_roundtrip_and_update(tmp_path):
    path = excel.auction_path(tmp_path, 41000)
    excel.save_lot(path, Lot(41000, serial="A1", condition="Good", year=1990))
    excel.save_lot(path, Lot(41001, title="Rifle", owner="Bob", book_no="7"))
    excel.save_lot(path, Lot(41000, serial="A2", condition="Fair"))

    lots = excel.load_auction(path)
    assert [x.lot_number for x in lots] == [41000, 41001]
    assert lots[0].serial == "A2"
    assert lots[0].condition == "Fair"
    assert lots[1].owner == "Bob" and lots[1].book_no == "7"


def test_delete_lots(tmp_path):
    path = excel.auction_path(tmp_path, 41000)
    for n in (41000, 41001, 41002, 41003):
        excel.save_lot(path, Lot(n))
    excel.delete_lots(path, {41001, 41002})
    assert [x.lot_number for x in excel.load_auction(path)] == [41000, 41003]


def test_list_auctions_ignores_junk(tmp_path):
    for name in ["41000.xlsx", "40000.xlsx", "notes.xlsx", "~$41000.xlsx"]:
        (tmp_path / name).touch()
    assert excel.list_auctions(tmp_path) == [40000, 41000]


EXPECTED_HEADERS = [
    "Lot Number",
    "Title",
    "Description",
    "Owner",
    "Book Number",
    "Serial",
    "Condition",
    "Year",
]
LEGACY_HEADERS = [
    "Lot",
    "Serial",
    "Condition",
    "Title",
    "Desc",
    "Owner",
    "Book #",
    "Year",
]


def test_new_workbook_column_order_matches_values(tmp_path):
    path = tmp_path / "41000.xlsx"
    excel.create_auction(path)
    lot = Lot(
        41001,
        title="Rifle",
        desc="Description text",
        owner="Owner name",
        book_no="007",
        serial="ABC",
        condition="Good",
        year=1990,
    )
    excel.save_lot(path, lot)
    with path.open("rb") as source:
        wb = load_workbook(source)
        try:
            assert list(wb.active.values) == [
                tuple(EXPECTED_HEADERS),
                (
                    41001,
                    "Rifle",
                    "Description text",
                    "Owner name",
                    "007",
                    "ABC",
                    "Good",
                    1990,
                ),
            ]
        finally:
            wb.close()
    assert excel.load_auction(path) == [lot]


@pytest.mark.parametrize("include_year", [False, True])
def test_legacy_load_export_and_save_preserve_fields_and_formatting(
    tmp_path, include_year
):
    path, exported = tmp_path / "41000.xlsx", tmp_path / "export.xlsx"
    wb = Workbook()
    ws = wb.active
    headers = LEGACY_HEADERS if include_year else LEGACY_HEADERS[:-1]
    values = [41001, "ABC", "Good", "Rifle", "Description text", "Owner name", 7]
    if include_year:
        values.append(1990)
    ws.append([*headers, "Staff note"])
    ws.append([*values, "Retain this extra column"])
    ws["D2"].font = Font(bold=True)
    ws["D2"].comment = Comment("Title comment", "Staff")
    ws.column_dimensions["D"].width = 35
    wb.create_sheet("Notes")["A1"] = "Retain this sheet"
    wb.save(path)
    wb.close()
    original = path.read_bytes()
    lot = Lot(
        41001,
        serial="ABC",
        condition="Good",
        title="Rifle",
        desc="Description text",
        owner="Owner name",
        book_no="7",
        year=1990 if include_year else None,
    )
    assert excel.load_auction(path) == [lot]
    excel.export_auction(path, exported)
    assert path.read_bytes() == original
    assert excel.load_auction(exported) == [lot]
    excel.save_lot(path, lot)
    for target in (path, exported):
        wb = load_workbook(target)
        try:
            ws = wb.active
            assert list(next(ws.values)) == [*EXPECTED_HEADERS, "Staff note"]
            assert ws["I2"].value == "Retain this extra column"
            assert ws["B2"].font.bold
            assert ws["B2"].comment.text == "Title comment"
            assert ws.column_dimensions["B"].width == 35
            assert wb["Notes"]["A1"].value == "Retain this sheet"
        finally:
            wb.close()
    excel.add_lots(path, [Lot(41002, title="Next lot")])
    excel.delete_lots(path, {41001})
    assert excel.load_auction(path) == [Lot(41002, title="Next lot")]


def test_export_missing_source_does_not_create_workbook(tmp_path):
    destination = tmp_path / "export.xlsx"
    with pytest.raises(FileNotFoundError):
        excel.export_auction(tmp_path / "missing.xlsx", destination)
    assert not destination.exists()
