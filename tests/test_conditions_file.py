import json

import pytest

from simple_auction.services.conditions import (
    DEFAULT_CONDITIONS,
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
