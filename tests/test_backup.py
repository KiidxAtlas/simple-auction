import sqlite3
import stat
import zipfile
from threading import RLock
from types import SimpleNamespace

import pytest

from simple_auction.services import backup
from simple_auction.services.config import Config
from simple_auction.services.network import Sharing


@pytest.fixture
def configured(tmp_path):
    config = Config(
        base_dir=tmp_path / "working", photos_dir=tmp_path / "separate-photos"
    )
    config.data_dir.mkdir(parents=True)
    config.photos_dir.mkdir()
    (config.data_dir / "shipping").mkdir()
    (config.data_dir / "shipping" / "batch.json").write_text('{"buyers": []}')
    (config.photos_dir / "photo.jpg").write_bytes(b"photo bytes")
    (config.base_dir / ".env").write_text("GEMINI_API_KEY=not-for-backup")
    (config.base_dir / "scratch").mkdir()
    (config.base_dir / "scratch" / "draft").write_text("scratch")
    return config


def make(config, tmp_path, **kwargs):
    return backup.create_backup(
        config, tmp_path / "backup.zip", status_path=tmp_path / "status.json", **kwargs
    )


def test_roundtrip_external_photos_shipping_settings_and_status(configured, tmp_path):
    config = configured
    config.sharing = Sharing(mode="off", code="123456")
    config.dark_mode = True
    result = make(config, tmp_path)
    assert backup.last_backup_status(tmp_path / "status.json")["path"] == str(
        result.path
    )
    with zipfile.ZipFile(result.path) as archive:
        assert "123456" not in archive.read("settings.json").decode()
        assert not any(
            ".env" in name or "scratch" in name for name in archive.namelist()
        )
    restored = backup.restore_backup(result.path, tmp_path / "restored")
    assert restored.config_path == tmp_path / "restored" / "config.json"
    assert restored.config.dark_mode is True
    assert restored.config.photos_dir == tmp_path / "restored" / "photos"
    assert (restored.config.photos_dir / "photo.jpg").read_bytes() == b"photo bytes"
    assert (
        restored.config.data_dir / "shipping" / "batch.json"
    ).read_text() == '{"buyers": []}'
    assert (config.photos_dir / "photo.jpg").exists()
    loaded, _ = Config._from_bytes(restored.config_path.read_bytes())
    assert loaded.base_dir == restored.config.base_dir
    assert loaded.sharing.mode == "off"


def test_sqlite_snapshot_includes_uncheckpointed_wal(configured, tmp_path):
    path = configured.data_dir / "shared.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE data(value TEXT)")
        connection.execute("INSERT INTO data VALUES ('latest')")
        connection.commit()
        database = SimpleNamespace(path=path, lock=RLock())
        result = make(configured, tmp_path, database=database)
        with zipfile.ZipFile(result.path) as archive:
            assert not any(
                name.endswith(("-wal", "-shm")) for name in archive.namelist()
            )
        restored = backup.restore_backup(result.path, tmp_path / "restored")
        with sqlite3.connect(restored.config.data_dir / "shared.sqlite3") as snapshot:
            assert snapshot.execute("SELECT value FROM data").fetchall() == [
                ("latest",)
            ]


def test_host_requires_database_and_remote_cache_cannot_claim_full_backup(
    configured, tmp_path
):
    with pytest.raises(backup.BackupError, match="remote client"):
        make(configured, tmp_path, remote_client=True)
    configured.sharing = Sharing(mode="host", code="123456")
    with pytest.raises(backup.BackupError, match="database"):
        make(configured, tmp_path)
    assert not (tmp_path / "backup.zip").exists()


def test_same_and_nested_photo_roots_roundtrip(configured, tmp_path):
    for index, photo_root in enumerate(
        [configured.base_dir, configured.base_dir / "photos"]
    ):
        photo_root.mkdir(exist_ok=True)
        configured.photos_dir = photo_root
        (photo_root / "image.jpg").write_bytes(b"image")
        result = backup.create_backup(
            configured,
            configured.base_dir / f"output{index}.zip",
            status_path=tmp_path / "status.json",
        )
        with zipfile.ZipFile(result.path) as archive:
            assert not any(
                name.endswith(f"output{index}.zip") for name in archive.namelist()
            )
        restored = backup.restore_backup(result.path, tmp_path / f"restore{index}")
        assert (restored.config.photos_dir / "image.jpg").read_bytes() == b"image"


def test_never_replace_existing_backup_or_restore_data(configured, tmp_path):
    result = make(configured, tmp_path)
    original = result.path.read_bytes()
    with pytest.raises(backup.BackupError, match="never replaced"):
        make(configured, tmp_path)
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "precious").write_text("keep")
    with pytest.raises(backup.BackupError, match="empty"):
        backup.restore_backup(result.path, destination)
    assert result.path.read_bytes() == original
    assert (destination / "precious").read_text() == "keep"


def test_symlink_and_pending_transaction_fail_without_output(configured, tmp_path):
    link = configured.base_dir / "link"
    link.symlink_to(configured.photos_dir, target_is_directory=True)
    with pytest.raises(backup.BackupError, match="symbolic"):
        make(configured, tmp_path)
    link.unlink()
    (configured.data_dir / ".workbook.xlsx.transaction").mkdir()
    with pytest.raises(backup.BackupError, match="recovery"):
        make(configured, tmp_path)
    assert not (tmp_path / "backup.zip").exists()


@pytest.mark.parametrize(
    "name,mode",
    [
        ("../escape", 0),
        ("/escape", 0),
        ("base/../../escape", 0),
        ("base\\escape", 0),
        ("base/link", stat.S_IFLNK | 0o777),
        ("base/C:drive", 0),
    ],
)
def test_restore_rejects_zip_slip_and_symlinks(tmp_path, name, mode):
    source = tmp_path / "bad.zip"
    with zipfile.ZipFile(source, "w") as archive:
        info = zipfile.ZipInfo(name)
        info.external_attr = mode << 16
        archive.writestr(info, b"bad")
    with pytest.raises(backup.BackupError, match="Unsafe"):
        backup.restore_backup(source, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not (tmp_path / "escape").exists()


def rewrite_archive(path, change):
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    change(contents)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)


def test_checksum_failure_leaves_empty_destination_untouched(configured, tmp_path):
    result = make(configured, tmp_path)
    rewrite_archive(
        result.path,
        lambda contents: contents.update({"photos/photo.jpg": b"wrong bytes"}),
    )
    destination = tmp_path / "restored"
    destination.mkdir()
    with pytest.raises(backup.BackupError, match="checksum"):
        backup.restore_backup(result.path, destination)
    assert list(destination.iterdir()) == []
    assert not list(tmp_path.glob(".auction-restore-*"))


def test_bomb_limit_is_checked_before_extracting(configured, tmp_path, monkeypatch):
    result = make(configured, tmp_path)
    monkeypatch.setattr(backup, "MAX_TOTAL_BYTES", 10)
    with pytest.raises(backup.BackupError, match="oversized"):
        backup.restore_backup(result.path, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_actual_database_and_storage_locks_are_taken(configured, tmp_path, monkeypatch):
    events = []

    class Lock:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            events.append("enter " + self.name)

        def __exit__(self, *args):
            events.append("exit " + self.name)

    monkeypatch.setattr(backup.storage, "lock", Lock("storage"))
    database = SimpleNamespace(
        path=configured.data_dir / "shared.sqlite3", lock=Lock("database")
    )
    make(configured, tmp_path, database=database)
    assert events == [
        "enter database",
        "enter storage",
        "exit storage",
        "exit database",
    ]


def test_status_failure_does_not_discard_created_backup(
    configured, tmp_path, monkeypatch
):
    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(backup.storage, "atomic_write", fail)
    result = make(configured, tmp_path)
    assert result.path.exists()
    assert "status" in result.status_warning
