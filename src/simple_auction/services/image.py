import io
import tempfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageOps

from simple_auction.constants import (
    IMAGE_MAX_QUALITY,
    IMAGE_MIN_QUALITY,
    IMAGE_SIZE_RATIO,
)
from simple_auction.services import storage


def image_name(lot_number: int, index: int) -> str:
    """41001, 41001-1, 41001-2 ... (no extension)."""
    return str(lot_number) if index == 0 else f"{lot_number}-{index}"


def lot_photo_files(lot_number: int, folder: Path) -> list[Path]:
    """Processed photos on disk for a lot, in order: 41001.jpg, 41001-1.jpg, ..."""
    if not folder.exists():
        return []

    def index(p: Path) -> int | None:
        if p.stem == str(lot_number):
            return 0
        prefix, _, n = p.stem.rpartition("-")
        return int(n) if prefix == str(lot_number) and n.isdigit() else None

    found = [(index(p), p) for p in folder.glob(f"{lot_number}*.jpg")]
    return [p for i, p in sorted((i, p) for i, p in found if i is not None)]


def process_photos(
    lot_number: int,
    photos: list[Path],
    dest: Path,
    discard: Callable[[Path], object] = Path.unlink,
) -> list[Path]:
    """Validate all photos before changing disk; restore originals on failure."""
    journal = dest / f".{lot_number}.transaction"
    with storage.lock:
        storage.recover(journal)
        changes, out = prepare_photos(lot_number, photos, dest)
        removed = {p: p.read_bytes() for p, data in changes.items() if data is None}
        storage.commit(changes, journal)
        if discard is not Path.unlink and removed:
            archive = archive_removed(removed, dest)
            for copy in archive.iterdir():
                discard(copy)
            if not any(archive.iterdir()):
                archive.rmdir()
    return out


def archive_removed(removed: dict[Path, bytes], folder: Path) -> Path:
    """Preserve removed photos for recycling; failures leave the archive intact."""
    folder.mkdir(parents=True, exist_ok=True)
    archive = Path(tempfile.mkdtemp(prefix=".removed-", dir=folder))
    for path, data in removed.items():
        storage.atomic_write(archive / path.name, data)
    return archive


def prepare_photos(
    lot_number: int,
    photos: list[Path],
    dest: Path,
) -> tuple[dict[Path, bytes | None], list[Path]]:
    """Encode/validate the entire new photo set without deleting or renaming."""
    changes: dict[Path, bytes | None] = {}
    out = []
    for i, src in enumerate(photos):
        target = dest / f"{image_name(lot_number, i)}.jpg"
        if src.parent.resolve() == dest.resolve():
            data = src.read_bytes()
            # Also catch corrupt processed files before starting a commit.
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
        else:
            with Image.open(src) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                data = _compress(img, int(src.stat().st_size * IMAGE_SIZE_RATIO))
        if not target.exists() or target.read_bytes() != data:
            changes[target] = data
        out.append(target)
    for old in lot_photo_files(lot_number, dest):
        if old not in out:
            changes[old] = None
    return changes, out


def _encode(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _compress(img: Image.Image, target_bytes: int) -> bytes:
    """Highest JPEG quality that fits target_bytes; downscale if none does."""
    while True:
        lo, hi, best = IMAGE_MIN_QUALITY, IMAGE_MAX_QUALITY, None
        while lo <= hi:
            mid = (lo + hi) // 2
            data = _encode(img, mid)
            if len(data) <= target_bytes:
                best, lo = data, mid + 1
            else:
                hi = mid - 1
        if best is not None or min(img.size) <= 64:
            return best or _encode(img, IMAGE_MIN_QUALITY)
        img = img.resize(
            (round(img.width * 0.9), round(img.height * 0.9)),
            Image.Resampling.LANCZOS,
        )
