import io
import uuid
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageOps

from simple_auction.constants import (
    IMAGE_MAX_QUALITY,
    IMAGE_MIN_QUALITY,
    IMAGE_SIZE_RATIO,
)


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
    """Make dest hold exactly `photos` for this lot, named 41001, 41001-1, ...

    New photos are compressed. Photos already in dest were compressed when
    first added, so they are only renamed. Old files no longer in the list
    are passed to `discard`.
    """
    dest.mkdir(parents=True, exist_ok=True)
    resolved = {p.resolve() for p in photos}
    for old in lot_photo_files(lot_number, dest):
        if old.resolve() not in resolved:
            discard(old)

    # Move processed photos out of the way so renames can't collide.
    staged: dict[Path, Path] = {}
    for src in photos:
        if src.parent.resolve() == dest.resolve() and src.exists():
            tmp = dest / f".staging-{uuid.uuid4().hex}.jpg"
            src.rename(tmp)
            staged[src] = tmp

    out: list[Path] = []
    for i, src in enumerate(photos):
        target = dest / f"{image_name(lot_number, i)}.jpg"
        if src in staged:
            staged[src].rename(target)
        else:
            with Image.open(src) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                data = _compress(img, int(src.stat().st_size * IMAGE_SIZE_RATIO))
            target.write_bytes(data)
        out.append(target)
    return out


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
