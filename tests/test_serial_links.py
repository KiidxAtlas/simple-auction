import json

from simple_auction.services.config import Config
from simple_auction.services.serial_links import (
    DEFAULT_LINKS,
    OFFICIAL_LINKS,
    SerialLink,
    build_url,
    from_json,
)

LINDCOTT = DEFAULT_LINKS[0].url


def test_default_link_with_maker():
    assert build_url(LINDCOTT, "A 123", "S&W Model 29") == (
        "https://lindcottarmory.com/serial-lookup?make=Smith%20%26%20Wesson&serial=A%20123"
    )


def test_empty_params_dropped():
    assert build_url(LINDCOTT, "12345", "Unknown maker rifle") == (
        "https://lindcottarmory.com/serial-lookup?serial=12345"
    )
    assert build_url(LINDCOTT, "") == "https://lindcottarmory.com/serial-lookup"


def test_placeholder_in_path_and_title():
    url = build_url("https://example.com/s/{serial}?q={title}", "AB/1", "Colt 1911")
    assert url == "https://example.com/s/AB%2F1?q=Colt%201911"


def test_ruger_prefill_preserves_serial_and_drops_blank_query():
    template = next(link.url for link in DEFAULT_LINKS if link.name == "Ruger official")
    assert build_url(template, " 001-AB /23&x ") == (
        "https://ruger.com/dataProcess/serialHistory/?serial=001-AB%20%2F23%26x"
    )
    assert build_url(template, " ") == "https://ruger.com/dataProcess/serialHistory/"


def test_from_json_skips_invalid_and_defaults_when_missing():
    links = from_json(
        [
            {"name": "Good", "url": "https://x.com/{serial}"},
            {"name": "", "url": "https://y.com"},
            {"name": "No scheme", "url": "y.com/{serial}"},
            "junk",
        ]
    )
    assert links == [SerialLink("Good", "https://x.com/{serial}")]
    assert from_json(None) == DEFAULT_LINKS
    assert from_json([]) == []  # the user removed them all


def test_config_roundtrip_keeps_links(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(base_dir=tmp_path, photos_dir=tmp_path)
    cfg.serial_links = [SerialLink("Mine", "https://m.com/?s={serial}")]
    cfg.save(path)
    assert Config.load(path).serial_links == cfg.serial_links


def test_upgrade_adds_official_links_once_and_preserves_custom_rows(tmp_path):
    path = tmp_path / "config.json"
    custom = SerialLink("My site", "https://example.com/{serial}")
    colt = SerialLink("Colt official", "https://example.com/custom-colt")
    cfg = Config(base_dir=tmp_path, photos_dir=tmp_path, serial_links=[custom, colt])
    cfg.save(path)
    data = json.loads(path.read_text())
    del data["serial_links_configurable"]
    path.write_text(json.dumps(data))
    upgraded = Config.load(path)
    assert upgraded.serial_links == [custom, colt, *OFFICIAL_LINKS[1:]]
    upgraded.serial_links = [custom]
    upgraded.save(path)
    assert Config.load(path).serial_links == [custom]
    upgraded.serial_links = []
    upgraded.save(path)
    assert Config.load(path).serial_links == []
