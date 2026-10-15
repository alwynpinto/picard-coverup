# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""Qt rendering for creative art: offline procedural backgrounds, and the logo/title compositor.

Text and logos are always drawn here, never by an AI model, so they are sharp and correctly spelled.
QImage/QPainter only, so this is safe in worker threads.
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

STYLES = ("gradient", "nebula", "rings", "grid", "minimal", "bauhaus", "halftone", "waves", "brush")


def _colors(palette: list[str]) -> list[QColor]:
    cols = [QColor(c) for c in palette if QColor(c).isValid()]
    return cols or [QColor("#222222"), QColor("#888888"), QColor("#dddddd"), QColor("#c0392b")]


def procedural(style: str, size: int, seed: int, palette: list[str]) -> QImage:
    """Render an abstract background. Same (style, size, seed, palette) -> same image."""
    rnd = random.Random(seed)
    cols = _colors(palette)
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(cols[0])
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    pick = lambda: QColor(rnd.choice(cols))  # noqa: E731

    if style == "nebula":
        bg = QLinearGradient(0, 0, s, s)
        bg.setColorAt(0, cols[0].darker(160))
        bg.setColorAt(1, cols[0])
        p.fillRect(img.rect(), bg)
        for _ in range(9):
            c = pick()
            c.setAlpha(rnd.randint(40, 110))
            g = QRadialGradient(QPointF(rnd.uniform(0, s), rnd.uniform(0, s)), rnd.uniform(s * 0.2, s * 0.6))
            g.setColorAt(0, c)
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(img.rect(), g)
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(int(s * 0.35)):
            a = rnd.randint(80, 255)
            p.setBrush(QColor(255, 255, 255, a))
            r = rnd.choice((0.6, 0.8, 1.0, 1.4, 2.2)) * s / 1000
            p.drawEllipse(QPointF(rnd.uniform(0, s), rnd.uniform(0, s)), r, r)
        if rnd.random() < 0.8:  # a planet
            c = pick()
            cx, cy, r = rnd.uniform(s * 0.25, s * 0.75), rnd.uniform(s * 0.4, s * 0.8), rnd.uniform(s * 0.12, s * 0.28)
            g = QRadialGradient(QPointF(cx - r / 3, cy - r / 3), r * 1.3)
            g.setColorAt(0, c.lighter(150))
            g.setColorAt(1, c.darker(250))
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(cx, cy), r, r)
    elif style == "rings":
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = s * rnd.uniform(0.35, 0.65), s * rnd.uniform(0.35, 0.65)
        for i in range(28, 0, -1):
            pen = QPen(cols[i % len(cols)], s * rnd.uniform(0.006, 0.02))
            p.setPen(pen)
            r = s * 0.025 * i
            p.drawEllipse(QPointF(cx, cy), r, r)
    elif style == "grid":
        g = QLinearGradient(0, 0, 0, s)
        g.setColorAt(0, cols[0])
        g.setColorAt(0.55, cols[1 % len(cols)].darker(200))
        g.setColorAt(1, cols[0])
        p.fillRect(img.rect(), g)
        sun = QRadialGradient(QPointF(s / 2, s * 0.45), s * 0.22)
        sun.setColorAt(0, cols[-1])
        sun.setColorAt(1, cols[1 % len(cols)])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(sun))
        p.drawEllipse(QPointF(s / 2, s * 0.45), s * 0.2, s * 0.2)
        p.fillRect(QRectF(0, s * 0.55, s, s * 0.45), cols[0])
        pen = QPen(cols[2 % len(cols)], max(1.0, s / 400))
        p.setPen(pen)
        horizon = s * 0.55
        for i in range(1, 16):
            y = horizon + (s - horizon) * (i / 15) ** 2
            p.drawLine(QPointF(0, y), QPointF(s, y))
        for i in range(-12, 13):
            p.drawLine(QPointF(s / 2 + i * s * 0.02, horizon), QPointF(s / 2 + i * s * 0.18, s))
    elif style == "minimal":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(cols[1 % len(cols)])
        if rnd.random() < 0.5:
            p.drawEllipse(QPointF(s * rnd.uniform(0.3, 0.7), s * rnd.uniform(0.35, 0.6)), s * 0.22, s * 0.22)
        else:
            p.drawRect(QRectF(s * 0.18, s * rnd.uniform(0.3, 0.5), s * 0.64, s * 0.12))
        p.setBrush(cols[2 % len(cols)])
        p.drawRect(QRectF(0, s * 0.88, s, s * 0.12))
    elif style == "bauhaus":
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(9):
            p.setBrush(pick())
            kind = rnd.choice(("circle", "rect", "tri"))
            x, y, r = rnd.uniform(0, s), rnd.uniform(0, s), rnd.uniform(s * 0.08, s * 0.3)
            if kind == "circle":
                p.drawEllipse(QPointF(x, y), r, r)
            elif kind == "rect":
                p.drawRect(QRectF(x - r, y - r / 3, 2 * r, r / 1.5))
            else:
                path = QPainterPath(QPointF(x, y - r))
                path.lineTo(x + r, y + r)
                path.lineTo(x - r, y + r)
                path.closeSubpath()
                p.drawPath(path)
    elif style == "halftone":
        bg = QLinearGradient(0, 0, s, s)
        bg.setColorAt(0, cols[0])
        bg.setColorAt(1, cols[1 % len(cols)])
        p.fillRect(img.rect(), bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(cols[2 % len(cols)])
        step = s / 28
        cx, cy = rnd.uniform(0, s), rnd.uniform(0, s)
        for ix in range(29):
            for iy in range(29):
                x, y = ix * step, iy * step
                d = math.hypot(x - cx, y - cy) / s
                r = step * 0.45 * max(0.05, 1 - d)
                p.drawEllipse(QPointF(x, y), r, r)
    elif style == "waves":
        sky = QLinearGradient(0, 0, 0, s)
        sky.setColorAt(0, cols[-1])
        sky.setColorAt(1, cols[2 % len(cols)])
        p.fillRect(img.rect(), sky)
        p.setPen(Qt.PenStyle.NoPen)
        for layer in range(5):
            c = QColor(cols[layer % len(cols)]).darker(100 + layer * 25)
            p.setBrush(c)
            base = s * (0.45 + layer * 0.11)
            amp, freq, phase = s * rnd.uniform(0.03, 0.09), rnd.uniform(1.0, 3.0), rnd.uniform(0, 6.28)
            path = QPainterPath(QPointF(0, s))
            for i in range(0, 101):
                x = s * i / 100
                path.lineTo(x, base + amp * math.sin(freq * 6.28 * i / 100 + phase))
            path.lineTo(s, s)
            path.closeSubpath()
            p.drawPath(path)
    elif style == "brush":
        for _ in range(60):
            c = pick()
            c.setAlpha(rnd.randint(60, 180))
            p.setPen(QPen(c, s * rnd.uniform(0.01, 0.06), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            path = QPainterPath(QPointF(rnd.uniform(0, s), rnd.uniform(0, s)))
            for _ in range(3):
                path.quadTo(QPointF(rnd.uniform(0, s), rnd.uniform(0, s)), QPointF(rnd.uniform(0, s), rnd.uniform(0, s)))
            p.drawPath(path)
    else:  # gradient
        g = QLinearGradient(0, 0, s * rnd.uniform(0.4, 1), s)
        for i, c in enumerate(cols):
            g.setColorAt(i / max(1, len(cols) - 1), c)
        p.fillRect(img.rect(), g)
        vign = QRadialGradient(QPointF(s / 2, s / 2), s * 0.75)
        vign.setColorAt(0.6, QColor(0, 0, 0, 0))
        vign.setColorAt(1, QColor(0, 0, 0, 140))
        p.fillRect(img.rect(), vign)
    # subtle film grain on every style
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(int(s * 1.5)):
        p.setBrush(QColor(255, 255, 255, rnd.randint(4, 14)) if rnd.random() < 0.5 else QColor(0, 0, 0, rnd.randint(4, 14)))
        p.drawRect(QRectF(rnd.uniform(0, s), rnd.uniform(0, s), s / 500 + 1, s / 500 + 1))
    p.end()
    return img


def _fit_font(text: str, family: str, max_width: float, start_px: float, bold: bool = True) -> QFont:
    font = QFont(family)
    font.setBold(bold)
    px = start_px
    while px > 8:
        font.setPixelSize(int(px))
        if QFontMetricsF(font).horizontalAdvance(text) <= max_width:
            break
        px *= 0.9
    return font


def _draw_text(p: QPainter, text: str, font: QFont, rect: QRectF, color: QColor) -> None:
    p.setFont(font)
    shadow = QColor(0, 0, 0, 170) if color.lightness() > 100 else QColor(255, 255, 255, 150)
    off = max(1.0, font.pixelSize() / 18)
    p.setPen(shadow)
    p.drawText(rect.translated(off, off), Qt.AlignmentFlag.AlignCenter, text)
    p.setPen(color)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


def compose(
    background: QImage,
    artist: str = "",
    album: str = "",
    year: int | None = None,
    logo: QImage | None = None,
    show_logo: bool = True,
    show_title: bool = True,
    position: str = "top",
    text_color: str | None = None,
    font_family: str = "Sans Serif",
) -> QImage:
    """Overlay the band logo (or the artist name as text) and the album title onto a square image."""
    size = min(background.width(), background.height())
    img = background.copy(0, 0, size, size).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if not (show_logo or show_title):
        return img
    s = float(size)
    margin = s * 0.06
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    band_h = s * 0.22
    top = {"top": margin, "center": s / 2 - band_h / 2, "bottom": s - margin - band_h - s * 0.1}.get(position, margin)
    color = QColor(text_color) if text_color else _auto_text_color(img, QRectF(0, top, s, band_h))
    if show_logo:
        if logo is not None and not logo.isNull():
            box = QRectF(margin, top, s - 2 * margin, band_h)
            scaled = logo.scaled(int(box.width()), int(box.height()), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            x = box.x() + (box.width() - scaled.width()) / 2
            y = box.y() + (box.height() - scaled.height()) / 2
            p.drawImage(QPointF(x, y), scaled)
        elif artist:
            font = _fit_font(artist.upper(), font_family, s - 2 * margin, s * 0.11)
            _draw_text(p, artist.upper(), font, QRectF(margin, top, s - 2 * margin, band_h), color)
    if show_title and album:
        title = album + (f"  ·  {year}" if year else "")
        font = _fit_font(title, font_family, s - 2 * margin, s * 0.055, bold=False)
        ty = s - margin - s * 0.08 if position != "bottom" else top + band_h
        _draw_text(p, title, font, QRectF(margin, ty, s - 2 * margin, s * 0.08), color)
    p.end()
    return img


def _auto_text_color(img: QImage, region: QRectF) -> QColor:
    """White on dark backgrounds, near-black on light ones."""
    total, n = 0, 0
    step = max(1, int(region.width() / 24))
    for x in range(int(region.left()), int(region.right()), step):
        for y in range(int(region.top()), int(region.bottom()), step):
            if 0 <= x < img.width() and 0 <= y < img.height():
                total += QColor(img.pixel(x, y)).lightness()
                n += 1
    return QColor("#ffffff") if (total / max(1, n)) < 140 else QColor("#111111")


def disc_mask(img: QImage) -> QImage:
    """Circular crop with a centre hole, for generated disc art (transparent PNG)."""
    size = min(img.width(), img.height())
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, size, size))
    hole = QPainterPath()
    hole.addEllipse(QRectF(size * 0.43, size * 0.43, size * 0.14, size * 0.14))
    p.setClipPath(path.subtracted(hole))
    p.drawImage(0, 0, img)
    p.end()
    return out
