"""Atomic files and recoverable multi-file commits for catalogue saves."""

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from threading import RLock

# Serialize catalogue reads/recovery and writes within this process.

log = logging.getLogger(__name__)
lock = RLock()


def _sync_directory(path: Path) -> None:
    # POSIX needs the directory entry flushed as well as the file contents.
    # Windows does not allow opening directories with this interface.
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_write(path: Path, data: bytes) -> None:
    """Replace only after a complete, flushed write, on the destination filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        _sync_directory(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def journal_path(workbook: Path) -> Path:
    return workbook.parent / f".{workbook.name}.transaction"


def recover(journal: Path) -> None:
    """Roll back an interrupted commit; committed journals only need cleanup.

    Backups remain until *all* restores succeed, so recovery is itself retryable.
    A crash during preparation has no manifest and has not changed any originals.
    """
    with lock:
        if not journal.exists():
            return
        manifest = journal / "manifest.json"
        if manifest.exists() and not (journal / "committed").exists():
            entries = json.loads(manifest.read_text(encoding="utf-8"))
            for entry in entries:
                path = Path(entry["path"])
                if entry["backup"] is None:
                    if path.exists():
                        path.unlink()
                        _sync_directory(path.parent)
                else:
                    original = (journal / entry["backup"]).read_bytes()
                    if not path.exists() or path.read_bytes() != original:
                        atomic_write(path, original)
        shutil.rmtree(journal)


def commit(changes: dict[Path, bytes | None], journal: Path) -> None:
    """Commit prepared replacements/removals, retaining originals for recovery."""
    with lock:
        recover(journal)
        journal.mkdir(parents=True)
        entries = []
        try:
            _sync_directory(journal.parent)
            for i, path in enumerate(changes):
                backup = str(i) if path.exists() else None
                if backup is not None:
                    atomic_write(journal / backup, path.read_bytes())
                entries.append({"path": str(path.resolve()), "backup": backup})
            atomic_write(journal / "manifest.json", json.dumps(entries).encode("utf-8"))
            for path, data in changes.items():
                if data is None:
                    if path.exists():
                        path.unlink()
                        _sync_directory(path.parent)
                else:
                    atomic_write(path, data)
            atomic_write(journal / "committed", b"done")
        except BaseException:
            marker = journal / "committed"
            if marker.exists():
                marker.unlink()
                _sync_directory(journal)
            # Don't mask a failed recovery: its journal must stay for the next try.
            recover(journal)
            raise
        # Failure to clean a committed journal is not a failed save. Recovery will
        # finish cleanup next time, without restoring stale data.
        try:
            shutil.rmtree(journal)
        except OSError as e:
            log.warning("Save committed; journal cleanup pending at %s: %s", journal, e)
