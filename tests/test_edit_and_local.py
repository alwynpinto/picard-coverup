"""Rotate, crop, TIFF, 'always JPEG', and every local image offered for front, back and disc."""

import pytest

pytest.importorskip("PyQt6.QtGui", reason="PyQt6 is needed for image tests (pip install PyQt6)")

from coverup import imaging
from coverup.apply.writer import write_item  # noqa: F401  (imported to make sure the module loads)
from coverup.providers.local import scan_folder
from helpers import make_image

pytestmark = pytest.mark.usefixtures("qapp")


def test_rotate_turns_the_picture_and_returns_jpeg():
    wide = make_image("a", w=600, h=300)
    for deg in (90, -90):
        out = imaging.rotate(wide, deg)
        assert imaging._format_of(out) == "jpeg" and imaging.size_of(out) == (300, 600)
    assert imaging.size_of(imaging.rotate(wide, 180)) == (600, 300)
    assert imaging.size_of(imaging.rotate(wide, 360)) == (600, 300)


def test_crop_cuts_the_rectangle_and_clamps_to_the_image():
    img = make_image("a", 600)
    assert imaging.size_of(imaging.crop(img, 100, 50, 300, 200)) == (300, 200)
    assert imaging.size_of(imaging.crop(img, 500, 500, 900, 900)) == (100, 100)  # clamped, never an error


def test_png_and_tiff_become_jpeg_when_prepared():
    png = make_image("b", 400, fmt="png")
    assert imaging._format_of(png) == "png"
    out, w, h, fmt = imaging.prepare(png)
    assert fmt == "jpeg" and imaging._format_of(out) == "jpeg" and (w, h) == (400, 400)
    jpg = make_image("a", 400)
    assert imaging.prepare(jpg)[0] == jpg  # a JPEG is left exactly as it is


def _tiff(tmp_path, name="scan.tif"):
    from PyQt6.QtGui import QImage

    img = imaging.load(make_image("a", 500))
    assert isinstance(img, QImage)
    path = tmp_path / name
    if not img.save(str(path), "TIFF"):
        pytest.skip("this Qt build has no TIFF plugin")
    return path


def test_local_scan_finds_jpg_png_tiff_in_the_folder_and_its_subfolders(tmp_path):
    (tmp_path / "front.jpg").write_bytes(make_image("a", 600))
    (tmp_path / "back scan.png").write_bytes(make_image("b", 600, fmt="png"))
    _tiff(tmp_path, "disc.tif")
    sub = tmp_path / "Scans 2021"
    sub.mkdir()
    (sub / "inlay.jpeg").write_bytes(make_image("c", 600))
    (tmp_path / ".coverup-backup").mkdir()
    (tmp_path / ".coverup-backup" / "old.jpg").write_bytes(make_image("a", 600))
    names = {c.comment for c in scan_folder(tmp_path)}
    assert names == {"front.jpg", "back scan.png", "disc.tif", "inlay.jpeg"}
    tif = next(c for c in scan_folder(tmp_path) if c.comment == "disc.tif")
    assert (tif.width, tif.height) == (500, 500) and imaging._format_of(tif.data) == "jpeg" and tif.extra["source_format"] == "tif"
