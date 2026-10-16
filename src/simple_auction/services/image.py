import io
import logging
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageOps

from simple_auction.constants import (
    IMAGE_MAX_QUALITY,
    IMAGE_MIN_QUALITY,
    PHOTO_FOLDER_NAME,
    PHOTO_MAX_BYTES,
    PHOTO_MAX_HEIGHT,
    PHOTO_MAX_WIDTH,
)
from simple_auction.services import storage

log = logging.getLogger(__name__)


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
            # Already ours: keep as is when it meets the standard, otherwise
            # bring it into line (also catches corrupt files before a commit).
            data = fit_saved(src.read_bytes())
        else:
            with Image.open(src) as img:
                data = conform(img)
        if not target.exists() or target.read_bytes() != data:
            changes[target] = data
        out.append(target)
    for old in lot_photo_files(lot_number, dest):
        if old not in out:
            changes[old] = None
    return changes, out


def _box(img: Image.Image) -> tuple[int, int]:
    """The largest allowed size for the photo's orientation."""
    if img.width >= img.height:
        return PHOTO_MAX_WIDTH, PHOTO_MAX_HEIGHT
    return PHOTO_MAX_HEIGHT, PHOTO_MAX_WIDTH


def conform(img: Image.Image) -> bytes:
    """JPEG bytes for a new photo: upright, within 1024x768 and 145 KB.

    Never enlarged, and re-encoding drops camera metadata such as location.
    """
    img = ImageOps.exif_transpose(img).convert("RGB")
    box = _box(img)
    if img.width > box[0] or img.height > box[1]:
        img = ImageOps.contain(img, box, Image.Resampling.LANCZOS)
    return _compress(img, PHOTO_MAX_BYTES)


def meets_standard(source: bytes | Path) -> bool:
    """Is this already a JPEG within the size, dimensions and orientation rules?

    A path is checked from its size and image header only, without reading the
    whole file.
    """
    if isinstance(source, Path):
        size, opened = source.stat().st_size, source
    else:
        size, opened = len(source), io.BytesIO(source)
    if size > PHOTO_MAX_BYTES:
        return False
    with Image.open(opened) as img:
        if img.format != "JPEG" or img.getexif().get(0x0112, 1) != 1:
            return False
        width, height = _box(img)
        return img.width <= width and img.height <= height


def fit_saved(data: bytes) -> bytes:
    """A photo already in the library, changed only if it breaks the standard."""
    if meets_standard(data):
        with Image.open(io.BytesIO(data)) as img:
            img.verify()  # also catches truncated files
        return data
    with Image.open(io.BytesIO(data)) as img:
        return conform(img)


def rotated_copy(src: Path, folder: Path, clockwise_degrees: int) -> Path:
    """A turned, upright copy of a photo in its own new subfolder of `folder`.

    The original is never touched (it may be the user's own file, or a photo
    in a shared cache). The copy keeps the file's name so the editor still
    shows it under the same label.
    """
    with Image.open(src) as img:
        turned = ImageOps.exif_transpose(img).convert("RGB")
    turned = turned.rotate(-clockwise_degrees, expand=True)
    target = Path(tempfile.mkdtemp(dir=folder)) / f"{src.stem}.jpg"
    target.write_bytes(_encode(turned, IMAGE_MAX_QUALITY))
    return target


def photo_info(path: Path) -> tuple[int, int, int] | None:
    """(width, height, bytes) as the photo will look upright, or None if unreadable.

    Reads the image header only.
    """
    try:
        size = path.stat().st_size
        with Image.open(path) as img:
            width, height = img.size
            if img.getexif().get(0x0112, 1) in (5, 6, 7, 8):
                width, height = height, width
    except OSError, ValueError:
        return None
    return width, height, size


_LOT_PHOTO = re.compile(r"\d+(-\d+)?\.jpg", re.IGNORECASE)


def fix_library(photos_dir: Path) -> int:
    """Bring every saved lot photo up to the standard; returns how many changed.

    Only files that break it are rewritten (same name, same place). A photo
    that cannot be read is left alone and logged rather than stopping the rest.
    """
    fixed = 0
    for folder in sorted(photos_dir.glob(PHOTO_FOLDER_NAME.format(auction="*"))):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if not _LOT_PHOTO.fullmatch(path.name):
                continue
            try:
                with storage.lock:
                    if meets_standard(path):
                        continue
                    with Image.open(io.BytesIO(path.read_bytes())) as img:
                        storage.atomic_write(path, conform(img))
                fixed += 1
            except OSError, ValueError:
                log.exception("Could not bring %s up to the photo standard", path)
    return fixed


RESEARCH_IMAGE_SIDE = 1280  # px; enough to read markings, small to upload
RAW_IMAGE_LIMIT = 7_000_000  # bytes; larger originals that PIL can't open are skipped
_RAW_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


def research_image(path: Path) -> tuple[bytes, str] | None:
    """A photo prepared for sending to research: (data, mime type).

    Downscaled to a JPEG when Pillow can read it; formats it can't (e.g.
    HEIC without a plugin) are sent as they are if small enough. None if the
    file can't be used.
    """
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((RESEARCH_IMAGE_SIDE, RESEARCH_IMAGE_SIDE))
            return _encode(img, 85), "image/jpeg"
    except OSError:
        mime = _RAW_MIME.get(path.suffix.lower())
        try:
            if mime and path.stat().st_size <= RAW_IMAGE_LIMIT:
                return path.read_bytes(), mime
        except OSError:
            pass
    return None


def _encode(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    # optimize: smaller file at the same quality, so more of the 145 KB goes to detail.
    img.save(buf, "JPEG", quality=quality, optimize=True)
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
