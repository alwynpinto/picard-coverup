# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""Crop window: drag a rectangle over the picture, move it by dragging inside, optionally keep it square."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import imaging

MAX_VIEW = 640


class CropArea(QWidget):
    """Shows the image scaled to fit; ``selection`` is kept in image pixels."""

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.image = image
        scale = min(1.0, MAX_VIEW / max(image.width(), image.height()))
        self.scale = scale
        self.pix = QPixmap.fromImage(image).scaled(
            max(1, round(image.width() * scale)), max(1, round(image.height() * scale)),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        self.setFixedSize(self.pix.size())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.square = True
        self.selection = QRect(0, 0, image.width(), image.height())
        self._anchor: QPoint | None = None
        self._moving: QPoint | None = None

    # image <-> view coordinates
    def _to_image(self, p: QPoint) -> QPoint:
        return QPoint(max(0, min(self.image.width(), round(p.x() / self.scale))), max(0, min(self.image.height(), round(p.y() / self.scale))))

    def reset(self) -> None:
        self.selection = QRect(0, 0, self.image.width(), self.image.height())
        self.update()

    def make_square(self) -> None:
        r = self.selection
        side = min(r.width(), r.height())
        self.selection = QRect(r.x(), r.y(), side, side)
        self.update()

    def mousePressEvent(self, event) -> None:
        p = self._to_image(event.position().toPoint())
        if self.selection.contains(p) and self.selection != QRect(0, 0, self.image.width(), self.image.height()):
            self._moving = p - self.selection.topLeft()
        else:
            self._anchor = p
            self.selection = QRect(p, p)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        p = self._to_image(event.position().toPoint())
        if self._moving is not None:
            tl = p - self._moving
            x = max(0, min(self.image.width() - self.selection.width(), tl.x()))
            y = max(0, min(self.image.height() - self.selection.height(), tl.y()))
            self.selection.moveTo(x, y)
        elif self._anchor is not None:
            a = self._anchor
            dx, dy = p.x() - a.x(), p.y() - a.y()
            if self.square:
                side = min(abs(dx), abs(dy))
                dx, dy = (side if dx >= 0 else -side), (side if dy >= 0 else -side)
            self.selection = QRect(a, QPoint(a.x() + dx, a.y() + dy)).normalized()
        self.update()

    def mouseReleaseEvent(self, _event) -> None:
        self._anchor = self._moving = None
        if self.selection.width() < 2 or self.selection.height() < 2:
            self.reset()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.drawPixmap(0, 0, self.pix)
        sel = QRectF(self.selection.x() * self.scale, self.selection.y() * self.scale, self.selection.width() * self.scale, self.selection.height() * self.scale)
        dim = QColor(0, 0, 0, 140)
        for r in (QRectF(0, 0, self.width(), sel.top()), QRectF(0, sel.bottom(), self.width(), self.height() - sel.bottom()),
                  QRectF(0, sel.top(), sel.left(), sel.height()), QRectF(sel.right(), sel.top(), self.width() - sel.right(), sel.height())):
            p.fillRect(r, dim)
        p.setPen(QPen(QColor("white"), 1, Qt.PenStyle.DashLine))
        p.drawRect(sel)
        p.end()


class CropDialog(QDialog):
    def __init__(self, data: bytes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crop")
        self.image = imaging.load(data)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Drag over the picture to choose what to keep. Drag inside the box to move it."))
        self.area = CropArea(self.image)
        lay.addWidget(self.area, 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        self.square = QCheckBox("Keep it square")
        self.square.setChecked(True)
        self.square.toggled.connect(self._square_toggled)
        row.addWidget(self.square)
        self.info = QLabel()
        row.addStretch(1)
        row.addWidget(self.info)
        lay.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Reset)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Crop")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self.area.reset)
        lay.addWidget(buttons)
        self._tick()

    def _square_toggled(self, on: bool) -> None:
        self.area.square = on
        if on:
            self.area.make_square()

    def _tick(self) -> None:
        from PyQt6.QtCore import QTimer

        t = QTimer(self)
        t.timeout.connect(lambda: self.info.setText(f"{self.area.selection.width()} × {self.area.selection.height()} px"))
        t.start(150)

    def rect(self) -> QRect:
        return self.area.selection
