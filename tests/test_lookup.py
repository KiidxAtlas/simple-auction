import json

from simple_auction.services.lookup import (
    LookupResult,
    SerialRule,
    ensure_table,
    load_rules,
    lookup_serial,
)

RULES = [
    SerialRule("Winchester", 2600000, 2700000, 1955, model="Model 94"),
    SerialRule("Remington", 100, 999, 1972, model="870", prefix="AB"),
    SerialRule("Marlin", 2650000, 2660000, 1956),
]


def test_numeric_match():
    assert lookup_serial("2612345", RULES) == [
        LookupResult(1955, "Winchester", "Model 94")
    ]


def test_prefix_ignores_case_spaces_and_dashes():
    assert lookup_serial("ab-1 23", RULES) == [LookupResult(1972, "Remington", "870")]


def test_overlapping_ranges_return_all():
    assert len(lookup_serial("2655000", RULES)) == 2


def test_no_match():
    assert lookup_serial("ZZ123", RULES) == []
    assert lookup_serial("", RULES) == []


def test_template_creates_and_loads_empty(tmp_path):
    path = tmp_path / "serial_years.json"
    ensure_table(path)
    assert load_rules(path) == []
    data = json.loads(path.read_text())
    data["rules"].append(data["_example"])
    path.write_text(json.dumps(data))
    assert lookup_serial("AB1500", load_rules(path))[0].year == 1960
