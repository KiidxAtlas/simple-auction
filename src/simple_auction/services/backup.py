"""Portable, consistent backups and non-destructive, staged restores.

Callers must save drafts and stop local catalogue editing during create_backup.
A running host must supply its Database (Host.db); lock order matches migration:
Database.lock, then storage.lock. Remote client caches are never full backups.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import zipfile
import zlib
from contextlib import closing, nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from simple_auction.services import storage
from simple_auction.services.config import CONFIG_PATH, Config
from simple_auction.services.network import Sharing

STATUS_PATH = CONFIG_PATH.with_name("last-backup.json")
MAX_FILES = 100_000
MAX_FILE_BYTES = 8 * 1024**3
MAX_TOTAL_BYTES = 50 * 1024**3
MAX_MANIFEST_BYTES = 8 * 1024**2
MAX_COMPRESSION_RATIO = 2000
_SKIP_DIRS = {"scratch", ".scratch", "__pycache__", ".cache", ".git"}


class BackupError(ValueError):
    """The operation cannot safely proceed; existing data is untouched."""


@dataclass(frozen=True)
class BackupResult:
    path: Path
    created_at: str
    file_count: int
    status_warning: str = ""


@dataclass(frozen=True)
class RestoreResult:
    destination: Path
    config_path: Path
    config: Config


def last_backup_status(path: Path = STATUS_PATH) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except OSError, ValueError:
        return None


def _settings(config: Config) -> bytes:
    # Pairing codes are credentials too. Never read keyring or the environment.
    return replace(config, sharing=Sharing())._encode()


def _excluded(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in _SKIP_DIRS
        or name == ".env"
        or name.startswith((".env.", "~$", ".removed-"))
        or name.endswith((".tmp", ".part", "~"))
    )


def _files(root: Path, other: Path, excluded: set[Path]):
    if not root.exists():
        return
    if root.is_symlink() or not root.is_dir():
        raise BackupError(f"Data folder must be a real directory: {root}")
    for folder, dirs, files in os.walk(root, followlinks=False):
        folder = Path(folder)
        kept = []
        for name in sorted(dirs):
            child = folder / name
            if _excluded(child) or child in excluded or child == other:
                continue
            if child.is_symlink():
                raise BackupError(f"Backups do not follow symbolic links: {child}")
            if name.startswith(".") and name.endswith(".transaction"):
                raise BackupError(
                    "Pending save recovery found. Reopen the catalogue before backing up."
                )
            kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            child = folder / name
            if _excluded(child) or child in excluded:
                continue
            if child.is_symlink() or not child.is_file():
                raise BackupError(f"Backups require regular files: {child}")
            yield child


def _copy_stream(source, target) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_FILE_BYTES:
            raise BackupError("A file exceeds the backup size limit.")
        digest.update(chunk)
        target.write(chunk)
    return size, digest.hexdigest()


def create_backup(
    config: Config,
    destination: Path,
    *,
    database=None,
    remote_client: bool = False,
    status_path: Path = STATUS_PATH,
) -> BackupResult:
    """Create a new ZIP, never replacing an existing file, including shared DB assets."""
    if remote_client or config.sharing.mode == "join":
        raise BackupError(
            "Full backups must be made on the host, not from a remote client cache."
        )
    if config.sharing.mode == "host" and database is None:
        raise BackupError(
            "A running host must supply its database for a consistent backup."
        )
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise BackupError(
            "Choose a new backup filename; existing backups are never replaced."
        )
    base = config.base_dir.absolute()
    photos = config.photos_dir.absolute()
    if base.is_symlink() or photos.is_symlink():
        raise BackupError("Configured folders cannot be symbolic links.")
    base, photos = base.resolve(), photos.resolve()
    db_path = base / "data" / "shared.sqlite3"
    if database is not None and Path(database.path).resolve() != db_path:
        raise BackupError("The supplied database does not belong to these settings.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = datetime.now(UTC).isoformat()
    entries = {}
    total = 0
    with tempfile.TemporaryDirectory(prefix="simple-auction-backup-") as scratch:
        scratch = Path(scratch)
        archive = scratch / "backup.zip"
        with (
            database.lock if database is not None else nullcontext(),
            storage.lock,
            zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as out,
        ):
            excluded = {
                destination.resolve(),
                scratch.resolve(),
                status_path.resolve(),
            }
            db_related = {
                db_path,
                Path(str(db_path) + "-wal"),
                Path(str(db_path) + "-shm"),
                Path(str(db_path) + "-journal"),
            }
            for label, root, other in (
                ("base", base, photos),
                ("photos", photos, base),
            ):
                # Equal roots need only one copy; restore points photos at base.
                if label == "photos" and photos == base:
                    continue
                for path in _files(
                    root,
                    other if other != root else Path("/___unused___"),
                    excluded,
                ):
                    if path in db_related:
                        continue
                    name = f"{label}/{path.relative_to(root).as_posix()}"
                    with (
                        path.open("rb") as source,
                        out.open(name, "w", force_zip64=True) as target,
                    ):
                        size, digest = _copy_stream(source, target)
                    entries[name] = {"size": size, "sha256": digest}
                    total += size
                    if total > MAX_TOTAL_BYTES or len(entries) > MAX_FILES:
                        raise BackupError(
                            "Backup exceeds the archive size or file count limit."
                        )
            if db_path.exists():
                snapshot = scratch / "shared.sqlite3"
                with (
                    closing(
                        sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
                    ) as source,
                    closing(sqlite3.connect(snapshot)) as target,
                ):
                    source.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                        raise BackupError("Shared database failed its integrity check.")
                with (
                    snapshot.open("rb") as source,
                    out.open(
                        "base/data/shared.sqlite3", "w", force_zip64=True
                    ) as target,
                ):
                    size, digest = _copy_stream(source, target)
                entries["base/data/shared.sqlite3"] = {
                    "size": size,
                    "sha256": digest,
                }
                total += size
            raw = _settings(config)
            out.writestr("settings.json", raw)
            entries["settings.json"] = {
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            if total + len(raw) > MAX_TOTAL_BYTES or len(entries) > MAX_FILES:
                raise BackupError(
                    "Backup exceeds the archive size or file count limit."
                )
            manifest = {
                "format": 1,
                "created_at": created,
                "photos_in_base": photos == base,
                "files": entries,
            }
            manifest_raw = json.dumps(manifest).encode("utf-8")
            if len(manifest_raw) > MAX_MANIFEST_BYTES:
                raise BackupError("Backup manifest exceeds the size limit.")
            out.writestr("manifest.json", manifest_raw)
        # Exclusive create preserves any file created by another process meanwhile.
        try:
            with destination.open("xb") as target, archive.open("rb") as source:
                try:
                    shutil.copyfileobj(source, target)
                    target.flush()
                    os.fsync(target.fileno())
                except BaseException:
                    destination.unlink(missing_ok=True)
                    raise
        except FileExistsError as e:
            raise BackupError("The backup filename is already in use.") from e
    warning = ""
    try:
        storage.atomic_write(
            status_path,
            json.dumps(
                {
                    "path": str(destination),
                    "created_at": created,
                    "file_count": len(entries),
                }
            ).encode("utf-8"),
        )
    except OSError as e:
        warning = (
            f"Backup created, but local last-backup status could not be saved: {e}"
        )
    return BackupResult(destination, created, len(entries), warning)


def _validate_archive(archive: zipfile.ZipFile) -> dict:
    infos = archive.infolist()
    if len(infos) > MAX_FILES + 1:
        raise BackupError("Too many archive entries.")
    names = set()
    folded_names = set()
    total = 0
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        mode = info.external_attr >> 16
        if (
            not name
            or "\\" in name
            or ":" in name
            or "\x00" in name
            or path.is_absolute()
            or any(p in {".", "..", ""} for p in name.split("/"))
            or name in names
            or info.is_dir()
            or (stat.S_IFMT(mode) not in {0, stat.S_IFREG})
        ):
            raise BackupError(f"Unsafe archive entry: {name!r}")
        # Case-fold collisions are unsafe on Windows and default macOS volumes.
        if name.casefold() in folded_names:
            raise BackupError("Archive contains conflicting filenames.")
        folded_names.add(name.casefold())
        names.add(name)
        total += info.file_size
        if (
            info.flag_bits & 1
            or info.file_size > MAX_FILE_BYTES
            or total > MAX_TOTAL_BYTES
            or info.file_size > max(1, info.compress_size) * MAX_COMPRESSION_RATIO
        ):
            raise BackupError("Encrypted or oversized archive entry.")
    if not {"manifest.json", "settings.json"} <= names:
        raise BackupError("Not a Simple Auction full backup.")
    if archive.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES:
        raise BackupError("Backup manifest is too large.")
    manifest = json.loads(archive.read("manifest.json"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != 1
        or type(manifest.get("photos_in_base")) is not bool
    ):
        raise BackupError("Unsupported backup format.")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != names - {"manifest.json"}:
        raise BackupError("Backup contents do not match the manifest.")
    for name, record in files.items():
        if name != "settings.json" and not name.startswith(("base/", "photos/")):
            raise BackupError("Unexpected backup content.")
        if (
            not isinstance(record, dict)
            or type(record.get("size")) is not int
            or record["size"] != archive.getinfo(name).file_size
            or not isinstance(record.get("sha256"), str)
            or len(record["sha256"]) != 64
        ):
            raise BackupError("Invalid backup file metadata.")
    return manifest


def restore_backup(source: Path, destination: Path) -> RestoreResult:
    """Validate and restore to an empty folder. Never activate or change current data."""
    destination = Path(destination).absolute()
    if destination.is_symlink() or (
        destination.exists()
        and (not destination.is_dir() or any(destination.iterdir()))
    ):
        raise BackupError("Restore requires a new or empty destination folder.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=".auction-restore-", dir=destination.parent))
    try:
        with zipfile.ZipFile(source) as archive:
            manifest = _validate_archive(archive)
            for name, record in manifest["files"].items():
                target = scratch / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as incoming, target.open("xb") as outgoing:
                    size, digest = _copy_stream(incoming, outgoing)
                if size != record["size"] or digest != record["sha256"]:
                    raise BackupError(f"Backup checksum mismatch: {name}")
        config, _ = Config._from_bytes((scratch / "settings.json").read_bytes())
        config.base_dir = destination / "base"
        config.photos_dir = (
            config.base_dir if manifest["photos_in_base"] else destination / "photos"
        )
        config.sharing = (
            Sharing()
        )  # Never reconnect a restored copy to the original host.
        (scratch / "base").mkdir(exist_ok=True)
        if not manifest["photos_in_base"]:
            (scratch / "photos").mkdir(exist_ok=True)
        config.save(scratch / "config.json")
        if destination.exists():
            destination.rmdir()  # Fails safely if it is no longer empty.
        scratch.rename(destination)
        return RestoreResult(destination, destination / "config.json", config)
    except (
        zipfile.BadZipFile,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        RuntimeError,
        EOFError,
        zlib.error,
    ) as e:
        raise BackupError(f"Invalid backup: {e}") from e
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)
