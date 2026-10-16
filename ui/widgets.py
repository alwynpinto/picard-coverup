# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""Shared Qt widgets: candidate cards/grid, the big preview, and a background-task runner.

The UI follows the system theme (palette colours); the only fixed colours are the four trust chips,
which carry meaning: exact release, same album, search match, generated.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from PyQt6.QtCore import QObject, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPalette, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QLabel, QListView, QListWidget, QListWidgetItem, QSizePolicy, QVBoxLayout, QWidget

from ..model import ArtType, Candidate, Tier

log = logging.getLogger("coverup.ui")

ROLE = Qt.ItemDataRole.UserRole
THUMB = 156

SOURCE_NAMES = {
    "caa": "Cover Art Archive",
    "discogs": "Discogs",
    "fanart": "Fanart.tv",
    "audiodb": "TheAudioDB",
    "itunes": "Apple Music",
    "deezer": "Deezer",
    "lastfm": "Last.fm",
    "websearch": "Web search",
    "local": "In your folder",
    "embedded": "Current cover",
    "manual": "Added by you",
    "generated": "Generated",
}
TRUST = {
    Tier.A: ("Exact release", "#2e7d32"),
    Tier.B: ("Same album", "#1565c0"),
    Tier.C: ("Search match", "#9a5b00"),
    Tier.G: ("Generated", "#7b1fa2"),
}
TRUST_HELP = {
    Tier.A: "This image belongs to the exact release you tagged (its MusicBrainz or Discogs entry).",
    Tier.B: "This image belongs to the same album, but possibly another edition.",
    Tier.C: "Found by searching for the artist and title. It is trusted only when several sources show the same picture.",
    Tier.G: "Made by CoverUp. It is labelled as generated wherever it is saved.",
}


def source_name(c: Candidate) -> str:
    return SOURCE_NAMES.get(c.provider, c.provider)


def size_text(c: Candidate) -> str:
    return f"{c.width} × {c.height}" if c.width else "size unknown"


class _Bridge(QObject):
    done = pyqtSignal(object, object, object)  # callback, result, error


_bridge: _Bridge | None = None


def run_in_background(func: Callable[[], object], callback: Callable[[object, BaseException | None], None]) -> None:
    """Run ``func`` off the GUI thread and call ``callback(result, error)`` on the GUI thread.

    Uses Picard's thread pool when available, otherwise a plain thread (tests)."""
    global _bridge
    try:
        from picard.util import thread

        def next_func(result=None, error=None):
            callback(result, error)

        thread.run_task(func, next_func, traceback=False)
        return
    except Exception:
        pass
    if _bridge is None:
        _bridge = _Bridge()
        _bridge.done.connect(lambda cb, res, err: cb(res, err), Qt.ConnectionType.QueuedConnection)

    def work():
        try:
            res = func()
            _bridge.done.emit(callback, res, None)
        except BaseException as exc:  # noqa: BLE001
            log.exception("Background task failed")
            _bridge.done.emit(callback, None, exc)

    threading.Thread(target=work, daemon=True).start()


def image_of(c: Candidate | None) -> QImage | None:
    if c is None:
        return None
    data = c.thumb_data or c.data
    if not data:
        return None
    img = QImage()
    return img if img.loadFromData(data) else None


def _chip(p: QPainter, x: float, y: float, text: str, color: str, align_right: bool = False, width_limit: float = 999) -> None:
    f = QFont(p.font())
    f.setPixelSize(11)
    f.setBold(True)
    p.setFont(f)
    w = min(width_limit, p.fontMetrics().horizontalAdvance(text) + 12)
    h = 18
    if align_right:
        x -= w
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), 4, 4)
    p.fillPath(path, QColor(color))
    p.setPen(QColor("white"))
    p.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignCenter, text)


def card_pixmap(c: Candidate, size: int = THUMB, pick: bool = False) -> QPixmap:
    """Square tile: the image letterboxed, a trust chip, and a 'Pick' chip on CoverUp's choice."""
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    img = image_of(c)
    if img is not None:
        scaled = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        p.drawImage(int((size - scaled.width()) / 2), int((size - scaled.height()) / 2), scaled)
    else:
        p.fillRect(0, 0, size, size, QColor(128, 128, 128, 60))
        p.setPen(QColor(128, 128, 128))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "No preview")
    if c.rejected_reason:
        p.fillRect(0, 0, size, size, QColor(255, 255, 255, 140))
    label, color = TRUST[c.tier]
    if c.generated and c.extra.get("method") == "ai":
        label = "AI generated"
    _chip(p, 4, size - 22, label, color)
    if pick:
        _chip(p, size - 4, 4, "CoverUp pick", "#00695c", align_right=True)
    p.end()
    return pm


ARTIST_KIND = {
    ArtType.ARTIST_THUMB: "Photo",
    ArtType.ARTIST_LOGO: "Logo",
    ArtType.ARTIST_BACKGROUND: "Background",
    ArtType.ARTIST_BANNER: "Banner",
}


def card_text(c: Candidate) -> str:
    extra = ""
    if c.art_type in ARTIST_KIND:
        extra = f" · {ARTIST_KIND[c.art_type].lower()}"
    elif c.art_type == ArtType.OTHER:
        extra = " · unlabelled"
    elif c.rejected_reason:
        extra = " · too small" if c.rejected_reason.startswith("Too small") else " · not eligible"
    return f"{source_name(c)}\n{size_text(c)}{extra}"


def tooltip(c: Candidate) -> str:
    lines = [f"<b>{source_name(c)}</b> · {TRUST[c.tier][0]}", size_text(c)]
    if c.rejected_reason:
        lines.append(f"Not used automatically: {c.rejected_reason}")
    if c.comment:
        lines.append(c.comment)
    return "<br>".join(lines)


class CandidateGrid(QListWidget):
    """Thumbnail grid. Single choice by default; booklet and artist slots allow several."""

    def __init__(self, multi: bool = False, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(THUMB, THUMB))
        self.setGridSize(QSize(THUMB + 24, THUMB + 48))
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection if multi else QAbstractItemView.SelectionMode.SingleSelection
        )
        self.pick_id: int | None = None

    def set_candidates(self, cands: list[Candidate], show_rejected: bool, selected: list[Candidate], pick: Candidate | None = None) -> None:
        keep = {id(c) for c in selected}
        self.pick_id = id(pick) if pick is not None else None
        self.blockSignals(True)
        self.clear()
        ordered = sorted(cands, key=lambda c: (id(c) != self.pick_id, bool(c.rejected_reason), -c.tier.rank if c.tier != Tier.G else 0, -c.score))
        for c in ordered:
            if c.rejected_reason and not show_rejected:
                continue
            self._add(c, id(c) in keep)
        self.blockSignals(False)

    def _add(self, c: Candidate, selected: bool, at: int | None = None) -> QListWidgetItem:
        item = QListWidgetItem(QIcon(card_pixmap(c, pick=id(c) == self.pick_id)), card_text(c))
        item.setData(ROLE, c)
        item.setToolTip(tooltip(c))
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        if at is None:
            self.addItem(item)
        else:
            self.insertItem(at, item)
        item.setSelected(selected)
        return item

    def add_candidate(self, c: Candidate, select: bool = True) -> None:
        if select and self.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection:
            self.clearSelection()
        item = self._add(c, select, at=0)
        self.scrollToItem(item)

    def selected(self) -> list[Candidate]:
        return [i.data(ROLE) for i in self.selectedItems()]

    def all(self) -> list[Candidate]:
        return [self.item(i).data(ROLE) for i in range(self.count())]


class Preview(QWidget):
    """The large view of one image, with plain-language details and a comparison with the current cover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setFixedSize(300, 300)
        self.title = QLabel()
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() * 1.15)
        f.setBold(True)
        self.title.setFont(f)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.image)
        lay.addWidget(self.title)
        lay.addWidget(self.details, 1)
        self.current: Candidate | None = None
        self.show_empty("Select an image to see it larger.")

    def show_empty(self, text: str) -> None:
        pm = QPixmap(300, 300)
        pm.fill(self.palette().color(QPalette.ColorRole.Base))
        p = QPainter(pm)
        p.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        p.drawRect(0, 0, 299, 299)
        p.drawText(QRectF(20, 0, 260, 300), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
        p.end()
        self.image.setPixmap(pm)
        self.title.setText("")
        self.details.setText("")

    def show_candidate(self, c: Candidate | None) -> None:
        if c is None:
            self.show_empty("Select an image to see it larger.")
            return
        img = image_of(c)
        if img is not None:
            self.image.setPixmap(QPixmap.fromImage(img.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
        else:
            self.show_empty("No preview available.")
        label, color = TRUST[c.tier]
        self.title.setText(source_name(c))
        rows = [f"<span style='color:{color}; font-weight:600'>{label}</span>: {TRUST_HELP[c.tier]}", f"<b>Size</b>: {size_text(c)}"]
        cur = self.current
        if cur is not None and cur.width and c.width and c is not cur:
            ratio = (c.width * c.height) / max(1, cur.width * cur.height)
            if ratio > 1.05:
                rows.append(f"<b>Compared with your current cover</b> ({cur.width} × {cur.height}): {ratio:.1f}× the pixels")
            elif ratio < 0.95:
                rows.append(f"<b>Compared with your current cover</b> ({cur.width} × {cur.height}): smaller")
            else:
                rows.append("<b>Compared with your current cover</b>: same size")
        if c.rejected_reason:
            rows.append(f"<b>Not chosen automatically</b>: {c.rejected_reason}")
        if c.comment and not c.generated:
            rows.append(f"<b>Note</b>: {c.comment}")
        if c.generated:
            rows.append(f"<b>Style</b>: {c.extra.get('template', '')} (seed {c.extra.get('seed', '')})")
        if c.score and not c.generated:
            rows.append(f"<b>Score</b>: {c.score:.0f} of 100")
        self.details.setText("<br><br>".join(rows))
