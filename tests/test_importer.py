from openpyxl import Workbook

from simple_auction.models import Lot
from simple_auction.services import excel, lot_details
from simple_auction.services.conditions import DEFAULT_CONDITIONS
from simple_auction.services.importer import (
    build_lots,
    guess_auction_number,
    guess_mapping,
    lot_numbers,
    lots_in_range,
    parse_condition,
    read_sheet,
)


def _xlsx(path, rows):
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    wb.save(path)
    return path


OLD_LAYOUT = [
    ["Spring Gun Auction 2025"],  # a title row above the headers
    [],
    ["Lot #", "Item Description", "Serial No.", "Consignor Name", "Cond.", "Year Made"],
    [38001, "Winchester 94 30-30", "1234567", "J. Miller", "Very good", "c. 1965"],
    [38002, "Colt 1911", "C12345", "A. Smith", "Fair, worn bluing", 1918],
    [None, None, None, None, None, None],  # blank row
    ["38003", "Ruger 10/22", "", "", "NIB", ""],
]


def test_finds_header_row_below_a_title(tmp_path):
    sheet = read_sheet(_xlsx(tmp_path / "old.xlsx", OLD_LAYOUT))
    assert sheet.headers[0] == "Lot #"
    assert len(sheet.rows) == 3  # blank row dropped


def test_guess_mapping_by_header_names():
    mapping = guess_mapping(
        [
            "Lot #",
            "Lot Title",
            "Item Description",
            "Serial No.",
            "Consignor Name",
            "Cond.",
            "Year Made",
            "Book No",
            "Make",
            "Model #",
            "Notes",
        ]
    )
    assert mapping["lot_number"] == 0
    assert mapping["title"] == 1
    assert mapping["desc"] == 2  # "Notes" doesn't steal it: first match wins
    assert mapping["serial"] == 3
    assert mapping["owner"] == 4
    assert mapping["condition"] == 5
    assert mapping["year"] == 6
    assert mapping["book_no"] == 7
    assert mapping["make"] == 8
    assert mapping["model"] == 9


def test_unknown_headers_stay_unmapped():
    mapping = guess_mapping(["Hammer price", "Buyer #", "Paid"])
    assert all(col is None for col in mapping.values())


def test_build_lots_from_old_layout(tmp_path):
    sheet = read_sheet(_xlsx(tmp_path / "old.xlsx", OLD_LAYOUT))
    mapping = guess_mapping(sheet.headers)
    numbers = lot_numbers(sheet, mapping["lot_number"])
    auction = guess_auction_number(tmp_path / "old.xlsx", numbers)
    assert auction == 38000 and lots_in_range(numbers, auction)

    names = [o.name for o in DEFAULT_CONDITIONS]
    lots = build_lots(sheet, mapping, auction, renumber=False, conditions=names)
    assert [x.lot_number for x in lots] == [38001, 38002, 38003]
    first = lots[0]
    assert first.desc == "Winchester 94 30-30"
    assert first.serial == "1234567" and first.owner == "J. Miller"
    assert first.condition == "Excellent" and first.year == 1965
    assert lots[1].condition == "Fair" and lots[1].year == 1918
    assert lots[2].condition == "Like New" and lots[2].year is None


def test_renumber_when_lot_numbers_dont_fit_the_auction():
    from simple_auction.services.importer import Sheet

    sheet = Sheet(headers=["Lot", "Title"], rows=[[1, "A"], [2, "B"], [5, "C"]])
    mapping = guess_mapping(sheet.headers)
    assert not lots_in_range(lot_numbers(sheet, 0), 52000)
    lots = build_lots(sheet, mapping, 52000, renumber=True)
    assert [(x.lot_number, x.title) for x in lots] == [
        (52000, "A"),
        (52001, "B"),
        (52002, "C"),
    ]


def test_no_lot_column_numbers_in_row_order():
    from simple_auction.services.importer import Sheet

    sheet = Sheet(headers=["Title"], rows=[["A"], ["B"]])
    lots = build_lots(sheet, guess_mapping(sheet.headers), 41000, renumber=False)
    assert [x.lot_number for x in lots] == [41000, 41001]


def test_duplicate_and_out_of_range_lots_skipped():
    from simple_auction.services.importer import Sheet

    sheet = Sheet(headers=["Lot"], rows=[[41001], [41001], [99999]])
    lots = build_lots(sheet, guess_mapping(sheet.headers), 41000, renumber=False)
    assert [x.lot_number for x in lots] == [41001]


def test_auction_number_from_file_name(tmp_path):
    assert guess_auction_number(tmp_path / "Auction 47000 final.xlsx", []) == 47000
    assert guess_auction_number(tmp_path / "spring sale.xlsx", []) is None


def test_csv(tmp_path):
    path = tmp_path / "old.csv"
    path.write_text("Lot,Title,Serial\n41000,Colt 1911,C1\n", encoding="utf-8")
    sheet = read_sheet(path)
    lots = build_lots(sheet, guess_mapping(sheet.headers), 41000, renumber=False)
    assert lots[0].title == "Colt 1911" and lots[0].serial == "C1"


def test_parse_condition_matches_configured_names():
    names = ["Mint", "Very Good+", "Good", "Poor"]
    assert parse_condition("very good+", names) == "Very Good+"  # exact
    assert parse_condition("Good+, light wear", names) == "Good"  # name in text
    assert parse_condition("Worn", names) == "Worn"  # "Fair" not configured
    assert parse_condition("as pictured", names) == "as pictured"  # kept as is
    assert parse_condition("", names) == "Mint"  # blank -> default


def test_parse_condition_uses_wording_for_default_names():
    names = [o.name for o in DEFAULT_CONDITIONS]
    assert parse_condition("NIB", names) == "Like New"
    assert parse_condition("worn bluing", names) == "Fair"


def test_add_lots_only_adds_missing(tmp_path):
    path = excel.auction_path(tmp_path, 41000)
    excel.save_lot(path, Lot(41000, title="Keep me"))
    added = excel.add_lots(
        path, [Lot(41000, title="Imported"), Lot(41001, title="New")]
    )
    assert [x.lot_number for x in added] == [41001]
    titles = {x.lot_number: x.title for x in excel.load_auction(path)}
    assert titles == {41000: "Keep me", 41001: "New"}


def test_details_save_many(tmp_path):
    path = lot_details.details_path(tmp_path, 41000)
    lot_details.save_many(path, [Lot(41000, make="Colt"), Lot(41001)])
    lots = [Lot(41000), Lot(41001)]
    lot_details.fill(path, lots)
    assert lots[0].make == "Colt" and lots[1].make == ""


def test_title_taken_from_description_when_sheet_has_none():
    from simple_auction.services.importer import Sheet

    long = "Winchester Model 94 " + "carbine with saddle ring and original sights " * 4
    sheet = Sheet(
        headers=["Lot", "Description"],
        rows=[[41000, "Colt 1911. Blued, good bore."], [41001, long]],
    )
    lots = build_lots(sheet, guess_mapping(sheet.headers), 41000, renumber=False)
    assert lots[0].title == "Colt 1911."
    assert lots[0].desc == "Colt 1911. Blued, good bore."  # description untouched
    assert len(lots[1].title) <= 85 and not lots[1].title.endswith(" ")
    assert long.startswith(lots[1].title)
