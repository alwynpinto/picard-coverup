# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""Qt image operations: decode, fingerprint, resize, convert. Safe to call from worker threads
(QImage only, never QPixmap). Picard does not bundle Pillow, so everything here uses Qt."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QImage

from .imageinfo import probe
from .matching.phash import dhash, is_blank, trim_uniform_margins

GRID = 64


@dataclass
class Fingerprint:
    phash: int | None
    blank: bool
    width: int
    height: int
    format: str


def load(data: bytes) -> QImage:
    img = QImage()
    img.loadFromData(QByteArray(data))
    return img


def _format_of(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:3] == b"GIF":
        return "gif"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return "unknown"


def gray_grid(img: QImage, size: int = GRID) -> list[int]:
    small = img.convertToFormat(QImage.Format.Format_Grayscale8).scaled(
        size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    small = small.convertToFormat(QImage.Format.Format_Grayscale8)
    bpl = small.bytesPerLine()
    ptr = small.constBits()
    ptr.setsize(small.sizeInBytes())
    raw = bytes(ptr)
    return [raw[y * bpl + x] for y in range(size) for x in range(size)]


def fingerprint(data: bytes) -> Fingerprint | None:
    """Perceptual hash + blank flag + decoded size. None if the data is not a decodable image."""
    if not data:
        return None
    img = load(data)
    if img.isNull():
        return None
    grid = gray_grid(img)
    trimmed, tw, th = trim_uniform_margins(grid, GRID, GRID)
    blank = is_blank(grid)
    return Fingerprint(dhash(trimmed, tw, th), blank, img.width(), img.height(), _format_of(data))


def size_of(data: bytes) -> tuple[int, int] | None:
    img = load(data)
    return None if img.isNull() else (img.width(), img.height())


def dimensions(data: bytes) -> tuple[int, int] | None:
    """Width and height: from the header when it is cheap (JPEG, PNG...), by decoding otherwise (TIFF)."""
    info = probe(data[:65536])
    return (info[0], info[1]) if info else size_of(data)


def to_jpeg(data: bytes, quality: int = 95) -> bytes:
    """The image as a JPEG. JPEG input is returned untouched (no second generation of compression)."""
    if _format_of(data) == "jpeg":
        return data
    img = load(data)
    if img.isNull():
        raise ValueError("Not a decodable image")
    return encode(img, "jpeg", quality)


def rotate(data: bytes, degrees: int, quality: int = 95) -> bytes:
    """Rotate by a multiple of 90 degrees (positive = clockwise) and return a JPEG."""
    img = load(data)
    if img.isNull():
        raise ValueError("Not a decodable image")
    turns = (int(degrees) // 90) % 4
    if turns:
        from PyQt6.QtGui import QTransform

        img = img.transformed(QTransform().rotate(90 * turns), Qt.TransformationMode.SmoothTransformation)
    return encode(img, "jpeg", quality)


def crop(data: bytes, x: int, y: int, w: int, h: int, quality: int = 95) -> bytes:
    """Cut out a rectangle (pixels, clamped to the image) and return a JPEG."""
    img = load(data)
    if img.isNull():
        raise ValueError("Not a decodable image")
    x, y = max(0, min(int(x), img.width() - 1)), max(0, min(int(y), img.height() - 1))
    w, h = max(1, min(int(w), img.width() - x)), max(1, min(int(h), img.height() - y))
    return encode(img.copy(x, y, w, h), "jpeg", quality)


def is_valid_image(data: bytes) -> bool:
    return bool(data) and not load(data).isNull()


def encode(img: QImage, fmt: str = "jpeg", quality: int = 92) -> bytes:
    fmt = fmt.lower()
    if fmt == "jpeg" and img.hasAlphaChannel():
        flat = QImage(img.size(), QImage.Format.Format_RGB32)
        flat.fill(Qt.GlobalColor.white)
        from PyQt6.QtGui import QPainter

        p = QPainter(flat)
        p.drawImage(0, 0, img)
        p.end()
        img = flat
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = img.save(dev, "JPEG" if fmt == "jpeg" else "PNG", quality if fmt == "jpeg" else -1)
    dev.close()
    if not ok:
        raise ValueError(f"Could not encode image as {fmt}")
    return bytes(buf.data())


def prepare(
    data: bytes, max_side: int = 0, fmt: str = "jpeg", quality: int = 92, min_side: int = 0, upscale: bool = False
) -> tuple[bytes, int, int, str]:
    """Resize (never up unless ``upscale``) and/or convert. Returns (bytes, width, height, format).

    With ``fmt='original'`` and no resize needed, the original bytes are returned untouched (no
    re-encoding). WebP/GIF/BMP sources are converted to JPEG (PNG if they have transparency) because
    tag formats and players handle those best.
    """
    src_fmt = _format_of(data)
    img = load(data)
    if img.isNull():
        raise ValueError("Not a decodable image")
    w, h = img.width(), img.height()
    target = img
    longest = max(w, h)
    if max_side and longest > max_side:
        target = img.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    elif upscale and min_side and longest < min_side:
        target = img.scaled(min_side, min_side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    out_fmt = fmt
    if fmt == "original":
        out_fmt = src_fmt if src_fmt in ("jpeg", "png") else ("png" if img.hasAlphaChannel() else "jpeg")
    if target is img and out_fmt == src_fmt:
        return data, w, h, src_fmt
    return encode(target, out_fmt, quality), target.width(), target.height(), out_fmt


def extension_for(fmt: str) -> str:
    return {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif"}.get(fmt, ".jpg")


def mime_for(fmt: str) -> str:
    return {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}.get(fmt, "image/jpeg")
