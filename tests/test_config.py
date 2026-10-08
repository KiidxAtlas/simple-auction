import json
from pathlib import Path

from simple_auction.services.config import Config


def test_folders(tmp_path):
    cfg = Config(base_dir=tmp_path, photos_dir=tmp_path / "pics")
    assert cfg.auctions_dir == tmp_path / "auctions"
    assert cfg.data_dir == tmp_path / "data"
    assert cfg.auction_photos_dir(41000) == tmp_path / "pics" / "auction 41000 photos"


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    Config(base_dir=Path("/a"), photos_dir=Path("/b"), step=500).save(path)
    loaded = Config.load(path)
    assert (loaded.base_dir, loaded.photos_dir, loaded.step) == (
        Path("/a"),
        Path("/b"),
        500,
    )


def test_old_config_key_is_the_main_folder(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"auctions_dir": "/old/place"}))
    assert Config.load(path).base_dir == Path("/old/place")


def test_move_old_files_into_subfolders(tmp_path):
    for name in ["40000.xlsx", "41000.xlsx", "41000 details.json", "serial_years.json"]:
        (tmp_path / name).write_text(name)
    (tmp_path / "notes.xlsx").write_text("keep")
    (tmp_path / "auctions").mkdir()
    (tmp_path / "auctions" / "41000.xlsx").write_text("newer")  # don't overwrite

    cfg = Config(base_dir=tmp_path)
    cfg.move_old_files()

    assert (cfg.auctions_dir / "40000.xlsx").read_text() == "40000.xlsx"
    assert (cfg.auctions_dir / "41000.xlsx").read_text() == "newer"
    assert (tmp_path / "41000.xlsx").exists()  # left where it was
    assert (cfg.data_dir / "41000 details.json").exists()
    assert (cfg.data_dir / "serial_years.json").exists()
    assert (tmp_path / "notes.xlsx").exists()
