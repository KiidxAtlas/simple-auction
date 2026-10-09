import json

import pytest

from simple_auction.services import storage


def test_atomic_write_preserves_original_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_bytes(b"original")

    def fail(src, dest):
        raise PermissionError("denied")

    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(PermissionError):
        storage.atomic_write(path, b"new")
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


def test_commit_rolls_back_replacements_deletions_and_new_files(tmp_path, monkeypatch):
    old, removed, new = (tmp_path / name for name in ("old", "removed", "new"))
    old.write_bytes(b"original")
    removed.write_bytes(b"photo")
    journal = tmp_path / "journal"
    real_write = storage.atomic_write

    def fail_once(path, data):
        if path == new:
            raise OSError("disk full")
        real_write(path, data)

    monkeypatch.setattr(storage, "atomic_write", fail_once)
    with pytest.raises(OSError, match="disk full"):
        storage.commit({old: b"changed", removed: None, new: b"new"}, journal)
    assert old.read_bytes() == b"original"
    assert removed.read_bytes() == b"photo"
    assert not new.exists()
    assert not journal.exists()


def _interrupted(journal, originals):
    journal.mkdir()
    entries = []
    for i, (path, data) in enumerate(originals.items()):
        backup = str(i) if data is not None else None
        if backup is not None:
            (journal / backup).write_bytes(data)
        entries.append({"path": str(path), "backup": backup})
    (journal / "manifest.json").write_text(json.dumps(entries))


def test_recovery_restores_interrupted_transaction(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.write_bytes(b"changed")
    new.write_bytes(b"new")
    journal = tmp_path / "journal"
    _interrupted(journal, {old: b"original", new: None})
    storage.recover(journal)
    assert old.read_bytes() == b"original"
    assert not new.exists()
    assert not journal.exists()


def test_failed_recovery_retains_backups_and_can_be_retried(tmp_path, monkeypatch):
    path = tmp_path / "old"
    path.write_bytes(b"changed")
    journal = tmp_path / "journal"
    _interrupted(journal, {path: b"original"})
    real_write = storage.atomic_write

    def fail(path, data):
        raise PermissionError("locked")

    monkeypatch.setattr(storage, "atomic_write", fail)
    with pytest.raises(PermissionError):
        storage.recover(journal)
    assert (journal / "0").read_bytes() == b"original"
    monkeypatch.setattr(storage, "atomic_write", real_write)
    storage.recover(journal)
    assert path.read_bytes() == b"original"


def test_committed_transaction_is_not_rolled_back(tmp_path):
    path = tmp_path / "old"
    path.write_bytes(b"committed")
    journal = tmp_path / "journal"
    _interrupted(journal, {path: b"original"})
    (journal / "committed").write_bytes(b"done")
    storage.recover(journal)
    assert path.read_bytes() == b"committed"
    assert not journal.exists()


def test_unprepared_transaction_cleanup_does_not_touch_originals(tmp_path):
    path = tmp_path / "old"
    path.write_bytes(b"original")
    journal = tmp_path / "journal"
    journal.mkdir()
    (journal / "0").write_bytes(b"backup")
    storage.recover(journal)
    assert path.read_bytes() == b"original"
    assert not journal.exists()


def test_failure_after_commit_marker_is_written_still_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "original"
    path.write_bytes(b"original")
    journal = tmp_path / "journal"
    real_write = storage.atomic_write

    def fail_after_marker(path_, data):
        real_write(path_, data)
        if path_ == journal / "committed":
            raise OSError("commit marker directory flush failed")

    monkeypatch.setattr(storage, "atomic_write", fail_after_marker)
    with pytest.raises(OSError, match="commit marker"):
        storage.commit({path: b"changed"}, journal)
    assert path.read_bytes() == b"original"
    assert not journal.exists()
