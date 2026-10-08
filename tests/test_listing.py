from simple_auction.models import Condition, Lot
from simple_auction.services.listing import (
    apply_condition,
    condition_desc,
    condition_title,
)


def test_title_suffix_added_and_replaced():
    t = condition_title("Remington 870", Condition.EXCELLENT)
    assert t == "Remington 870 - Excellent"
    assert condition_title(t, Condition.LIKE_NEW) == "Remington 870 - Like New"


def test_empty_title_stays_empty():
    assert condition_title("", Condition.GOOD) == ""


def test_desc_sentence_replaced_not_duplicated():
    d = condition_desc("12 gauge pump.", Condition.EXCELLENT)
    d = condition_desc(d, Condition.FAIR)
    assert d.startswith("12 gauge pump.\n\nCondition: Fair.")
    assert d.count("Condition:") == 1


def test_desc_keeps_user_text_after_condition_line():
    d = condition_desc("Line one.", Condition.GOOD) + "\n\nIncludes case."
    d = condition_desc(d, Condition.EXCELLENT)
    assert "Includes case." in d and d.count("Condition:") == 1
    assert d.endswith("Condition: Excellent. Light handling marks, bore bright.")


def test_apply_condition_is_idempotent():
    lot = Lot(41000, title="Colt 1911", desc="Blued.", condition=Condition.GOOD)
    once = apply_condition(lot)
    assert apply_condition(once) == once


def test_title_capped_at_100_including_suffix():
    long = "Winchester Model 1894 " + "x" * 120
    t = condition_title(long, Condition.EXCELLENT)
    assert len(t) <= 100 and t.endswith(" - Excellent")
    # Switching condition keeps it within the limit and doesn't stack suffixes.
    t2 = condition_title(t, Condition.LIKE_NEW)
    assert len(t2) <= 100 and t2.endswith(" - Like New") and "Excellent" not in t2


def test_untrimmed_length():
    from simple_auction.services.listing import untrimmed_title_length

    assert untrimmed_title_length("Colt", Condition.GOOD) == len("Colt - Good")
    assert untrimmed_title_length("", Condition.GOOD) == 0
