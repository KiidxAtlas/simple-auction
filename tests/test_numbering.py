import pytest

from simple_auction.models import Lot
from simple_auction.services.numbering import next_auction, next_lot


def test_next_auction_empty():
    assert next_auction([]) == 40000


def test_next_auction_adds_step():
    assert next_auction([40000, 41000]) == 42000


def test_start_at_jumps_ahead():
    assert next_auction([40000], start_at=52000) == 52000


def test_start_at_used_when_no_auctions_yet():
    assert next_auction([], start_at=12000) == 12000


def test_start_at_ignored_once_files_pass_it():
    assert next_auction([52000], start_at=52000) == 53000


def test_next_lot_first_is_auction_number():
    assert next_lot([], 41000) == 41000


def test_next_lot_increments():
    lots = [Lot(41000), Lot(41001)]
    assert next_lot(lots, 41000) == 41002


def test_next_lot_full_auction():
    with pytest.raises(ValueError):
        next_lot([Lot(41999)], 41000)
