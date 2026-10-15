# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""Shared Qt widgets: the candidate thumbnail grid and a background-task runner."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem

from ..model import ArtType, Candidate, Tier

log = logging.getLogger("coverup.ui")

ROLE = Qt.ItemDataRole.UserRole
THUMB = 150

TIER_TEXT = {Tier.A: "exact release", Tier.B: "release group", Tier.C: "unanchored", Tier.G: "AI/template"}
TIER_COLOR = {Tier.A: "#2e7d32", Tier.B: "#1565c0", Tier.C: "#8d6e63", Tier.G: "#8e24aa"}


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


def placeholder_icon(text: str = "…") -> QIcon:
    pm = QPixmap(THUMB, THUMB)
    pm.fill(QColor("#555555"))
    p = QPainter(pm)
    p.setPen(QColor("#dddddd"))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return QIcon(pm)


def icon_for(c: Candidate) -> QIcon:
    if c.thumb_data:
        img = QImage()
        if img.loadFromData(c.thumb_data):
            pm = QPixmap.fromImage(
                img.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
            if c.generated:
                p = QPainter(pm)
                p.fillRect(0, 0, 34, 16, QColor(TIER_COLOR[Tier.G]))
                p.setPen(QColor("white"))
                p.drawText(2, 12, "AI")
                p.end()
            return QIcon(pm)
    return placeholder_icon("no preview")


def describe(c: Candidate) -> str:
    size = f"{c.width}x{c.height}" if c.width else "size ?"
    extra = f" · disc {c.disc_number}" if c.art_type == ArtType.DISC and c.disc_number else ""
    unl = " · unlabelled" if c.art_type == ArtType.OTHER else ""
    return f"{c.provider}{extra}{unl}\n{size} · {c.tier.value} · {c.score:.0f}"


def tooltip(c: Candidate, existing: Candidate | None = None) -> str:
    lines = [
        f"<b>{c.provider}</b> ({TIER_TEXT[c.tier]}, tier {c.tier.value})",
        f"Size: {c.width}x{c.height}" + ("" if c.dims_known else " (not yet measured)"),
        f"Score: {c.score:.1f}",
    ]
    if c.breakdown:
        lines.append("<br>".join(f"&nbsp;&nbsp;{k}: {v:+.1f}" for k, v in c.breakdown.items()))
    if c.rejected_reason:
        lines.append(f"<span style='color:#c62828'>Not eligible: {c.rejected_reason}</span>")
    if c.comment:
        lines.append(f"Note: {c.comment}")
    if c.attribution:
        lines.append(f"Source: {c.attribution}")
    if c.generated:
        lines.append("<b>AI/template-generated art</b>, labelled as such when applied")
    if existing is not None and existing.width:
        lines.append(f"Current cover: {existing.width}x{existing.height}")
    if c.url:
        lines.append(f"<small>{c.url[:120]}</small>")
    return "<br>".join(lines)


class CandidateGrid(QListWidget):
    def __init__(self, multi: bool = False, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(THUMB, THUMB))
        self.setGridSize(QSize(THUMB + 30, THUMB + 54))
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(True)
        self.setSpacing(4)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection if multi else QAbstractItemView.SelectionMode.SingleSelection
        )
        self.existing: Candidate | None = None

    def set_candidates(self, cands: list[Candidate], show_rejected: bool = False, preselect: list[Candidate] | None = None) -> None:
        keep = {id(c) for c in (preselect if preselect is not None else self.selected())}
        self.clear()
        ordered = sorted(cands, key=lambda c: (bool(c.rejected_reason), -c.tier.rank if c.tier != Tier.G else 0, -c.score))
        for c in ordered:
            if c.rejected_reason and not show_rejected:
                continue
            item = QListWidgetItem(icon_for(c), describe(c))
            item.setData(ROLE, c)
            item.setToolTip(tooltip(c, self.existing))
            if c.rejected_reason:
                item.setForeground(QColor("#9e9e9e"))
            else:
                item.setForeground(QColor(TIER_COLOR[c.tier]))
            self.addItem(item)
            if id(c) in keep:
                item.setSelected(True)

    def add_candidate(self, c: Candidate, select: bool = True) -> None:
        item = QListWidgetItem(icon_for(c), describe(c))
        item.setData(ROLE, c)
        item.setToolTip(tooltip(c, self.existing))
        self.insertItem(0, item)
        if select:
            if self.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection:
                self.clearSelection()
            item.setSelected(True)
            self.scrollToItem(item)

    def selected(self) -> list[Candidate]:
        return [i.data(ROLE) for i in self.selectedItems()]

    def all(self) -> list[Candidate]:
        return [self.item(i).data(ROLE) for i in range(self.count())]
