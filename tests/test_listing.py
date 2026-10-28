import pytest

from simple_auction.models import Lot
from simple_auction.services.conditions import (
    DEFAULT_CONDITIONS,
    PREVIOUS_DEFAULT_CONDITIONS,
    ConditionOption,
    cleaned,
    from_json,
    to_json,
)
from simple_auction.services.listing import (
    apply_condition,
    condition_desc,
    condition_title,
    untrimmed_title_length,
)

KNOWN = [o.name for o in DEFAULT_CONDITIONS]
NOTE = {o.name: o.note for o in PREVIOUS_DEFAULT_CONDITIONS}


def test_title_suffix_added_and_replaced():
    t = condition_title("Remington 870", "Excellent", KNOWN)
    assert t == "Remington 870 - Excellent"
    assert condition_title(t, "Like New", KNOWN) == "Remington 870 - Like New"


def test_empty_title_stays_empty():
    assert condition_title("", "Good", KNOWN) == ""


def test_no_condition_means_no_suffix_or_sentence():
    assert condition_title("Colt - Good", "", KNOWN) == "Colt"
    desc = f"Blued.\n\nCondition: Good. {NOTE['Good']}"
    assert condition_desc(desc, "", "", KNOWN) == "Blued."


def test_desc_sentence_replaced_not_duplicated():
    d = condition_desc("12 gauge pump.", "Excellent", NOTE["Excellent"], KNOWN)
    d = condition_desc(d, "Fair", NOTE["Fair"], KNOWN)
    assert d.startswith("12 gauge pump.\n\nCondition: Fair.")
    assert d.count("Condition:") == 1


def test_desc_keeps_user_text_after_condition_line():
    d = condition_desc("Line one.", "Good", NOTE["Good"], KNOWN) + "\n\nIncludes case."
    d = condition_desc(d, "Excellent", NOTE["Excellent"], KNOWN)
    assert (
        d == f"Line one.\n\nCondition: Excellent. {NOTE['Excellent']}\n\nIncludes case."
    )


def test_condition_without_text_leaves_description_unchanged():
    desc = "  Blued.\n\nCondition: Good. Existing wording.\n"
    assert condition_desc(desc, "As Is", "", ["As Is", "Good"]) == desc
    assert condition_desc(desc, "As Is", "   ", ["As Is", "Good"]) == desc


def test_apply_condition_is_idempotent():
    lot = Lot(41000, title="Colt 1911", desc="Blued.", condition="Good")
    once = apply_condition(lot, DEFAULT_CONDITIONS)
    assert apply_condition(once, DEFAULT_CONDITIONS) == once


def test_custom_condition_and_new_wording():
    options = [ConditionOption("Very Good+", "Sharp, crisp markings.")]
    lot = Lot(1, title="Luger P08", desc="Matching numbers.", condition="Very Good+")
    out = apply_condition(lot, options)
    assert out.title == "Luger P08 - Very Good+"
    assert out.desc.endswith("Condition: Very Good+. Sharp, crisp markings.")
    reworded = [ConditionOption("Very Good+", "Crisp markings, 95% finish.")]
    again = apply_condition(out, reworded)
    assert "Condition: Very Good+. Crisp markings, 95% finish." in again.desc
    # Without the previous template, unfamiliar wording is preserved, not erased.
    assert "Sharp, crisp markings." in again.desc
    assert again.desc.count("Condition:") == 1


def test_removed_condition_keeps_its_text():
    lot = apply_condition(
        Lot(1, title="Colt", desc="Blued.", condition="Excellent"), DEFAULT_CONDITIONS
    )
    without_excellent = [o for o in DEFAULT_CONDITIONS if o.name != "Excellent"]
    out = apply_condition(lot, without_excellent)
    assert out.title == "Colt - Excellent"
    assert out.desc == lot.desc  # description left as it was


def test_title_capped_at_100_including_suffix():
    long = "Winchester Model 1894 " + "x" * 120
    t = condition_title(long, "Excellent", KNOWN)
    assert len(t) <= 100 and t.endswith(" - Excellent")
    # Switching condition keeps it within the limit and doesn't stack suffixes.
    t2 = condition_title(t, "Like New", KNOWN)
    assert len(t2) <= 100 and t2.endswith(" - Like New") and "Excellent" not in t2


def test_untrimmed_length():
    assert untrimmed_title_length("Colt", "Good", KNOWN) == len("Colt - Good")
    assert untrimmed_title_length("", "Good", KNOWN) == 0


def test_conditions_cleaned_and_saved():
    rows = [
        ConditionOption("  Good ", " Fine. "),
        ConditionOption("", "no name"),
        ConditionOption("good", "duplicate"),
    ]
    assert cleaned(rows) == [ConditionOption("Good", "Fine.")]
    assert from_json(to_json(DEFAULT_CONDITIONS)) == DEFAULT_CONDITIONS
    assert from_json(None) == DEFAULT_CONDITIONS
    assert from_json([]) == []


def test_no_condition_leaves_lot_alone():
    """An imported lot with no condition picked keeps its old text as is."""
    lot = Lot(
        1,
        title="Colt 1911 - Good",
        desc="Blued.\n\nCondition: Good. From the old catalogue.",
        condition="",
    )
    assert apply_condition(lot, DEFAULT_CONDITIONS) == lot


@pytest.mark.parametrize(
    "suffix",
    [
        " Includes case and two magazines.",
        "\nIncludes case.",
        "\n\nIncludes case.\nExtra provenance.",
    ],
)
def test_condition_update_preserves_appended_text_in_place(suffix):
    old = f"Condition: Good. {NOTE['Good']}"
    new = f"Condition: Excellent. {NOTE['Excellent']}"
    desc = f"Listing details.\n\n{old}{suffix}"
    updated = condition_desc(desc, "Excellent", NOTE["Excellent"], KNOWN)
    assert updated == f"Listing details.\n\n{new}{suffix}"
    assert condition_desc(updated, "Excellent", NOTE["Excellent"], KNOWN) == updated


def test_condition_clear_preserves_unrecognised_custom_text():
    assert (
        condition_desc(
            "Listing.\n\nCondition: Good. Handwritten inspection notes.", "", "", KNOWN
        )
        == "Listing.\n\nHandwritten inspection notes."
    )


def test_custom_note_rewording_removes_only_known_previous_note():
    desc = "Listing.\n\nCondition: Very Good+. Original note. Includes case.\nKeep this paragraph."
    assert (
        condition_desc(
            desc,
            "Very Good+",
            "Revised note.",
            ["Very Good+"],
            known_notes=["Original note."],
        )
        == "Listing.\n\nCondition: Very Good+. Revised note. Includes case.\nKeep this paragraph."
    )


@pytest.mark.parametrize("option", DEFAULT_CONDITIONS)
def test_all_default_conditions_add_no_description_text(option):
    assert option.note == ""
    for description in ("", "  Existing text.\n\nCondition: Good. Old wording.\n"):
        lot = Lot(1, title="Rifle", desc=description, condition=option.name)
        out = apply_condition(lot, DEFAULT_CONDITIONS)
        assert out.condition == option.name
        assert out.desc == description
        assert out.title == f"Rifle - {option.name}"
