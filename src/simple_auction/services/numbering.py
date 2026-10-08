from simple_auction.constants import AUCTION_STEP, FIRST_AUCTION
from simple_auction.models import Lot


def next_auction(
    existing: list[int], step: int = AUCTION_STEP, start_at: int | None = None
) -> int:
    """Next auction number: highest existing + step.

    `start_at` is a number set in Settings to jump ahead to the real series
    (e.g. 52000). It's used when it's higher than what the files suggest.
    """
    base = max(existing) + step if existing else FIRST_AUCTION
    if start_at is not None and (start_at > base or not existing):
        return start_at
    return base


def next_lot(lots: list[Lot], auction_no: int, step: int = AUCTION_STEP) -> int:
    """Next lot in an auction: last lot + 1, starting at the auction number."""
    if not lots:
        return auction_no
    n = max(lot.lot_number for lot in lots) + 1
    if n >= auction_no + step:
        raise ValueError(f"Auction {auction_no} is full")
    return n
