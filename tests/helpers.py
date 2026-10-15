# -*- coding: utf-8 -*-
"""Test helpers: synthetic images (Qt) and a fake HTTP client serving canned responses."""

from __future__ import annotations

import json
import threading

from coverup.net import HttpClient, HttpError, Response


def make_image(pattern: str = "a", size: int = 600, fmt: str = "jpeg", w: int | None = None, h: int | None = None) -> bytes:
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF
    from PyQt6.QtGui import QColor, QImage, QPainter

    w, h = w or size, h or size
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    if pattern == "a":  # horizontal gradient bars
        for x in range(w):
            v = int(255 * x / max(1, w - 1))
            p.setPen(QColor(v, 80, 255 - v))
            p.drawLine(x, 0, x, h)
    elif pattern == "b":  # checkerboard
        step = max(4, w // 8)
        for y in range(0, h, step):
            for x in range(0, w, step):
                p.fillRect(QRectF(x, y, step, step), QColor("white") if ((x // step + y // step) % 2) else QColor("black"))
    elif pattern == "c":  # circles
        img.fill(QColor("#203040"))
        p.setBrush(QColor("#f0c040"))
        for i in range(5):
            p.drawEllipse(QPointF(w * (i + 1) / 6, h / 2 + (i % 2) * h / 5), w / 10, w / 10)
    elif pattern == "blank":
        img.fill(QColor("#808080"))
    p.end()
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(dev, "JPEG" if fmt == "jpeg" else "PNG", 90)
    dev.close()
    return bytes(buf.data())


class FakeHttp(HttpClient):
    """Routes GETs by exact URL or by prefix to bytes / JSON-able objects / HttpError status codes."""

    def __init__(self, routes: dict[str, object] | None = None):
        super().__init__(version="test", cache_dir=None)
        self.routes = dict(routes or {})
        self.calls: list[str] = []
        self.posts: list[tuple[str, object]] = []
        self.lock = threading.Lock()

    def _lookup(self, url: str):
        if url in self.routes:
            return self.routes[url]
        best = None
        for k in self.routes:
            if url.startswith(k) and (best is None or len(k) > len(best)):
                best = k
        if best is None:
            raise HttpError(404, url)
        return self.routes[best]

    def get(self, url, headers=None, cache=True, max_bytes=0, range_bytes=None):
        with self.lock:
            self.calls.append(url)
        val = self._lookup(url)
        if isinstance(val, int):
            raise HttpError(val, url)
        if isinstance(val, (bytes, bytearray)):
            data = bytes(val)
            return Response(url, 200, data[:range_bytes] if range_bytes else data, {})
        return Response(url, 200, json.dumps(val).encode("utf-8"), {})

    def post_json(self, url, payload, headers=None, timeout=None):
        self.posts.append((url, payload))
        val = self._lookup(url)
        if isinstance(val, int):
            raise HttpError(val, url)
        return val
