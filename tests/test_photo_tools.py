from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from simple_auction.models import Lot
from simple_auction.services import image
from simple_auction.ui.components.lot_form import LotForm
from simple_auction.ui.photo_preview import PhotoPreview


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def make_photo(folder: Path, name: str, size=(300, 200), colour="red") -> Path:
    path = folder / name
    Image.new("RGB", size, colour).save(path, "JPEG")
    return path


@pytest.fixture
def form(app, tmp_path):
    photos = [
        make_photo(tmp_path, "41000.jpg"),
        make_photo(tmp_path, "41000-1.jpg", colour="blue"),
        make_photo(tmp_path, "41000-2.jpg", colour="green"),
    ]
    f = LotForm()
    f.load(Lot(41000, photos=photos), 41000)
    yield f
    f.close()


def names(form):
    return [p.stem for p in form.collect().photos]


def test_rotated_copy_turns_the_photo_and_leaves_the_original(tmp_path):
    src = make_photo(tmp_path, "41000.jpg", size=(300, 200))
    before = src.read_bytes()
    turned = image.rotated_copy(src, tmp_path, 90)
    assert turned.name == "41000.jpg" and turned != src
    with Image.open(turned) as img:
        assert img.size == (200, 300)
    assert src.read_bytes() == before


def test_photo_info_reports_upright_size(tmp_path):
    src = make_photo(tmp_path, "a.jpg", size=(300, 200))
    assert image.photo_info(src) == (300, 200, src.stat().st_size)
    assert image.photo_info(tmp_path / "missing.jpg") is None


def test_make_main_photo_puts_it_first_and_marks_the_lot_changed(form):
    changes = []
    form.changed.connect(lambda: changes.append(1))
    form._move_photo(2, 0)
    assert names(form) == ["41000-2", "41000", "41000-1"]
    assert changes
    assert form.photo_list.currentRow() == 0


def test_moving_past_the_ends_is_ignored(form):
    form._move_photo(0, -5)
    form._move_photo(2, 9)
    assert names(form) == ["41000", "41000-1", "41000-2"]


def test_dragging_in_the_list_reorders_the_photos(form):
    form.photo_list.model().moveRow(
        form.photo_list.rootIndex(), 1, form.photo_list.rootIndex(), 0
    )
    assert names(form) == ["41000-1", "41000", "41000-2"]


def test_rotate_selected_turns_only_those_photos(form):
    form.photo_list.item(1).setSelected(True)
    form._rotate_selected(90)
    photos = form.collect().photos
    sizes = [Image.open(p).size for p in photos]
    assert sizes == [(300, 200), (200, 300), (300, 200)]
    assert [p.stem for p in photos] == ["41000", "41000-1", "41000-2"]


def test_rotate_with_no_selection_turns_every_photo(form):
    form._rotate_selected(-90)
    assert {Image.open(p).size for p in form.collect().photos} == {(200, 300)}


def test_oversized_photo_is_flagged_in_the_list(app, tmp_path):
    big = make_photo(tmp_path, "41000.jpg", size=(3000, 2000))
    f = LotForm()
    f.load(Lot(41000, photos=[big]), 41000)
    item = f.photo_list.item(0)
    assert "3000×2000" in item.text()
    assert "resized" in item.toolTip()
    f.close()


def test_preview_steps_through_photos_within_bounds(app, tmp_path):
    photos = [make_photo(tmp_path, f"{n}.jpg") for n in ("a", "b")]
    dialog = PhotoPreview(photos, 0)
    assert not dialog.prev_btn.isEnabled() and dialog.next_btn.isEnabled()
    dialog.step(1)
    dialog.step(1)
    assert dialog._index == 1 and not dialog.next_btn.isEnabled()
    assert "2 of 2" in dialog.caption.text()
    dialog.deleteLater()


def test_preview_survives_an_unreadable_photo(app, tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    dialog = PhotoPreview([bad], 0)
    assert "bad.jpg" in dialog.caption.text()
    dialog.deleteLater()
