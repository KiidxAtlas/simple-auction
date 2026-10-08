from simple_auction.models import Condition, Lot
from simple_auction.services import excel


def test_save_load_roundtrip_and_update(tmp_path):
    path = excel.auction_path(tmp_path, 41000)
    excel.save_lot(path, Lot(41000, serial="A1", condition=Condition.GOOD, year=1990))
    excel.save_lot(path, Lot(41001, title="Rifle", owner="Bob", book_no="7"))
    excel.save_lot(path, Lot(41000, serial="A2", condition=Condition.FAIR))

    lots = excel.load_auction(path)
    assert [x.lot_number for x in lots] == [41000, 41001]
    assert lots[0].serial == "A2"
    assert lots[0].condition is Condition.FAIR
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
