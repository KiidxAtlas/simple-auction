import io
import os

from PIL import Image

from simple_auction.constants import PHOTO_MAX_BYTES
from simple_auction.services.image import (
    fix_library,
    image_name,
    lot_photo_files,
    meets_standard,
    process_photos,
)


def _noise_jpeg(path, size, quality=95):
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(
        path, "JPEG", quality=quality
    )
    return path


def _size(path):
    with Image.open(path) as img:
        return img.size


def test_image_name():
    assert image_name(41001, 0) == "41001"
    assert image_name(41001, 2) == "41001-2"


def test_resave_removes_and_renames_without_recompressing(tmp_path):
    src = _noise_jpeg(tmp_path / "IMG_1.jpg", (200, 150))
    dest = tmp_path / "out"
    first = process_photos(41001, [src, src, src], dest)
    kept = first[2].read_bytes()

    # Drop the first two photos: the third becomes 41001.jpg, unchanged.
    out = process_photos(41001, [first[2]], dest)

    assert [p.name for p in out] == ["41001.jpg"]
    assert out[0].read_bytes() == kept
    assert lot_photo_files(41001, dest) == out


def test_new_photos_are_named_by_lot_and_fit_the_proxibid_standard(tmp_path):
    src = _noise_jpeg(tmp_path / "IMG_1.jpg", (3000, 2000))

    out = process_photos(41001, [src, src], tmp_path / "out")

    assert [p.name for p in out] == ["41001.jpg", "41001-1.jpg"]
    for p in out:
        assert p.stat().st_size <= PHOTO_MAX_BYTES
        width, height = _size(p)
        assert width <= 1024 and height <= 768


def test_portrait_photos_fit_the_rotated_box_and_small_ones_are_not_enlarged(tmp_path):
    tall = _noise_jpeg(tmp_path / "tall.jpg", (1500, 2000))
    small = _noise_jpeg(tmp_path / "small.jpg", (300, 200))

    first, second = process_photos(41001, [tall, small], tmp_path / "out")

    width, height = _size(first)
    assert width <= 768 and height <= 1024 and height > width
    assert _size(second) == (300, 200)


def test_exif_rotation_is_applied(tmp_path):
    src = tmp_path / "IMG.jpg"
    img = Image.new("RGB", (400, 200), "red")
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees to display upright
    img.save(src, "JPEG", exif=exif)

    (out,) = process_photos(41001, [src], tmp_path / "out")

    assert _size(out) == (200, 400)
    assert not meets_standard(src.read_bytes())
    assert meets_standard(out.read_bytes())


def test_fix_library_repairs_only_photos_that_break_the_standard(tmp_path):
    folder = tmp_path / "auction 41000 photos"
    folder.mkdir()
    big = _noise_jpeg(folder / "41001.jpg", (2400, 1800))
    extra = _noise_jpeg(folder / "41001-1.jpg", (1600, 1200))
    good = _noise_jpeg(folder / "41002.jpg", (400, 300), quality=60)
    unrelated = _noise_jpeg(folder / "notes.jpg", (2000, 1500))
    good_bytes, unrelated_bytes = good.read_bytes(), unrelated.read_bytes()
    broken = folder / "41003.jpg"
    broken.write_bytes(b"not an image")

    assert good_bytes and fix_library(tmp_path) == 2

    for p in (big, extra):
        assert p.stat().st_size <= PHOTO_MAX_BYTES
        width, height = _size(p)
        assert width <= 1024 and height <= 768
    assert sorted(p.name for p in lot_photo_files(41001, folder)) == [
        "41001-1.jpg",
        "41001.jpg",
    ]
    assert good.read_bytes() == good_bytes  # already fine: untouched
    assert unrelated.read_bytes() == unrelated_bytes  # not a lot photo
    assert broken.read_bytes() == b"not an image"  # unreadable: left alone
    assert fix_library(tmp_path) == 0  # nothing left to fix


def test_resaving_a_lot_repairs_its_oversized_saved_photos(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    saved = _noise_jpeg(dest / "41001.jpg", (2000, 1500))

    (out,) = process_photos(41001, [saved], dest)

    assert out == saved
    assert out.stat().st_size <= PHOTO_MAX_BYTES
    with Image.open(io.BytesIO(out.read_bytes())) as img:
        assert img.size[0] <= 1024
