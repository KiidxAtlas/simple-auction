import os

from PIL import Image

from simple_auction.constants import IMAGE_SIZE_RATIO
from simple_auction.services.image import image_name, lot_photo_files, process_photos


def test_image_name():
    assert image_name(41001, 0) == "41001"
    assert image_name(41001, 2) == "41001-2"


def test_resave_removes_and_renames_without_recompressing(tmp_path):
    src = tmp_path / "IMG_1.jpg"
    noise = Image.frombytes("RGB", (200, 150), os.urandom(200 * 150 * 3))
    noise.save(src, "JPEG", quality=95)
    dest = tmp_path / "out"
    first = process_photos(41001, [src, src, src], dest)
    kept = first[2].read_bytes()

    # Drop the first two photos: the third becomes 41001.jpg, unchanged.
    out = process_photos(41001, [first[2]], dest)

    assert [p.name for p in out] == ["41001.jpg"]
    assert out[0].read_bytes() == kept
    assert lot_photo_files(41001, dest) == out


def test_process_photos_renames_and_halves_file_size(tmp_path):
    src = tmp_path / "IMG_1.jpg"
    noise = Image.frombytes("RGB", (400, 300), os.urandom(400 * 300 * 3))
    noise.save(src, "JPEG", quality=95)

    out = process_photos(41001, [src, src], tmp_path / "out")

    assert [p.name for p in out] == ["41001.jpg", "41001-1.jpg"]
    for p in out:
        assert p.stat().st_size <= src.stat().st_size * IMAGE_SIZE_RATIO
