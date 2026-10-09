import json

import pytest

from simple_auction.services.conditions import (
    DEFAULT_CONDITIONS,
    LEGACY_DEFAULT_CONDITIONS,
    ConditionOption,
    ConditionsFileError,
    load_file,
    save_file,
)
from simple_auction.services.config import Config


def test_simple_name_text_lines(tmp_path):
    path = tmp_path / "conditions.yaml"
    path.write_text(
        "# my notes\n"
        "Mint: Never fired.\n"
        "Very Good+: Light wear.   # inline comment\n"
        "As Is:\n"
    )
    assert load_file(path) == [
        ConditionOption("Mint", "Never fired."),
        ConditionOption("Very Good+", "Light wear."),
        ConditionOption("As Is", ""),
    ]


def test_list_form_also_accepted(tmp_path):
    path = tmp_path / "conditions.yaml"
    path.write_text("- name: Good\n  text: Fine.\n- Fair\n")
    assert load_file(path) == [
        ConditionOption("Good", "Fine."),
        ConditionOption("Fair"),
    ]


def test_save_then_load_round_trip_with_awkward_names(tmp_path):
    path = tmp_path / "conditions.yaml"
    options = [
        *DEFAULT_CONDITIONS,
        ConditionOption("As Is", ""),
        ConditionOption("Good: see notes", "Wear: light."),
        ConditionOption("NIB #1", "Box 100% — unopened"),
    ]
    save_file(path, options)
    text = path.read_text()
    assert text.startswith("# Lot conditions")
    first = DEFAULT_CONDITIONS[0]
    assert f"{first.name}: " in text.split("\n\n", 1)[1]  # one line per condition
    assert "As Is:\n" in text and "null" not in text
    assert load_file(path) == options


def test_mistake_reported_with_line_number(tmp_path):
    path = tmp_path / "conditions.yaml"
    path.write_text("Good: fine\nFair: worn: badly\n")
    with pytest.raises(ConditionsFileError, match="line 2"):
        load_file(path)


def test_wrong_shape_reported(tmp_path):
    path = tmp_path / "conditions.yaml"
    path.write_text("just some text\n")
    with pytest.raises(ConditionsFileError, match="Name: text"):
        load_file(path)


def test_empty_file_means_no_conditions(tmp_path):
    path = tmp_path / "conditions.yaml"
    path.write_text("# nothing yet\n")
    assert load_file(path) == []


def test_first_run_creates_file_with_defaults(tmp_path):
    config = Config(base_dir=tmp_path)
    assert config.load_conditions() is None
    assert load_file(config.conditions_path) == DEFAULT_CONDITIONS


def test_no_settings_file_uses_default_folder_under_home(_isolated_home):
    config = Config.load(_isolated_home / "missing-config.json")
    assert config.base_dir == _isolated_home / "Documents" / "simple-auction"
    assert config.conditions_path.exists()


def test_conditions_from_old_config_json_move_to_yaml(tmp_path):
    settings = tmp_path / "config.json"
    settings.write_text(
        json.dumps(
            {
                "base_dir": str(tmp_path),
                "conditions": [{"name": "Mint", "note": "Never fired."}],
            }
        )
    )
    config = Config.load(settings)
    assert config.conditions == [ConditionOption("Mint", "Never fired.")]
    assert load_file(tmp_path / "data" / "conditions.yaml") == config.conditions
    config.save(settings)
    assert "conditions" not in json.loads(settings.read_text())


def test_stock_legacy_settings_create_nine_condition_yaml(tmp_path):
    settings = tmp_path / "config.json"
    settings.write_text(
        json.dumps(
            {
                "base_dir": str(tmp_path),
                "conditions": [
                    {"name": option.name, "note": option.note}
                    for option in LEGACY_DEFAULT_CONDITIONS
                ],
            }
        )
    )
    config = Config.load(settings)
    assert config.conditions == DEFAULT_CONDITIONS
    assert [option.name for option in load_file(config.conditions_path)] == [
        "Factory New",
        "New",
        "Perfect",
        "Excellent",
        "Fine",
        "Very Good",
        "Good",
        "Fair",
        "Poor",
    ]


def test_existing_stock_yaml_is_upgraded_once(tmp_path):
    config = Config(base_dir=tmp_path)
    save_file(config.conditions_path, LEGACY_DEFAULT_CONDITIONS)
    assert config.load_conditions() is None
    assert config.conditions == DEFAULT_CONDITIONS
    assert load_file(config.conditions_path) == DEFAULT_CONDITIONS
    original = config.conditions_path.read_bytes()
    assert config.load_conditions() is None
    assert config.conditions_path.read_bytes() == original


@pytest.mark.parametrize("source", ["legacy", "yaml"])
@pytest.mark.parametrize(
    "options",
    [
        [],
        [ConditionOption("Mint", "Never fired.")],
        [
            ConditionOption("Like New", "My custom note."),
            *LEGACY_DEFAULT_CONDITIONS[1:],
        ],
        list(reversed(LEGACY_DEFAULT_CONDITIONS)),
    ],
)
def test_custom_conditions_are_not_replaced_by_defaults(tmp_path, source, options):
    config = Config(base_dir=tmp_path)
    legacy = None
    original = None
    if source == "yaml":
        save_file(config.conditions_path, options)
        original = config.conditions_path.read_bytes()
    else:
        legacy = [{"name": option.name, "note": option.note} for option in options]
    assert config.load_conditions(legacy) is None
    assert config.conditions == options
    assert load_file(config.conditions_path) == options
    if original is not None:
        assert config.conditions_path.read_bytes() == original


def test_broken_file_is_reported_and_never_overwritten(tmp_path):
    settings = tmp_path / "config.json"
    settings.write_text(json.dumps({"base_dir": str(tmp_path)}))
    path = tmp_path / "data" / "conditions.yaml"
    path.parent.mkdir()
    path.write_text("Good: fine\nFair: worn: badly\n")

    config = Config.load(settings)
    assert config.conditions_error and "line 2" in config.conditions_error
    assert config.conditions == DEFAULT_CONDITIONS  # still usable
    assert path.read_text() == "Good: fine\nFair: worn: badly\n"  # untouched


@pytest.mark.parametrize(
    "note",
    ["80% original finish", "80-90% finish", "% finish remaining", "% finish: unknown"],
)
def test_percentage_notes_load_and_round_trip(tmp_path, note):
    path = tmp_path / "conditions.yaml"
    path.write_text(f"Good: {note}\nFair: Some wear.\n")
    options = [ConditionOption("Good", note), ConditionOption("Fair", "Some wear.")]
    assert load_file(path) == options
    save_file(path, options)
    assert load_file(path) == options


def test_percent_notes_do_not_hide_other_yaml_errors(tmp_path):
    path = tmp_path / "conditions.yaml"
    path.write_text('Good: % remaining\nFair: "unfinished\n')
    original = path.read_bytes()
    with pytest.raises(ConditionsFileError, match="line"):
        load_file(path)
    assert path.read_bytes() == original


def test_yaml_list_accepts_percent_note(tmp_path):
    path = tmp_path / "conditions.yaml"
    path.write_text("- name: Good\n  text: % original finish\n")
    assert load_file(path) == [ConditionOption("Good", "% original finish")]
